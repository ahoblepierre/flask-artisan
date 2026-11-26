"""`flask queue:work` et les commandes des jobs en échec (registre d'échecs de RQ)."""

import click
from flask import current_app
from flask.cli import with_appcontext

connection_option = click.option(
    "--connection",
    "connection_name",
    help="Connexion de config/queue.py (défaut : la connexion par défaut).",
)


def _rq_connection(name: str | None) -> tuple[str, dict] | None:
    """(nom, config) d'une connexion rq ; None pour une connexion sync."""
    name, options = current_app.make("queue")._connection_config(name)
    if options.get("driver") == "sync":
        return None
    if options.get("driver") != "rq":
        raise click.ClickException(f"Pilote de file inconnu : {options.get('driver')!r}.")
    return name, options


def _registry(options: dict):
    from rq.registry import FailedJobRegistry

    from flask_artisan.queue import worker

    return FailedJobRegistry(queue=worker.rq_queue(options, options.get("queue") or "default"))


def _fetch(registry, job_id: str):
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    if job_id not in registry.get_job_ids():
        raise click.ClickException(f"Aucun job en échec avec l'id {job_id!r}.")
    try:
        return Job.fetch(job_id, connection=registry.connection, serializer=registry.serializer)
    except NoSuchJobError:
        raise click.ClickException(f"Job {job_id!r} introuvable dans Redis.") from None


def _no_queue(name: str | None) -> bool:
    if _rq_connection(name) is None:
        click.echo("Connexion sync : aucune file à inspecter.")
        return True
    return False


@click.command("queue:work")
@click.argument("connection_name", required=False)
@click.option("--queue", "queues", help="Files à écouter, séparées par des virgules.")
@click.option("--burst", is_flag=True, help="S'arrête quand les files sont vides.")
@with_appcontext
def queue_work(connection_name, queues, burst):
    """Exécute les jobs en file (worker RQ, dans le processus de l'application)."""
    found = _rq_connection(connection_name)
    if found is None:
        raise click.ClickException(
            "La connexion sync exécute les jobs tout de suite : pas de worker. "
            "Choisissez une connexion rq (QUEUE_CONNECTION=redis)."
        )
    from rq import SimpleWorker
    from rq.serializers import JSONSerializer

    from flask_artisan.queue import worker

    _, options = found
    names = [q.strip() for q in (queues or options.get("queue") or "default").split(",")]
    rq_queues = [worker.rq_queue(options, name) for name in names if name]
    SimpleWorker(rq_queues, connection=rq_queues[0].connection, serializer=JSONSerializer).work(
        burst=burst, with_scheduler=True
    )


@click.command("queue:failed")
@connection_option
@with_appcontext
def queue_failed(connection_name):
    """Liste les jobs en échec."""
    if _no_queue(connection_name):
        return
    registry = _registry(_rq_connection(connection_name)[1])
    ids = registry.get_job_ids()
    if not ids:
        click.echo("Aucun job en échec.")
        return
    for job_id in ids:
        job = _fetch(registry, job_id)
        cls = (job.args[0].get("class", "?") if job.args else "?").rsplit(".", 1)[-1]
        result = job.latest_result()
        error = (result.exc_string or "").strip().splitlines()[-1:] if result else []
        when = job.ended_at.strftime("%Y-%m-%d %H:%M:%S") if job.ended_at else "-"
        click.echo(f"{job_id}  {cls}  {job.origin}  {when}  {' '.join(error)}")


@click.command("queue:retry")
@click.argument("ids", nargs=-1, required=True)
@connection_option
@with_appcontext
def queue_retry(ids, connection_name):
    """Remet en file des jobs en échec (ou `all`), avec tous leurs essais."""
    if _no_queue(connection_name):
        return
    registry = _registry(_rq_connection(connection_name)[1])
    targets = registry.get_job_ids() if list(ids) == ["all"] else ids
    for job_id in targets:
        job = _fetch(registry, job_id)
        tries = job.meta.get("tries", 1)
        job.retries_left = tries - 1 if tries > 1 else None  # tous les essais, comme Laravel
        job.save()
        registry.requeue(job)
        click.echo(f"Remis en file : {job_id}")


@click.command("queue:forget")
@click.argument("job_id")
@connection_option
@with_appcontext
def queue_forget(job_id, connection_name):
    """Supprime un job en échec."""
    if _no_queue(connection_name):
        return
    registry = _registry(_rq_connection(connection_name)[1])
    registry.remove(_fetch(registry, job_id), delete_job=True)
    click.echo(f"Supprimé : {job_id}")


@click.command("queue:flush")
@connection_option
@with_appcontext
def queue_flush(connection_name):
    """Supprime tous les jobs en échec."""
    if _no_queue(connection_name):
        return
    registry = _registry(_rq_connection(connection_name)[1])
    ids = registry.get_job_ids()
    for job_id in ids:
        registry.remove(job_id, delete_job=True)
    click.echo(f"{len(ids)} job(s) en échec supprimé(s).")


COMMANDS = [queue_work, queue_failed, queue_retry, queue_forget, queue_flush]
