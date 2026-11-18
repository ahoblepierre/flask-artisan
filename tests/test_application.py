import pytest
from flask import Flask

from flask_artisan import Application, Container, Repository, ServiceProvider, config

calls: list[str] = []


class ProviderA(ServiceProvider):
    def register(self):
        calls.append("register:A")

    def boot(self):
        calls.append("boot:A")


class ProviderB(ServiceProvider):
    def register(self):
        calls.append("register:B")

    def boot(self):
        calls.append("boot:B")


@pytest.fixture(autouse=True)
def clear_calls():
    calls.clear()


PROVIDERS = "from test_application import ProviderA, ProviderB"


def test_is_a_flask_app(make_project):
    app = Application(make_project())
    assert isinstance(app, Flask)
    assert app.test_client().get("/nope").status_code == 404


def test_no_flask_attribute_shadowed():
    assert {n for n in dir(Container) if not n.startswith("__")} & set(dir(Flask)) == set()


def test_bridge(make_project):
    base = make_project()
    (base / "config" / "flask.py").write_text('config = {"SQLALCHEMY_DATABASE_URI": "sqlite://"}\n')
    app = Application(base)
    assert app.config["SECRET_KEY"] == "test-key"
    assert app.config["DEBUG"] is False
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"


def test_env_file_loaded(make_project, monkeypatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    Application(make_project(env_file="APP_NAME=FromEnv\n", name='env("APP_NAME")'))
    monkeypatch.delenv("APP_NAME", raising=False)
    assert config("app.name") == "FromEnv"


def test_without_env_file(make_project):
    base = make_project()
    assert not (base / ".env").exists()
    assert Application(base).config["SECRET_KEY"] == "test-key"


def test_missing_key_raises(make_project):
    with pytest.raises(RuntimeError, match="APP_KEY"):
        Application(make_project(key="''"))


def test_container_keys(make_project):
    app = Application(make_project())
    assert app.make("app") is app
    assert app.make(Application) is app
    assert app.make(Repository) is app.make("config")


def test_register_then_boot_order(make_project):
    Application(make_project(extra=PROVIDERS, providers="[ProviderA, ProviderB]"))
    assert calls == ["register:A", "register:B", "boot:A", "boot:B"]


def test_register_after_boot_boots_immediately(make_project):
    app = Application(make_project())
    app.register(ProviderA)
    assert calls == ["register:A", "boot:A"]


def test_duplicate_provider_registered_once(make_project):
    app = Application(make_project(extra=PROVIDERS, providers="[ProviderA, ProviderA]"))
    app.register(ProviderA)
    assert calls == ["register:A", "boot:A"]


def test_paths(make_project):
    base = make_project()
    app = Application(base)
    assert app.base_path("x") == base / "x"
    assert app.config_path() == base / "config"
    assert app.app_path() == base / "app"


def test_environment(make_project):
    assert Application(make_project()).environment() == "testing"


def test_instance_path_inside_project(make_project):
    base = make_project()
    assert Application(base).instance_path == str(base / "instance")


def test_application_does_not_override_flask():
    own = {n for n in vars(Application) if not n.startswith("__")}
    assert own & set(dir(Flask)) == set()


@pytest.mark.parametrize("raw", ["'0'", "'false'", "'no'", "''"])
def test_debug_falsy_strings(make_project, raw):
    assert Application(make_project(debug=raw)).config["DEBUG"] is False


def test_get_instance_prefers_current_app(make_project, tmp_path):
    import shutil

    base = make_project()
    a = Application(base)
    b = Application(shutil.copytree(base, tmp_path / "other"))
    with a.app_context():
        assert Application.get_instance() is a
    assert Application.get_instance() is b


def test_app_built_inside_other_app_context_boots_against_itself(make_project, tmp_path):
    import shutil

    from test_route_provider import ping

    from flask_artisan import Route

    base = make_project()
    a = Application(base)
    other = shutil.copytree(base, tmp_path / "other")
    (other / "config" / "app.py").write_text(
        (other / "config" / "app.py").read_text().replace("'Blog'", "'B'")
    )
    seen = []

    class P(ServiceProvider):
        def boot(self):
            seen.append(config("app.name"))
            Route.get("/b", ping)

    with a.app_context():
        b = Application(other)
        b.register(P)
    assert seen == ["B"]
    assert b.test_client().get("/b").status_code == 200
