"""Le gestionnaire de files (`"queue"`, façade `Queue`) et ses pilotes."""

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
        return self._driver(name).push(job, self._options(job))
