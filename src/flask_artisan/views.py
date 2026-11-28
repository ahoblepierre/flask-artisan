"""Fonctions des templates : `errors`, `old()`, `csrf_token()`, `csrf_field()`.

Les erreurs et saisies d'une validation HTML échouée sont flashées en session par le Router ;
`age_flash` (before_request) les sort de la session pour la seule requête suivante.
"""

import secrets

from flask import has_request_context, request, session
from flask.globals import request_ctx
from markupsafe import Markup, escape

FLASH_KEYS = {"_flash_errors": "errors", "_flash_old": "old"}


class ErrorBag:
    """Messages d'erreur par champ, comme `$errors` de Laravel."""

    def __init__(self, messages: dict | None = None):
        self._messages = dict(messages or {})

    def has(self, field: str) -> bool:
        return bool(self._messages.get(field))

    def get(self, field: str) -> list[str]:
        return list(self._messages.get(field, []))

    def first(self, field: str) -> str:
        return next(iter(self.get(field)), "")

    def all(self) -> list[str]:
        return [m for messages in self._messages.values() for m in messages]

    def any(self) -> bool:
        return bool(self.all())

    def __bool__(self) -> bool:
        return self.any()


def _flashed() -> dict:
    return request.environ.get("flask_artisan.flash", {}) if has_request_context() else {}


def _session_accessed() -> bool | None:
    """`accessed` de la session, lu sans le modifier ; None si Flask ne l'expose plus ainsi.

    Le proxy `session` et la propriété `RequestContext.session` (Flask 3.1) le mettent à True :
    on lit l'attribut d'instance, privé en 3.1 (`_session`), public en 3.0 (`session`).
    """
    attrs = vars(request_ctx._get_current_object())
    store = attrs.get("_session", attrs.get("session"))
    return getattr(store, "accessed", None)


def age_flash() -> None:
    """before_request : données flashées par la requête précédente, retirées de la session."""
    accessed_before = _session_accessed()
    store = session._get_current_object()
    # Pas de pop sans la clé : une requête d'API ne doit pas recevoir de cookie.
    data = {name: store.pop(key) for key, name in FLASH_KEYS.items() if key in store}
    if data:
        request.environ["flask_artisan.flash"] = data
    elif accessed_before is not None:
        # On annule notre propre lecture, pas celle d'un url_value_preprocessor, d'un
        # convertisseur ou de request_started, qui passent avant nous : sinon une réponse
        # dépendant de la session sortirait sans `Vary: Cookie`. Attribut introuvable : on
        # ne touche à rien (un `Vary: Cookie` de trop, jamais un de moins).
        store.accessed = accessed_before


def errors() -> ErrorBag:
    return ErrorBag(_flashed().get("errors"))


def old(key: str, default=""):
    return _flashed().get("old", {}).get(key, default)


def csrf_token() -> str:
    if "_token" not in session:
        session["_token"] = secrets.token_urlsafe(32)
    return session["_token"]


def csrf_field() -> Markup:
    return Markup(f'<input type="hidden" name="_token" value="{escape(csrf_token())}">')


def template_context() -> dict:
    return {"errors": errors(), "old": old, "csrf_token": csrf_token, "csrf_field": csrf_field}
