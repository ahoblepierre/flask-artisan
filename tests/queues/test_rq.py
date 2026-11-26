import sys

import pytest

pytest.importorskip("rq")

from rq import Queue
from rq.job import Job as RqJob
from rq.registry import FailedJobRegistry, ScheduledJobRegistry
from rq.serializers import JSONSerializer

from flask_artisan.queue import worker

from .jobs import (
    AddUncommitted,
    Backoff,
    BadFailedOnce,
    Boom,
    CountPodcasts,
    Ping,
    Record,
    Retried,
    Slow,
)


@pytest.fixture(autouse=True)
def clear_record():
    Record.clear()


def fetch(app, job_id):
    return RqJob.fetch(job_id, connection=app.redis, serializer=JSONSerializer)


def failed_registry(app, name="default"):
    return FailedJobRegistry(queue=Queue(name, connection=app.redis, serializer=JSONSerializer))


def test_push_returns_id_and_worker_runs(rq_app):
    job_id = Ping.dispatch("a")
    assert isinstance(job_id, str)
    assert Record == []
    rq_app.work()
    assert Record == ["a"]


def test_payload_is_json_not_pickle(rq_app):
    job_id = Ping.dispatch("a")
    assert fetch(rq_app, job_id).args[0]["class"] == f"{Ping.__module__}.Ping"
    raw = rq_app.redis.hgetall(f"rq:job:{job_id}")
    assert not any(b"\x80\x04" in v or b"\x80\x05" in v for v in raw.values())


def test_queue_selection(rq_app):
    from flask_artisan import dispatch

    dispatch(Ping("a").on_queue("audio"))
    rq_app.work(("default",))
    assert Record == []
    rq_app.work(("audio",))
    assert Record == ["a"]


def test_delay_schedules(rq_app):
    from flask_artisan import dispatch

    job_id = dispatch(Ping("a").delay(60))
    registry = ScheduledJobRegistry(
        queue=Queue("default", connection=rq_app.redis, serializer=JSONSerializer)
    )
    assert job_id in registry.get_job_ids()
    rq_app.work()
    assert Record == []


def test_timeout_passed(rq_app):
    assert fetch(rq_app, Slow.dispatch("a")).timeout == 5


def test_retries_then_failed_once(rq_app):
    job_id = Retried.dispatch()
    for _ in range(5):
        rq_app.work()
    assert Record.count("try") == 3
    assert Record.count(("failed", "boom")) == 1
    assert job_id in failed_registry(rq_app).get_job_ids()
    assert "boom" in fetch(rq_app, job_id).latest_result().exc_string


def test_single_try_calls_failed(rq_app):
    Boom.dispatch()
    rq_app.work()
    assert Record == ["try", ("failed", "boom")]


def test_backoff_padded_with_last_value(rq_app):
    assert fetch(rq_app, Backoff.dispatch()).retry_intervals == [5, 30, 30]


def test_failed_error_does_not_replace_job_error(rq_app):
    job_id = BadFailedOnce.dispatch()
    rq_app.work()
    exc = fetch(rq_app, job_id).latest_result().exc_string
    assert "boom" in exc and "failed a cassé" not in exc


def test_session_removed_between_jobs(rq_app):
    AddUncommitted.dispatch()
    CountPodcasts.dispatch()
    rq_app.work()
    assert Record == [0]


def test_forged_payload_rejected(rq_app):
    queue = Queue("default", connection=rq_app.redis, serializer=JSONSerializer)
    job = queue.enqueue(worker.run, {"class": "os.path", "data": {}})
    rq_app.work()
    assert job.id in failed_registry(rq_app).get_job_ids()
    assert "TypeError" in fetch(rq_app, job.id).latest_result().exc_string


def test_missing_rq_message(queue_app, monkeypatch):
    config = queue_app.make("config")
    config.set("queue.connections.redis", {"driver": "rq", "url": "redis://x"})
    config.set("queue.default", "redis")
    monkeypatch.setitem(sys.modules, "rq", None)
    with pytest.raises(RuntimeError, match=r"flask-artisan\[rq\]"):
        Ping.dispatch("a")


def test_connect_reuses_client():
    pytest.importorskip("redis")
    assert worker.connect("redis://127.0.0.1:6399/0") is worker.connect("redis://127.0.0.1:6399/0")
