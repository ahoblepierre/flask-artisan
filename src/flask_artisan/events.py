"""Événements applicatifs façon Laravel : `Event.dispatch`, `Event.listen`, `Event.fake()`."""

from collections.abc import Callable
from typing import Any

__all__ = ["Dispatcher"]


def _describe(listener: Any) -> str:
    if isinstance(listener, tuple):
        return repr(listener)
    return getattr(listener, "__qualname__", repr(listener))


class Dispatcher:
    """Écouteurs par classe d'événement ; appelés dans l'ordre, de la classe exacte aux parents."""

    def __init__(self, app):
        self._app = app
        self._listeners: dict[type, list[Callable[[Any], Any]]] = {}

    def listen(self, event_class: type, listener) -> None:
        if not isinstance(event_class, type):
            raise TypeError(f"Un événement s'écoute par sa classe, pas {event_class!r}.")
        listeners = listener if isinstance(listener, list) else [listener]
        normalized = [self._normalize(event_class, item) for item in listeners]
        self._listeners.setdefault(event_class, []).extend(normalized)

    def dispatch(self, event) -> list:
        if isinstance(event, (type, str)):
            raise TypeError(
                f"dispatch attend une instance d'événement (ex. OrderShipped(...)), pas {event!r}."
            )
        results = []
        for cls in type(event).__mro__[:-1]:
            for listener in list(self._listeners.get(cls, ())):
                result = listener(event)
                results.append(result)
                if result is False:
                    return results
        return results

    def has_listeners(self, event_class: type) -> bool:
        return any(self._listeners.get(cls) for cls in event_class.__mro__[:-1])

    def forget(self, event_class: type) -> None:
        self._listeners.pop(event_class, None)

    def _normalize(self, event_class: type, listener) -> Callable[[Any], Any]:
        cls, method = None, "handle"
        if isinstance(listener, type):
            cls = listener
        elif isinstance(listener, tuple):
            if len(listener) == 2 and isinstance(listener[0], type):
                cls, method = listener
        elif callable(listener):
            return listener
        if cls is None or not isinstance(method, str) or not callable(getattr(cls, method, None)):
            raise TypeError(
                f"Écouteur invalide pour {event_class.__name__} : {_describe(listener)} "
                "(attendu : une classe avec handle(), un tuple (Classe, 'méthode') ou une fonction)."
            )
        app = self._app
        # Construit à chaque émission, comme Laravel : l'écouteur reçoit ses dépendances fraîches.
        return lambda event: getattr(app.make(cls), method)(event)
