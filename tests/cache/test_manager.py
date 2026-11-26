import pytest

from flask_artisan import Cache
from flask_artisan.application import Application
from flask_artisan.cache import ArrayStore, CacheManager

from .conftest import configure


def test_registered(cache_app):
    assert cache_app.make("cache") is cache_app.make(CacheManager)


def test_facade_uses_default_store(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    Cache.put("k", "v")
    assert Cache.get("k") == "v"
    assert Cache.store("array").get("k") == "v"
    assert isinstance(Cache.store(), ArrayStore)


def test_store_by_name_and_unknown(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    with pytest.raises(ValueError, match="nope"):
        Cache.store("nope")
    cache_app.make("config").set("cache.stores.x", {"driver": "carrier"})
    with pytest.raises(ValueError, match="carrier"):
        Cache.store("x")


def test_array_store_kept(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    Cache.store("array").put("k", 1)
    assert Cache.store("array").get("k") == 1


@pytest.mark.xfail(strict=True, reason="pilote file : Task 2")
def test_defaults_without_config(make_project):
    from flask_artisan.cache import FileStore

    base = make_project()
    app = Application(base)
    with app.app_context():
        store = Cache.store()
        assert isinstance(store, FileStore)
        assert store.directory == base / "storage" / "cache"
        assert store.prefix == "blog_cache:"
