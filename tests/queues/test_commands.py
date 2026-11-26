import pytest

pytest.importorskip("rq")

from rq import Queue
from rq.registry import FailedJobRegistry
from rq.serializers import JSONSerializer

from .jobs import Boom, Ping, Record


class TwoTries(Boom):
    tries = 2


@pytest.fixture(autouse=True)
def clear_record():
    Record.clear()


def cli(app, *args):
    return app.test_cli_runner().invoke(args=list(args))


def failed_ids(app):
    queue = Queue("default", connection=app.redis, serializer=JSONSerializer)
    return FailedJobRegistry(queue=queue).get_job_ids()


def test_work_burst_runs_jobs(rq_app):
    Ping.dispatch("a")
    result = cli(rq_app, "queue:work", "--burst")
    assert result.exit_code == 0, result.output
    assert Record == ["a"]


def test_failed_lists_job(rq_app):
    job_id = Boom.dispatch()
    rq_app.work()
    result = cli(rq_app, "queue:failed")
    assert result.exit_code == 0, result.output
    for text in (job_id, "Boom", "default", "RuntimeError: boom"):
        assert text in result.output


def test_failed_empty(rq_app):
    assert "Aucun job en échec" in cli(rq_app, "queue:failed").output


def test_retry_restores_all_tries(rq_app):
    job_id = TwoTries.dispatch()
    for _ in range(3):
        rq_app.work()
    assert Record.count("try") == 2
    result = cli(rq_app, "queue:retry", job_id)
    assert result.exit_code == 0, result.output
    assert failed_ids(rq_app) == []
    for _ in range(3):
        rq_app.work()
    assert Record.count("try") == 4
    assert failed_ids(rq_app) == [job_id]


def test_retry_all_forget_flush(rq_app):
    ids = [Boom.dispatch() for _ in range(3)]
    rq_app.work()
    assert sorted(failed_ids(rq_app)) == sorted(ids)
    assert cli(rq_app, "queue:forget", ids[0]).exit_code == 0
    assert sorted(failed_ids(rq_app)) == sorted(ids[1:])
    assert cli(rq_app, "queue:retry", "all").exit_code == 0
    assert failed_ids(rq_app) == []
    rq_app.work()
    assert cli(rq_app, "queue:flush").exit_code == 0
    assert failed_ids(rq_app) == []


def test_unknown_failed_id(rq_app):
    result = cli(rq_app, "queue:forget", "nope")
    assert result.exit_code != 0 and "nope" in result.output


def test_sync_connection_has_no_queue(queue_app):
    for command in ("queue:failed", "queue:flush"):
        result = cli(queue_app, command)
        assert result.exit_code == 0 and "aucune file" in result.output


def test_work_requires_rq_connection(queue_app):
    result = cli(queue_app, "queue:work", "--burst")
    assert result.exit_code != 0 and "sync" in result.output


def test_failed_commands_cover_every_queue(rq_app):
    from .jobs import AudioBoom

    job_id = AudioBoom.dispatch()
    rq_app.work(("audio",))
    assert job_id in cli(rq_app, "queue:failed").output
    assert cli(rq_app, "queue:retry", job_id).exit_code == 0
    rq_app.work(("audio",))
    assert cli(rq_app, "queue:forget", job_id).exit_code == 0
    AudioBoom.dispatch()
    rq_app.work(("audio",))
    assert "1 job(s)" in cli(rq_app, "queue:flush").output
    assert "Aucun job en échec" in cli(rq_app, "queue:failed").output


def test_retry_all_skips_missing_job(rq_app):
    lost, kept = Boom.dispatch(), Boom.dispatch()
    rq_app.work()
    rq_app.redis.delete(f"rq:job:{lost}")
    result = cli(rq_app, "queue:retry", "all")
    assert result.exit_code == 0, result.output
    assert lost in result.output and f"Remis en file : {kept}" in result.output
