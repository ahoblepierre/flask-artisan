import pytest

from flask_artisan import Queue, dispatch
from flask_artisan.queue import QueueFake, QueueManager

from .jobs import Boom, Ping, Record, Unserializable


class LoudPing(Ping):
    pass


@pytest.fixture(autouse=True)
def clear_record():
    Record.clear()


def test_records_without_running(queue_app):
    with Queue.fake() as fake:
        assert Ping.dispatch("a") is None
    assert isinstance(fake, QueueFake)
    assert Record == []
    fake.assert_pushed(Ping)
    assert [j.word for j in fake.pushed(Ping)] == ["a"]


def test_callback_and_failure_message(queue_app):
    with Queue.fake() as fake:
        Ping.dispatch("a")
    fake.assert_pushed(Ping, lambda job: job.word == "a")
    with pytest.raises(AssertionError, match="Ping"):
        fake.assert_pushed(Ping, lambda job: job.word == "z")
    with pytest.raises(AssertionError, match="Boom poussé 0 fois"):
        fake.assert_pushed(Boom)


def test_times_not_pushed_nothing_pushed(queue_app):
    with Queue.fake() as fake:
        fake.assert_nothing_pushed()
        Ping.dispatch("a")
        dispatch(Ping("b"))
    fake.assert_pushed_times(Ping, 2)
    with pytest.raises(AssertionError, match="Ping poussé 2 fois, attendu 1"):
        fake.assert_pushed_times(Ping, 1)
    fake.assert_not_pushed(Boom)
    fake.assert_not_pushed(Ping, lambda job: job.word == "z")
    with pytest.raises(AssertionError, match="Ping poussé 2 fois"):
        fake.assert_not_pushed(Ping)
    with pytest.raises(AssertionError, match="Ping poussé 2 fois"):
        fake.assert_nothing_pushed()


def test_assert_pushed_on(queue_app):
    with Queue.fake() as fake:
        dispatch(Ping("a").on_queue("audio"))
    fake.assert_pushed_on("audio", Ping)
    with pytest.raises(AssertionError, match="default"):
        fake.assert_pushed_on("default", Ping)


def test_subclass_counts(queue_app):
    with Queue.fake() as fake:
        LoudPing.dispatch("a")
    fake.assert_pushed(Ping)


def test_unserializable_still_raises(queue_app):
    with Queue.fake() as fake, pytest.raises(TypeError):
        Unserializable.dispatch()
    fake.assert_nothing_pushed()


def test_injected_manager_is_faked(queue_app):
    held = queue_app.make(QueueManager)
    with Queue.fake() as fake:
        held.push(Ping("a"))
    fake.assert_pushed(Ping)
    assert Record == []


def test_dispatch_sync_runs_under_fake(queue_app):
    with Queue.fake() as fake:
        Ping.dispatch_sync("a")
    assert Record == ["a"]
    fake.assert_nothing_pushed()


def test_restore_and_superseded(queue_app):
    old = Queue.fake()
    new = Queue.fake()
    old.restore()
    Ping.dispatch("a")
    assert Record == []
    new.assert_pushed(Ping)
    new.restore()
    Ping.dispatch("b")
    assert Record == ["b"]
