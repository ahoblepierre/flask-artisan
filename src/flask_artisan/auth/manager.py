import hashlib
import hmac
from functools import cache

from flask import has_request_context, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from flask_artisan.auth.authenticatable import AuthenticationError
from flask_artisan.auth.tokens import find_token

SESSION_KEY = "_auth_user_id"
# Empreinte du hash du mot de passe : changer le mot de passe (ou réutiliser l'id) coupe la session.
SESSION_HASH_KEY = "_auth_password_hash"


@cache
def _dummy_hash() -> str:
    return generate_password_hash("dummy-password")


def _state() -> dict:
    """État d'auth de la requête (pas de `g`, partagé si un app context englobe plusieurs requêtes)."""
    return request.environ.setdefault("flask_artisan.auth", {})


def _fingerprint(user) -> str:
    return hashlib.sha256((user.password or "").encode()).hexdigest()


class Guard:
    """Résout l'utilisateur de la requête courante ; le résultat est gardé dans `g`."""

    def __init__(self, name: str, model: type):
        self.name = name
        self.model = model

    def user(self):
        if not has_request_context():
            return None
        state = _state()
        key = f"user:{self.name}"
        if key not in state:
            state[key] = self._resolve()
        return state[key]

    def _remember(self, user) -> None:
        _state()[f"user:{self.name}"] = user

    def id(self):
        user = self.user()
        return None if user is None else user.id

    def check(self) -> bool:
        return self.user() is not None

    def guest(self) -> bool:
        return not self.check()

    def validate(self, **credentials):
        """L'utilisateur si les identifiants sont bons, sinon None ; ne connecte personne."""
        password = credentials.pop("password", None)
        # Frontière de confiance (JSON du client) : que des chaînes. None deviendrait IS NULL.
        if not credentials or not all(
            isinstance(v, str) for v in (password, *credentials.values())
        ):
            return None
        query = self.model.query()
        for key, value in credentials.items():
            query = query.where(key, value)
        user = query.first()
        if user is None:
            check_password_hash(_dummy_hash(), password)  # même durée qu'un email connu
            return None
        return user if user.check_password(password) else None

    def _resolve(self):
        raise NotImplementedError


class SessionGuard(Guard):
    def _resolve(self):
        user_id = session.get(SESSION_KEY)
        user = None if user_id is None else self.model.find(user_id)
        expected = session.get(SESSION_HASH_KEY, "")
        if user is None or not hmac.compare_digest(_fingerprint(user), expected):
            return None
        return user

    def attempt(self, **credentials) -> bool:
        user = self.validate(**credentials)
        if user is not None:
            self.login(user)
        return user is not None

    def login(self, user) -> None:
        session.clear()  # contre la fixation de session : un cookie Flask n'a pas d'id à régénérer
        session[SESSION_KEY] = user.id
        session[SESSION_HASH_KEY] = _fingerprint(user)
        self._remember(user)

    def logout(self) -> None:
        session.clear()
        self._remember(None)


class TokenGuard(Guard):
    def _resolve(self):
        scheme, _, plain = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not plain.strip():
            return None
        token = find_token(plain.strip())
        user = None if token is None else self.model.find(token.user_id)
        if user is not None:
            user._access_token = token
        return user

    def attempt(self, **credentials):
        raise AuthenticationError(
            f"Le guard '{self.name}' (token) est sans état : utilisez Auth.validate(...) "
            "puis user.create_token(nom)."
        )

    def login(self, user):
        self.attempt()

    def logout(self):
        raise AuthenticationError(
            f"Le guard '{self.name}' (token) est sans état : révoquez le token avec "
            "Auth.user().current_access_token().delete()."
        )


DRIVERS = {"session": SessionGuard, "token": TokenGuard}
RELAYED = {"user", "id", "check", "guest", "validate", "attempt", "login", "logout"}


class AuthManager:
    """Service `"auth"` (façade Auth) : construit les guards de config/auth.py."""

    def __init__(self, app):
        self._app = app

    def guard(self, name: str | None = None) -> Guard:
        config = self._app.make("config")
        if name is None and has_request_context():
            name = _state().get("guard")
        name = name or config.get("auth.defaults.guard")
        guards = config.get("auth.guards", {})
        if name not in guards:
            raise AuthenticationError(
                f"Guard '{name}' inconnu ; guards configurés : {', '.join(guards)}."
            )
        driver = guards[name].get("driver")
        if driver not in DRIVERS:
            raise AuthenticationError(
                f"Driver '{driver}' inconnu pour le guard '{name}' : {', '.join(DRIVERS)}."
            )
        model = config.get("auth.model")
        if model is None:
            raise AuthenticationError(
                "Déclarez le modèle utilisateur : 'model' dans config/auth.py."
            )
        return DRIVERS[driver](name, model)

    def should_use(self, name: str) -> None:
        """Guard par défaut pour la requête courante (comme shouldUse de Laravel)."""
        self.guard(name)
        _state()["guard"] = name

    def __getattr__(self, name: str):
        if name in RELAYED:
            return getattr(self.guard(), name)
        raise AttributeError(name)
