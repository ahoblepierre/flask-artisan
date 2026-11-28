from .conftest import configure


def cli(app, *args):
    return app.test_cli_runner().invoke(args=list(args))


def test_clear_default_store(cache_app, tmp_path):
    configure(cache_app, tmp_path, default="file")
    store = cache_app.make("cache").store()
    store.put("k", 1)
    result = cli(cache_app, "cache:clear")
    assert result.exit_code == 0, result.output
    assert "file" in result.output
    assert store.missing("k")


def test_clear_named_store(cache_app, tmp_path):
    configure(cache_app, tmp_path, default="file")
    cache_app.make("cache").store("array").put("k", 1)
    assert cli(cache_app, "cache:clear", "array").exit_code == 0
    assert cache_app.make("cache").store("array").missing("k")


def test_clear_unknown_store(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    result = cli(cache_app, "cache:clear", "nope")
    assert result.exit_code != 0 and "nope" in result.output


def test_clear_reports_store_errors(cache_app, tmp_path, monkeypatch):
    from flask_artisan import cache

    configure(cache_app, tmp_path, default="redis")

    def unavailable(url):
        raise RuntimeError('pip install "flask-artisan[redis]"')

    monkeypatch.setattr(cache, "_redis", unavailable)
    result = cli(cache_app, "cache:clear")
    assert result.exit_code != 0 and "flask-artisan[redis]" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_default_prefix_exported():
    from flask_artisan import cache

    assert "default_prefix" in cache.__all__


def test_prune_default_store(cache_app, tmp_path, clock):
    configure(cache_app, tmp_path, default="file")
    store = cache_app.make("cache").store()
    store.put("old", 1, 10)
    store.put("live", 1, 100)
    clock.advance(11)
    result = cli(cache_app, "cache:prune")
    assert result.exit_code == 0, result.output
    assert "1 entrée(s) expirée(s) supprimée(s) du store file." in result.output
    assert store.get("live") == 1


def test_prune_named_store(cache_app, tmp_path, clock):
    configure(cache_app, tmp_path, default="file")
    cache_app.make("cache").store("array").put("old", 1, 10)
    clock.advance(11)
    result = cli(cache_app, "cache:prune", "array")
    assert result.exit_code == 0, result.output
    assert "du store array." in result.output and "du store file." not in result.output


def test_prune_also_limiter_store(cache_app, tmp_path, clock):
    configure(cache_app, tmp_path, default="array")
    config = cache_app.make("config")
    config.set("cache.limiter", "file")
    cache_app.make("cache").store("file").put("throttle", 1, 10)
    clock.advance(11)
    result = cli(cache_app, "cache:prune")
    assert result.exit_code == 0, result.output
    assert "du store array." in result.output
    assert "1 entrée(s) expirée(s) supprimée(s) du store file." in result.output


def test_prune_limiter_same_as_default_runs_once(cache_app, tmp_path):
    configure(cache_app, tmp_path, default="file")
    cache_app.make("config").set("cache.limiter", "file")
    result = cli(cache_app, "cache:prune")
    assert result.output.count("du store file.") == 1


def test_prune_unknown_store(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    result = cli(cache_app, "cache:prune", "nope")
    assert result.exit_code != 0 and "nope" in result.output


def test_prune_unknown_limiter_store(cache_app, tmp_path):
    configure(cache_app, tmp_path)
    cache_app.make("config").set("cache.limiter", "nope")
    result = cli(cache_app, "cache:prune")
    assert result.exit_code != 0 and "nope" in result.output
