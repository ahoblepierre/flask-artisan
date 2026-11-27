"""Client de test du framework : `app.test_client()` renvoie des réponses à assertions chaînables."""

from contextlib import nullcontext

from flask import current_app, has_app_context
from flask.testing import FlaskClient
from werkzeug.test import TestResponse as BaseTestResponse

_MISSING = object()


def _contains(actual, expected) -> bool:
    """Sous-ensemble de `assertJson` de Laravel : les dicts récursivement, le reste par égalité."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value) for key, value in expected.items()
        )
    return _same(actual, expected)


def _same(a, b) -> bool:
    """Égalité, sauf qu'un booléen n'égale jamais un nombre (`1 == True` en Python)."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_same, a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return a == b


class TestResponse(BaseTestResponse):
    __test__ = False  # pas une classe de tests pour pytest

    def _fail(self, message: str):
        raise AssertionError(
            f"{message}\nCorps ({self.status_code}) : {self.get_data()[:500].decode(errors='replace')}"
        )

    def _json(self):
        data = self.get_json(silent=True)
        if data is None:
            self._fail("La réponse n'est pas du JSON.")
        return data

    def assert_status(self, code: int):
        if self.status_code != code:
            self._fail(f"Statut attendu {code}, reçu {self.status_code}.")
        return self

    def assert_ok(self):
        return self.assert_status(200)

    def assert_json(self, data):
        actual = self._json()
        if not _contains(actual, data):
            self._fail(f"Le JSON ne contient pas {data!r}.\nReçu : {actual!r}")
        return self

    def assert_json_path(self, path: str, value):
        current = self._json()
        for segment in path.split("."):
            if isinstance(current, list) and segment.isdecimal() and int(segment) < len(current):
                current = current[int(segment)]
            elif isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                self._fail(f"Chemin JSON '{path}' : segment '{segment}' absent.")
        if not _same(current, value):
            self._fail(f"'{path}' vaut {current!r}, attendu {value!r}.")
        return self

    def assert_json_validation_errors(self, fields):
        self.assert_status(422)
        data = self._json()
        errors = data.get("errors") if isinstance(data, dict) else None
        if not isinstance(errors, dict):
            self._fail(f"Pas de clé 'errors' (dict) dans le JSON ; champs attendus : {fields}.")
        missing = [f for f in ([fields] if isinstance(fields, str) else fields) if f not in errors]
        if missing:
            self._fail(f"Pas d'erreur de validation pour {missing} ; erreurs : {list(errors)}.")
        return self

    def assert_header(self, name: str, value: str | None = None):
        actual = self.headers.get(name, _MISSING)
        if actual is _MISSING:
            self._fail(f"En-tête '{name}' absent.")
        if value is not None and actual != value:
            self._fail(f"En-tête '{name}' vaut {actual!r}, attendu {value!r}.")
        return self

    def assert_redirect(self, location: str | None = None):
        if self.status_code not in (301, 302, 303, 307, 308):
            self._fail(f"Redirection attendue, statut {self.status_code}.")
        if location is not None and self.location != location:
            self._fail(f"Redirection vers {self.location!r}, attendu {location!r}.")
        return self


class TestClient(FlaskClient):
    __test__ = False

    def __init__(self, application, response_wrapper=None, *args, **kwargs):
        # Garde la classe de réponse de l'app (JSON de Flask, response_class du projet).
        base = response_wrapper or application.response_class
        wrapper = type("TestResponse", (TestResponse, base), {})
        super().__init__(application, wrapper, *args, **kwargs)

    def acting_as(self, user, guard: str | None = None):
        """Authentifie les requêtes suivantes par le vrai guard (session écrite, ou vrai token).

        Remplace l'utilisateur d'un `acting_as` précédent, quel que soit son guard.
        """
        # Import tardif : flask_artisan.auth déclare la table des tokens.
        from flask_artisan.auth.manager import (
            SESSION_HASH_KEY,
            SESSION_KEY,
            AuthManager,
            TokenGuard,
            _fingerprint,
        )

        # Réutilise le contexte ouvert par l'appelant : en pousser un autre retirerait sa session de base.
        reuse = has_app_context() and current_app._get_current_object() is self.application
        with nullcontext() if reuse else self.application.app_context():
            resolved = self.application.make(AuthManager).guard(guard)
            if isinstance(resolved, TokenGuard):
                token = user.create_token("test")
                self.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"
                with self.session_transaction() as session:
                    session.pop(SESSION_KEY, None)
                    session.pop(SESSION_HASH_KEY, None)
                return self
        self.environ_base.pop("HTTP_AUTHORIZATION", None)
        with self.session_transaction() as session:
            session.clear()  # comme SessionGuard.login
            session[SESSION_KEY] = user.id
            session[SESSION_HASH_KEY] = _fingerprint(user)
        return self
