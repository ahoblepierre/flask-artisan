import pytest


@pytest.fixture
def queue_app(db_app):
    app = db_app()
    from . import models  # noqa: F401 — table QPodcast dans Model.metadata

    app.make("db").create_all()
    with app.app_context():
        yield app


@pytest.fixture
def rq_app(queue_app, monkeypatch):
    """Pilote rq sur un faux Redis partagé ; `rq_app.work()` vide les files en mode burst."""
    fakeredis = pytest.importorskip("fakeredis")
    from rq import SimpleWorker
    from rq.serializers import JSONSerializer

    server = fakeredis.FakeServer()
    redis = fakeredis.FakeRedis(server=server)
    monkeypatch.setattr("flask_artisan.queue.worker.connect", lambda url: redis)
    config = queue_app.make("config")
    config.set("queue.default", "redis")
    config.set(
        "queue.connections",
        {
            "sync": {"driver": "sync"},
            "redis": {"driver": "rq", "url": "redis://test", "queue": "default"},
        },
    )

    def work(queues=("default",)):
        from rq import Queue

        qs = [Queue(q, connection=redis, serializer=JSONSerializer) for q in queues]
        SimpleWorker(qs, connection=redis, serializer=JSONSerializer).work(burst=True)

    queue_app.redis = redis
    queue_app.work = work
    return queue_app
