import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from .models import CPost


def test_get_put_and_default(store):
    assert store.get("k", "d") == "d"
    assert store.put("k", {"a": [1]}) is True
    assert store.get("k") == {"a": [1]}


def test_callable_default(store):
    assert store.get("k", lambda: 5) == 5


def test_ttl_seconds_and_timedelta_expire(store, clock):
    store.put("a", 1, 10)
    store.put("b", 1, timedelta(seconds=10))
    clock.advance(9)
    assert store.has("a") and store.has("b")
    clock.advance(2)
    assert store.missing("a") and store.missing("b")


def test_ttl_rounded_up(store, clock):
    store.put("k", 1, 0.2)
    clock.advance(0.1)
    assert store.get("k") == 1


def test_non_positive_ttl_and_none_delete(store):
    store.put("k", 1)
    store.put("k", 2, 0)
    assert store.missing("k")
    store.put("k", 1)
    store.put("k", None)
    assert store.missing("k")
    store.put("k", 1)
    store.forever("k", None)
    assert store.missing("k")


def test_forever(store, clock):
    store.forever("k", "v")
    clock.advance(10**6)
    assert store.get("k") == "v"


def test_add(store, clock):
    assert store.add("k", 1, 10) is True
    assert store.add("k", 2, 10) is False
    assert store.get("k") == 1
    clock.advance(11)
    assert store.add("k", 3) is True
    assert store.get("k") == 3
    store.put("n", None)
    assert store.add("n", 4) is True


def test_remember_computes_once_and_skips_none(store):
    calls = []

    def compute():
        calls.append(1)
        return 42

    assert store.remember("k", 60, compute) == 42
    assert store.remember("k", 60, compute) == 42
    assert len(calls) == 1
    nothing = []
    store.remember("n", 60, lambda: nothing.append(1))
    store.remember("n", 60, lambda: nothing.append(1))
    assert len(nothing) == 2 and store.missing("n")


def test_remember_callback_error_stores_nothing(store):
    def boom():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.remember("k", 60, boom)
    assert store.missing("k")


def test_remember_forever(store, clock):
    assert store.remember_forever("k", lambda: "v") == "v"
    clock.advance(10**6)
    assert store.get("k") == "v"


def test_has_missing_pull_forget(store):
    store.put("k", "v")
    assert store.has("k") and not store.missing("k")
    assert store.pull("k") == "v"
    assert store.missing("k")
    assert store.pull("k", "d") == "d"
    store.put("k", "v")
    assert store.forget("k") is True
    assert store.forget("k") is False


def test_increment_decrement(store):
    assert store.increment("c") == 1
    assert store.increment("c", 5) == 6
    assert store.decrement("c") == 5
    assert store.decrement("d", 2) == -2
    assert store.get("c") == 5


def test_increment_keeps_ttl(store, clock):
    store.put("c", 1, 10)
    assert store.increment("c") == 2
    clock.advance(11)
    assert store.missing("c")


def test_increment_non_integer(store):
    store.put("c", "x")
    with pytest.raises(ValueError):
        store.increment("c")


def test_flush(store):
    store.put("a", 1)
    store.put("b", 2)
    store.flush()
    assert store.missing("a") and store.missing("b")


def test_rich_values(store):
    when = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
    store.put("k", {"when": when, "price": Decimal("9.90")})
    assert store.get("k") == {"when": when, "price": Decimal("9.90")}


def test_unsupported_value_names_key(store):
    with pytest.raises(TypeError, match="weird"):
        store.put("weird", object())


@pytest.mark.parametrize("key", ["", 1, None])
def test_invalid_key(store, key):
    with pytest.raises((TypeError, ValueError)):
        store.put(key, 1)


def test_model_reloaded(store, cache_app):
    post = CPost.create(title="old")
    store.put("post", post)
    CPost.find(post.id).update(title="new")
    cache_app.make("db").session.expire_all()
    assert store.get("post").title == "new"


def test_deleted_model_counts_as_missing(store, cache_app, caplog):
    post = CPost.create(title="a")
    store.put("post", post)
    post.delete()
    with caplog.at_level(logging.WARNING):
        assert store.get("post", "d") == "d"
    assert "post" in caplog.text
    assert store.missing("post")
    store.put("post2", CPost.create(title="b"))
    CPost.query().where("title", "b").first().delete()
    assert store.remember("post2", 60, lambda: "recomputed") == "recomputed"


def test_bad_decimal_counts_as_missing(store):
    k = store.prefix + "k"
    store._put(k, '{"__decimal__": "abc"}', None)
    assert store.get("k", "d") == "d"


@pytest.mark.parametrize("ttl", [float("inf"), float("nan")])
def test_non_finite_ttl_rejected(store, ttl):
    with pytest.raises(TypeError):
        store.put("k", 1, ttl)


def test_prune_keeps_live_entries(store, clock):
    store.put("short", 1, 10)
    store.put("long", 2, 100)
    store.forever("always", 3)
    clock.advance(11)
    store.prune()
    assert store.missing("short")
    assert store.get("long") == 2 and store.get("always") == 3


def test_prune_returns_an_int(store):
    assert store.prune() == 0
