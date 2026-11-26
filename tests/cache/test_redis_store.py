import sys

import pytest

from flask_artisan.cache import RedisStore

from .conftest import configure


@pytest.fixture
def fake(fake_redis):
    return fake_redis


@pytest.fixture
def redis_store(fake):
    return RedisStore("app_cache:", fake)


def test_keys_are_prefixed(redis_store, fake):
    redis_store.put("a", 1)
    assert fake.exists("app_cache:a")


def test_flush_only_touches_prefix(redis_store, fake):
    fake.set("rq:queue:x", "1")
    fake.set("other", "1")
    redis_store.put("a", 1)
    redis_store.flush()
    assert fake.exists("rq:queue:x") and fake.exists("other")
    assert not fake.exists("app_cache:a")


def test_flush_with_glob_chars_in_prefix(fake):
    store = RedisStore("a*b[1]:", fake)
    fake.set("a_b1:x", "1")
    fake.set("axb1:y", "1")
    store.put("k", 1)
    store.flush()
    assert fake.exists("a_b1:x") and fake.exists("axb1:y")
    assert not fake.exists("a*b[1]:k")


def test_add_is_native(redis_store, fake):
    assert redis_store.add("k", 1, 10) is True
    assert 0 < fake.pttl("app_cache:k") <= 10_000


def test_increment_native_keeps_ttl(redis_store, fake):
    redis_store.put("c", 1, 10)
    assert redis_store.increment("c", 2) == 3
    assert fake.get("app_cache:c") == b"3"
    assert fake.pttl("app_cache:c") > 0


def test_missing_redis_message(cache_app, tmp_path, monkeypatch):
    from flask_artisan import cache

    cache._redis.cache_clear()
    configure(cache_app, tmp_path, default="redis")
    monkeypatch.setitem(sys.modules, "redis", None)
    with pytest.raises(RuntimeError, match=r"flask-artisan\[redis\]"):
        cache_app.make("cache").store().get("k")


def test_decode_responses_client():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    store = RedisStore("p:", client)
    store.put("k", {"a": 1})
    assert store.get("k") == {"a": 1}
    assert store.pull("k") == {"a": 1}


def test_default_redis_url_from_env(make_project, monkeypatch):
    from flask_artisan import cache
    from flask_artisan.application import Application

    seen = []
    monkeypatch.setattr(cache, "_redis", lambda url: seen.append(url) or object())
    monkeypatch.setenv("REDIS_URL", "redis://elsewhere:6380/2")
    app = Application(make_project())
    with app.app_context():
        app.make("cache").store("redis")
    assert seen == ["redis://elsewhere:6380/2"]
