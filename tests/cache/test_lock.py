import time

import pytest

from flask_artisan.cache import LockTimeoutError

from .conftest import configure


def test_get_acquires_once(store):
    assert store.lock("job").get() is True
    assert store.lock("job").get() is False


def test_lock_expires(store, clock):
    assert store.lock("job", 10).get() is True
    clock.advance(11)
    assert store.lock("job", 10).get() is True


def test_release_only_by_owner(store, clock):
    first = store.lock("job", 10)
    first.get()
    clock.advance(11)
    second = store.lock("job", 10)
    assert second.get() is True
    assert first.release() is False
    assert store.lock("job").get() is False  # celui du second tient toujours
    assert second.release() is True
    assert store.lock("job").get() is True


def test_force_release_and_restore_lock(store):
    lock = store.lock("job")
    lock.get()
    assert store.restore_lock("job", "autre").release() is False
    assert store.restore_lock("job", lock.owner).release() is True
    store.lock("job").get()
    store.lock("job").force_release()
    assert store.lock("job").get() is True


def test_get_with_callback_releases_even_on_error(store):
    def boom():
        raise RuntimeError

    assert store.lock("job").get(lambda: 42) == 42
    with pytest.raises(RuntimeError):
        store.lock("job").get(boom)
    assert store.lock("job").get() is True
    assert store.lock("job").get(lambda: 1) is False


def test_block_waits_then_succeeds(store, clock, monkeypatch):
    monkeypatch.setattr(time, "sleep", clock.advance)
    store.lock("job", 1).get()
    assert store.lock("job", 5).block(3) is True


def test_block_with_callback_releases(store, clock, monkeypatch):
    monkeypatch.setattr(time, "sleep", clock.advance)
    assert store.lock("job", 5).block(3, lambda: "fait") == "fait"
    assert store.lock("job").get() is True


def test_block_times_out(store, clock, monkeypatch):
    monkeypatch.setattr(time, "sleep", clock.advance)
    store.lock("job").get()
    with pytest.raises(LockTimeoutError):
        store.lock("job").block(1)


def test_context_manager(store):
    with store.lock("job", 10):
        assert store.lock("job").get() is False
        with pytest.raises(LockTimeoutError), store.lock("job"):
            pass
    assert store.lock("job").get() is True


def test_lock_name_must_be_a_string(store):
    with pytest.raises(TypeError):
        store.lock(3)


def test_lock_from_another_store_instance(cache_app, tmp_path):
    configure(cache_app, tmp_path, default="file")
    lock = cache_app.make("cache").store().lock("job")
    lock.get()
    other = cache_app.make("cache").store()  # nouvelle instance, même dossier
    assert other.lock("job").get() is False
    assert other.restore_lock("job", lock.owner).release() is True


def test_facade(cache_app, tmp_path):
    from flask_artisan import Cache

    configure(cache_app, tmp_path)
    assert Cache.lock("job").get() is True
    assert Cache.lock("job").get() is False


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"name": ""}, ValueError),
        ({"name": "job", "seconds": -1}, ValueError),
        ({"name": "job", "owner": ""}, ValueError),
        ({"name": "job", "owner": 123}, TypeError),
    ],
)
def test_lock_arguments_are_checked(store, kwargs, error):
    with pytest.raises(error):
        store.lock(**kwargs)
