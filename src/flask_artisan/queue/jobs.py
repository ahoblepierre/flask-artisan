"""Les jobs : `Job`, son exécution (contexte, injection, `failed`)."""

import logging
from datetime import timedelta

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
    """Exécute `handle` dans un contexte d'application ; `failed` si c'était le dernier essai."""
    with app.app_context():  # sa fin retire la session de base (teardown du provider)
        try:
            app.call(job.handle)
        except Exception as exc:
            if final:
                try:
                    job.failed(exc)
                except Exception:
                    logger.exception("Erreur dans %s.failed()", type(job).__name__)
            raise
