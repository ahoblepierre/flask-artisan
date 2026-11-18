import pytest

from flask_artisan import Application, Repository, app, base_path, config


def test_helpers_without_app_raise():
    for helper in (app, config, base_path):
        with pytest.raises(RuntimeError, match="Aucune application"):
            helper()


def test_app_helper(make_project):
    application = Application(make_project())
    assert app() is application
    assert app("config") is application.make("config")


def test_config_helper(make_project):
    Application(make_project())
    assert config("app.name") == "Blog"
    assert config("app.nope", "d") == "d"
    assert isinstance(config(), Repository)


def test_base_path_helper(make_project):
    base = make_project()
    Application(base)
    assert base_path("x") == base / "x"
