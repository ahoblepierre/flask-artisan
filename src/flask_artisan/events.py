"""Événements applicatifs façon Laravel : `Event.dispatch`, `Event.listen`, `Event.fake()`."""

from collections import Counter
from collections.abc import Callable
from typing import Any, ClassVar

from flask_artisan.providers import ServiceProvider

__all__ = ["Dispatcher", "EventFake", "EventServiceProvider"]


def _describe(listener: Any) -> str:
    if isinstance(listener, tuple):
        return repr(listener)
    return getattr(listener, "__qualname__", repr(listener))


class Dispatcher:
    """Écouteurs par classe d'événement ; appelés dans l'ordre, de la classe exacte aux parents."""

    def __init__(self, app):
        self._app = app
        self._listeners: dict[type, list[Callable[[Any], Any]]] = {}
        # Mode fake : un état du dispatcher (pas une instance de remplacement), pour que les
        # services qui le tiennent déjà le voient aussi.
        self._faking = False
        self._faked: tuple[type, ...] = ()
        self._recorded: list = []

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
        if self._faking:
            self._recorded.append(event)
            if not self._faked or isinstance(event, self._faked):
                return []
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

    def fake(self, *event_classes: type) -> "EventFake":
        """Enregistre les événements ; ceux de `event_classes` (tous si vide) sans écouteurs."""
        self._faking = True
        self._faked = event_classes
        self._recorded = []
        return EventFake(self, self._recorded)

    def _unfake(self) -> None:
        self._faking = False
        self._faked = ()

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


class EventFake:
    """Assertions sur les événements émis depuis `Event.fake()`."""

    def __init__(self, dispatcher: Dispatcher, recorded: list):
        self._dispatcher = dispatcher
        self._recorded = recorded

    def restore(self) -> None:
        """Rend au dispatcher son fonctionnement normal ; les enregistrements restent lisibles."""
        if self._dispatcher._recorded is self._recorded:  # pas remplacé par un fake() plus récent
            self._dispatcher._unfake()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.restore()

    def dispatched(self, event_class: type) -> list:
        return [e for e in self._recorded if isinstance(e, event_class)]

    def _matching(self, event_class: type, callback) -> list:
        events = self.dispatched(event_class)
        return events if callback is None else [e for e in events if callback(e)]

    def assert_dispatched(self, event_class: type, callback=None) -> None:
        count = len(self._matching(event_class, callback))
        if not count:
            detail = " correspondant au callback" if callback else ""
            raise AssertionError(
                f"Événement {event_class.__name__}{detail} émis 0 fois, attendu au moins 1."
            )

    def assert_dispatched_times(self, event_class: type, times: int) -> None:
        count = len(self.dispatched(event_class))
        if count != times:
            raise AssertionError(
                f"Événement {event_class.__name__} émis {count} fois, attendu {times}."
            )

    def assert_not_dispatched(self, event_class: type, callback=None) -> None:
        count = len(self._matching(event_class, callback))
        if count:
            raise AssertionError(
                f"Événement {event_class.__name__} émis {count} fois, attendu aucune émission."
            )

    def assert_nothing_dispatched(self) -> None:
        counts = Counter(type(e).__name__ for e in self._recorded)
        if counts:
            emitted = ", ".join(f"{name} émis {n} fois" for name, n in counts.items())
            raise AssertionError(f"Aucun événement attendu, mais : {emitted}.")


class EventServiceProvider(ServiceProvider):
    """Déclare les écouteurs : `listen = {ClasseÉvénement: [écouteurs…]}`."""

    listen: ClassVar[dict] = {}

    def register(self) -> None:
        events = self.app.make("events")
        for event_class, listeners in self.listen.items():
            events.listen(event_class, listeners)
