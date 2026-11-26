import time

import pytest

STORES = ["array", "file", "redis"]


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(time, "time", lambda: clock.now)
    return clock


@pytest.fixture
def cache_app(db_app):
    app = db_app()
    from . import models  # noqa: F401 — table CPost

    app.make("db").create_all()
    with app.app_context():
        yield app


def configure(app, tmp_path, default="array"):
    app.make("config").set(
        "cache",
        {
            "default": default,
            "stores": {
                "array": {"driver": "array"},
                "file": {"driver": "file", "path": str(tmp_path / "cache")},
                "redis": {"driver": "redis", "url": "redis://test"},
            },
            "prefix": "app_cache:",
        },
    )


@pytest.fixture(params=STORES)
def store(request, cache_app, tmp_path):
    configure(cache_app, tmp_path, default=request.param)
    if request.param == "redis":
        request.getfixturevalue("fake_redis")
    return cache_app.make("cache").store()


@pytest.fixture
def fake_redis(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr("flask_artisan.cache._redis", lambda url: client)
    return client
