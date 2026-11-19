from functools import cache

from flask import g, has_app_context, has_request_context, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from flask_artisan.auth.authenticatable import AuthenticationError
from flask_artisan.auth.tokens import find_token

SESSION_KEY = "_auth_user_id"


@cache
def _dummy_hash() -> str:
    return generate_password_hash("dummy-password")


class Guard:
    """Résout l'utilisateur de la requête courante ; le résultat est gardé dans `g`."""

    def __init__(self, name: str, model: type):
        self.name = name
        self.model = model

    def user(self):
        if not has_request_context():
            return None
        key = f"_auth_user_{self.name}"
        if key not in g:
            setattr(g, key, self._resolve())
        return getattr(g, key)

    def _remember(self, user) -> None:
        setattr(g, f"_auth_user_{self.name}", user)

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
        # where(col, None) deviendrait IS NULL : un identifiant absent ne trouve personne.
        if password is None or not credentials or None in credentials.values():
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
        return None if user_id is None else self.model.find(user_id)

    def attempt(self, **credentials) -> bool:
        user = self.validate(**credentials)
        if user is not None:
            self.login(user)
        return user is not None

    def login(self, user) -> None:
        session.clear()  # contre la fixation de session : un cookie Flask n'a pas d'id à régénérer
        session[SESSION_KEY] = user.id
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
        if name is None and has_app_context():
            name = g.get("_auth_guard")
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
        g._auth_guard = name

    def __getattr__(self, name: str):
        if name in RELAYED:
            return getattr(self.guard(), name)
        raise AttributeError(name)
