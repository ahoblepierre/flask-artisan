"""Les jobs : `Job`, son exécution (contexte, injection, `failed`)."""

import logging
from datetime import timedelta

from flask import current_app, has_app_context

from flask_artisan.mail import Mailable, Mailer
from flask_artisan.queue.serialization import class_path, import_class

logger = logging.getLogger("flask_artisan.queue")


class Job:
    """Un travail à exécuter en arrière-plan : surchargez `handle()` (dépendances injectées)."""

    queue: str | None = None  # None : la file de la connexion ("default")
    tries: int = 1
    backoff: int | list[int] = 0
    timeout: int = 60

    def handle(self):
        raise NotImplementedError(f"{type(self).__name__} doit définir handle().")

    def failed(self, exc: Exception) -> None:
        """Appelé une fois, après le dernier essai en échec."""

    # --- options d'envoi (attributs privés : non sérialisés avec le job) ---

    def on_queue(self, name: str) -> "Job":
        self._queue = name
        return self

    def delay(self, delay: float | timedelta) -> "Job":
        seconds = delay.total_seconds() if isinstance(delay, timedelta) else delay
        self._delay = int(seconds)
        return self

    @property
    def queue_name(self) -> str | None:
        return getattr(self, "_queue", None) or self.queue

    @property
    def delay_seconds(self) -> int:
        return getattr(self, "_delay", 0)

    # --- envoi ---

    @classmethod
    def dispatch(cls, *args, **kwargs):
        from flask_artisan.helpers import dispatch

        return dispatch(cls(*args, **kwargs))

    @classmethod
    def dispatch_sync(cls, *args, **kwargs) -> None:
        from flask_artisan.helpers import app

        app("queue").push_sync(cls(*args, **kwargs))


def execute(app, job: Job, *, final: bool) -> None:
    """Exécute `handle` ; `failed` si c'était le dernier essai.

    Réutilise le contexte de l'appelant s'il est celui de l'app : un job sync ne doit pas retirer
    la session de base de la requête (le worker, lui, pousse un contexte propre à chaque job).
    """
    if not (has_app_context() and current_app._get_current_object() is app):
        with app.app_context():
            _call(app, job, final)
    else:
        _call(app, job, final)


def _call(app, job: Job, final: bool) -> None:
    try:
        app.call(job.handle)
    except Exception as exc:
        if final:
            try:
                job.failed(exc)
            except Exception:
                logger.exception("Erreur dans %s.failed()", type(job).__name__)
        raise


class SendQueuedMailable(Job):
    """Job du framework : envoie un mailable mis en file par `Mail.to(...).queue(...)`."""

    @classmethod
    def wrap(cls, mailable: Mailable, envelope: dict, mailer: str | None) -> "SendQueuedMailable":
        job = cls()
        job.mailable_class = class_path(type(mailable))
        job.mailable_data = {k: v for k, v in vars(mailable).items() if not k.startswith("_")}
        job.envelope = {kind: [list(a) for a in addresses] for kind, addresses in envelope.items()}
        job.mailer = mailer
        return job

    def handle(self, mailer: Mailer) -> None:
        cls = import_class(self.mailable_class, Mailable)
        mailable = cls.__new__(cls)
        for key, value in self.mailable_data.items():
            if key.startswith("_"):
                raise TypeError(f"Attribut invalide dans un mail en file : {key!r}.")
            setattr(mailable, key, value)
        envelope = {
            kind: [tuple(a) for a in addresses] for kind, addresses in self.envelope.items()
        }
        mailer._send(self.mailer, envelope, mailable)


class ShouldQueue:
    """Marqueur : un écouteur qui en hérite est exécuté par la file, pas pendant `dispatch`.

    Il peut porter `queue`, `tries`, `backoff` et `timeout`, comme un job.
    """


class CallQueuedListener(Job):
    """Job du framework : appelle un écouteur `ShouldQueue` avec l'événement reconstruit."""

    @classmethod
    def wrap(cls, listener: type, method: str, event) -> "CallQueuedListener":
        job = cls()
        job.listener = class_path(listener)
        job.method = method
        job.event_class = class_path(type(event))
        job.event_data = {k: v for k, v in vars(event).items() if not k.startswith("_")}
        for setting in ("tries", "backoff", "timeout"):
            if hasattr(listener, setting):
                setattr(job, setting, getattr(listener, setting))
        job.on_queue(getattr(listener, "queue", None))
        return job

    def handle(self) -> None:
        from flask_artisan.helpers import app

        if not isinstance(self.method, str) or self.method.startswith("_"):
            raise TypeError(f"Méthode d'écouteur invalide : {self.method!r}.")
        listener_class = import_class(self.listener, ShouldQueue)
        event_class = import_class(self.event_class, object)
        event = event_class.__new__(event_class)
        for key, value in self.event_data.items():
            if key.startswith("_"):
                raise TypeError(f"Attribut invalide dans un événement en file : {key!r}.")
            setattr(event, key, value)
        getattr(app().make(listener_class), self.method)(event)
