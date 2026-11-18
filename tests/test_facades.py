import pytest

from flask_artisan import App, Application, Config, Facade


class Greeter:
    def __init__(self, word: str = "hi"):
        self.word = word

    def hi(self):
        return self.word


class G(Facade):
    accessor = Greeter


def test_config_facade(make_project):
    Application(make_project())
    assert Config.get("app.name") == "Blog"


def test_app_facade(make_project):
    Application(make_project())
    assert App.environment() == "testing"


def test_custom_facade(make_project):
    Application(make_project()).singleton(Greeter)
    assert G.hi() == "hi"


def test_follows_latest_application(tmp_path, make_project):
    Application(make_project())
    second = tmp_path / "second"
    (second / "config").mkdir(parents=True)
    (second / "config" / "app.py").write_text('config = {"name": "Second", "key": "k"}\n')
    Application(second)
    assert Config.get("app.name") == "Second"


def test_no_cache_after_rebind(make_project):
    app = Application(make_project())
    app.singleton(Greeter)
    assert G.hi() == "hi"
    app.instance(Greeter, Greeter("autre"))
    assert G.hi() == "autre"


def test_without_app_raises():
    with pytest.raises(RuntimeError, match="Aucune application"):
        Config.get("app.name")


def test_facade_without_accessor_raises_attribute_error(make_project):
    Application(make_project())

    class Broken(Facade):
        pass

    with pytest.raises(AttributeError, match="accessor"):
        Broken.anything  # noqa: B018
