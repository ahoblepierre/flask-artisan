"""Le gestionnaire de files (`"queue"`, façade `Queue`) et ses pilotes."""

from collections import Counter

from flask_artisan.queue.jobs import Job, execute
from flask_artisan.queue.serialization import restore, serialize

DEFAULT_CONNECTIONS = {"sync": {"driver": "sync"}}


class SyncDriver:
    """Exécute tout de suite, après un aller-retour de sérialisation (erreurs vues en dev)."""

    def __init__(self, app):
        self._app = app

    def push(self, job: Job, options: dict) -> None:
        execute(self._app, restore(serialize(job), Job), final=True)


class RqDriver:
    """Envoie le job à RQ (Redis), exécuté plus tard par `flask queue:work`."""

    def __init__(self, connection: dict):
        self._connection = connection

    def push(self, job: Job, options: dict) -> str:
        from flask_artisan.queue import worker

        options = {**options, "queue": options["queue"] or self._connection.get("queue")}
        return worker.enqueue(self._connection, serialize(job), options)


class _Connection:
    def __init__(self, manager: "QueueManager", name: str | None):
        self._manager = manager
        self._name = name

    def push(self, job: Job):
        return self._manager._push(self._name, job)


class QueueManager:
    """Le service `"queue"`. La config est relue à chaque envoi."""

    def __init__(self, app):
        self._app = app
        # Mode fake : un état du gestionnaire, vu aussi par les services qui le tiennent déjà.
        self._faking = False
        self._recorded: list = []

    def fake(self) -> "QueueFake":
        """Enregistre les jobs poussés, sans les exécuter ni les envoyer."""
        self._faking = True
        self._recorded = []
        return QueueFake(self, self._recorded)

    def _config(self, key: str, default=None):
        return self._app.make("config").get(f"queue.{key}", default)

    def _connection_config(self, name: str | None) -> tuple[str, dict]:
        name = name or self._config("default", "sync")
        connections = self._config("connections", DEFAULT_CONNECTIONS)
        if name not in connections:
            raise ValueError(f"Connexion de file inconnue : {name!r} (config queue.connections).")
        return name, connections[name]

    def _driver(self, name: str | None):
        name, options = self._connection_config(name)
        kind = options.get("driver")
        if kind == "sync":
            return SyncDriver(self._app)
        if kind == "rq":
            return RqDriver(options)
        raise ValueError(f"Pilote de file inconnu : {kind!r} (connexion {name!r}).")

    @staticmethod
    def _options(job: Job) -> dict:
        tries = max(int(job.tries), 1)
        backoff = job.backoff if isinstance(job.backoff, list) else [job.backoff]
        if tries > 1:  # complétée avec la dernière valeur, comme Laravel
            backoff = backoff or [0]
            backoff = (list(backoff) + [backoff[-1]] * tries)[: tries - 1]
        return {
            "queue": job.queue_name,  # None : file de la connexion
            "tries": tries,
            "backoff": [int(b) for b in backoff],
            "timeout": int(job.timeout),
            "delay": job.delay_seconds,
        }

    def connection(self, name: str) -> _Connection:
        self._connection_config(name)
        return _Connection(self, name)

    def push(self, job: Job):
        return self._push(None, job)

    def push_sync(self, job: Job) -> None:
        SyncDriver(self._app).push(job, self._options(job))

    def _push(self, name: str | None, job: Job):
        if not isinstance(job, Job):
            raise TypeError(f"dispatch attend un Job, pas {job!r}.")
        options = self._options(job)
        if self._faking:
            _, connection = self._connection_config(name)
            serialize(job)  # une erreur de sérialisation doit se voir aussi sous fake
            queue = options["queue"] or connection.get("queue") or "default"
            self._recorded.append((job, queue))
            return None
        return self._driver(name).push(job, options)


class QueueFake:
    """Assertions sur les jobs poussés depuis `Queue.fake()`."""

    def __init__(self, manager: QueueManager, recorded: list):
        self._manager = manager
        self._recorded = recorded

    def restore(self) -> None:
        """Rend au gestionnaire son fonctionnement normal ; les enregistrements restent lisibles."""
        if self._manager._recorded is self._recorded:  # pas remplacé par un fake() plus récent
            self._manager._faking = False

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.restore()

    def pushed(self, job_class: type) -> list:
        return [job for job, _ in self._recorded if isinstance(job, job_class)]

    def _matching(self, job_class: type, callback) -> list:
        jobs = self.pushed(job_class)
        return jobs if callback is None else [j for j in jobs if callback(j)]

    def assert_pushed(self, job_class: type, callback=None) -> None:
        if not self._matching(job_class, callback):
            detail = " correspondant au callback" if callback else ""
            raise AssertionError(
                f"Job {job_class.__name__}{detail} poussé 0 fois, attendu au moins 1."
            )

    def assert_pushed_times(self, job_class: type, times: int) -> None:
        count = len(self.pushed(job_class))
        if count != times:
            raise AssertionError(f"Job {job_class.__name__} poussé {count} fois, attendu {times}.")

    def assert_not_pushed(self, job_class: type, callback=None) -> None:
        count = len(self._matching(job_class, callback))
        if count:
            raise AssertionError(
                f"Job {job_class.__name__} poussé {count} fois, attendu aucun envoi."
            )

    def assert_nothing_pushed(self) -> None:
        counts = Counter(type(job).__name__ for job, _ in self._recorded)
        if counts:
            pushed = ", ".join(f"{name} poussé {n} fois" for name, n in counts.items())
            raise AssertionError(f"Aucun job attendu, mais : {pushed}.")

    def assert_pushed_on(self, queue: str, job_class: type) -> None:
        queues = [q for job, q in self._recorded if isinstance(job, job_class)]
        if queue not in queues:
            seen = ", ".join(sorted(set(queues))) or "aucune"
            raise AssertionError(
                f"Job {job_class.__name__} non poussé sur la file {queue!r} (files : {seen})."
            )
