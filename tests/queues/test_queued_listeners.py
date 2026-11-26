import pytest

from flask_artisan import Event, Queue
from flask_artisan.queue.jobs import CallQueuedListener

from .jobs import PlainListener, QueuedListener, Record, Shipped
from .models import QPodcast


@pytest.fixture(autouse=True)
def clear_record():
    Record.clear()


def test_should_queue_listener_is_pushed(queue_app):
    Event.listen(Shipped, QueuedListener)
    podcast = QPodcast.create(title="a")
    with Queue.fake() as fake:
        assert Event.dispatch(Shipped(podcast)) == [None]
    assert Record == []
    fake.assert_pushed(CallQueuedListener, lambda job: job.method == "handle")


def test_tuple_listener_queued(queue_app):
    Event.listen(Shipped, (QueuedListener, "on_ship"))
    with Queue.fake() as fake:
        Event.dispatch(Shipped(QPodcast.create(title="a")))
    fake.assert_pushed(CallQueuedListener, lambda job: job.method == "on_ship")


def test_sync_runs_listener_with_restored_event(queue_app):
    Event.listen(Shipped, [QueuedListener, (QueuedListener, "on_ship")])
    Event.dispatch(Shipped(QPodcast.create(title="a"), note="n"))
    assert Record == [("handle", "a", "n"), ("on_ship", "a")]


def test_worker_gets_reloaded_model(rq_app):
    Event.listen(Shipped, QueuedListener)
    podcast = QPodcast.create(title="old")
    Event.dispatch(Shipped(podcast, note="n"))
    podcast.title = "unsaved"  # non enregistré : le worker recharge depuis la base
    rq_app.make("db").remove()  # le worker a sa propre session (autre processus en production)
    rq_app.work(("listeners",))
    assert Record == [("handle", "old", "n")]


def test_listener_settings_copied(queue_app):
    Event.listen(Shipped, QueuedListener)
    with Queue.fake() as fake:
        Event.dispatch(Shipped(QPodcast.create(title="a")))
    fake.assert_pushed_on("listeners", CallQueuedListener)
    assert fake.pushed(CallQueuedListener)[0].tries == 3


def test_plain_listener_unchanged(queue_app):
    Event.listen(Shipped, PlainListener)
    with Queue.fake() as fake:
        Event.dispatch(Shipped(None))
    assert Record == ["plain"]
    fake.assert_nothing_pushed()


def test_forged_listener_rejected(queue_app):
    job = CallQueuedListener.__new__(CallQueuedListener)
    job.listener, job.method = f"{PlainListener.__module__}.PlainListener", "handle"
    job.event_class, job.event_data = f"{Shipped.__module__}.Shipped", {}
    with pytest.raises(TypeError):
        queue_app.call(job.handle)
    job.listener, job.method = f"{QueuedListener.__module__}.QueuedListener", "_secret"
    with pytest.raises(TypeError):
        queue_app.call(job.handle)


def test_forged_stdlib_event_class_rejected(queue_app):
    job = CallQueuedListener.__new__(CallQueuedListener)
    job.listener, job.method = f"{QueuedListener.__module__}.QueuedListener", "handle"
    job.event_class, job.event_data = "subprocess.Popen", {}
    with pytest.raises(TypeError, match="subprocess"):
        queue_app.call(job.handle)
