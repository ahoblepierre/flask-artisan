import logging
from datetime import timedelta

import pytest

from flask_artisan import Queue, dispatch
from flask_artisan.application import Application
from flask_artisan.queue import QueueManager

from .jobs import BadFailed, Boom, Injected, Ping, Record, Service, Unserializable, WithPodcast
from .models import QPodcast


@pytest.fixture(autouse=True)
def clear_record():
    Record.clear()


def test_registered(queue_app):
    assert queue_app.make("queue") is queue_app.make(QueueManager)


def test_dispatch_runs_immediately(queue_app):
    assert Ping.dispatch("a") is None
    assert Record == ["a"]


def test_dispatch_helper_and_facade(queue_app):
    dispatch(Ping("b"))
    Queue.push(Ping("c"))
    assert Record == ["b", "c"]


def test_handle_injected(queue_app):
    queue_app.singleton(Service)
    Injected.dispatch()
    assert Record == [queue_app.make(Service)]


def test_sync_round_trips_models(queue_app):
    podcast = QPodcast.create(title="a")
    WithPodcast.dispatch(podcast)
    [received] = Record
    assert isinstance(received, QPodcast) and received.id == podcast.id


def test_exception_propagates_after_failed(queue_app):
    with pytest.raises(RuntimeError, match="boom"):
        Boom.dispatch()
    assert Record == ["try", ("failed", "boom")]


def test_failed_error_logged_not_masking(queue_app, caplog):
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="boom"):
        BadFailed.dispatch()
    assert "failed a cassé" in caplog.text


def test_unserializable_job_raises_before_running(queue_app):
    with pytest.raises(TypeError, match="handle_"):
        Unserializable.dispatch()
    assert Record == []


def test_options_and_properties():
    job = Ping("a")
    assert (job.queue_name, job.delay_seconds) == ("default", 0)
    assert job.on_queue("x").delay(timedelta(minutes=1)) is job
    assert (job.queue_name, job.delay_seconds) == ("x", 60)
    assert Ping("a").delay(5).delay_seconds == 5


def test_dispatch_sync_ignores_driver(queue_app):
    queue_app.make("config").set("queue.default", "nope")
    Ping.dispatch_sync("a")
    assert Record == ["a"]


def test_unknown_connection(queue_app):
    with pytest.raises(ValueError, match="nope"):
        Queue.connection("nope")
    queue_app.make("config").set("queue.connections.x", {"driver": "carrier-pigeon"})
    with pytest.raises(ValueError, match="carrier-pigeon"):
        Queue.connection("x").push(Ping("a"))


def test_defaults_without_config(make_project):
    app = Application(make_project())
    with app.app_context():
        Ping.dispatch("z")
    assert Record == ["z"]
