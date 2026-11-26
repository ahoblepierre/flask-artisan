"""Côté RQ : connexion, files, et la fonction `run` que le worker exécute.

RQ et redis ne sont importés qu'ici, à l'usage : sans l'extra `[rq]`, le reste fonctionne.
"""

from datetime import timedelta

INSTALL = 'Le pilote rq demande RQ : pip install "flask-artisan[rq]".'


def require_rq():
    try:
        import rq
    except ImportError:
        raise RuntimeError(INSTALL) from None
    return rq


def connect(url: str):
    """Connexion Redis (point de remplacement des tests)."""
    require_rq()
    from redis import Redis

    return Redis.from_url(url)


def rq_queue(connection: dict, name: str):
    """File RQ avec le sérialiseur JSON : jamais de pickle lu dans Redis."""
    rq = require_rq()
    from rq.serializers import JSONSerializer

    return rq.Queue(name, connection=connect(connection["url"]), serializer=JSONSerializer)


def enqueue(connection: dict, payload: dict, options: dict) -> str:
    rq = require_rq()
    queue = rq_queue(connection, options["queue"] or "default")
    kwargs = {
        "job_timeout": options["timeout"],
        "description": payload["class"],
        "meta": {"tries": options["tries"]},  # pour que queue:retry rende tous les essais
    }
    if options["tries"] > 1:
        backoff = options["backoff"]
        kwargs["retry"] = rq.Retry(
            max=options["tries"] - 1, interval=backoff if any(backoff) else 0
        )
    if options["delay"]:
        job = queue.enqueue_in(timedelta(seconds=options["delay"]), run, payload, **kwargs)
    else:
        job = queue.enqueue(run, payload, **kwargs)
    return job.id


def run(payload: dict) -> None:
    """Exécutée par le worker : reconstruit le job (sous-classe de Job seulement) et l'exécute."""
    from rq import get_current_job

    from flask_artisan.application import Application
    from flask_artisan.queue.jobs import Job, execute
    from flask_artisan.queue.serialization import restore

    app = Application.get_instance()
    current = get_current_job()
    # retries_left : essais restants après celui-ci ; 0 ou None = dernier essai.
    final = current is None or not current.retries_left
    with app.app_context():  # contexte propre au job : sa fin retire la session de base
        job = restore(payload, Job)
        execute(app, job, final=final)
