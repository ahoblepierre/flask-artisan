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
