import pytest

from flask_artisan.application import Application

DEFAULT_APP = {
    "name": "'Blog'",
    "env": "'testing'",
    "debug": "False",
    "key": "'test-key'",
    "providers": "[]",
}


@pytest.fixture
def make_project(tmp_path):
    """Écrit config/app.py (valeurs Python sous forme de source) et un .env optionnel."""

    def _make(env_file: str | None = None, extra: str = "", **overrides) -> "Path":  # noqa: F821
        values = {**DEFAULT_APP, **overrides}
        body = ",\n".join(f"    {k!r}: {v}" for k, v in values.items())
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "app.py").write_text(
            f"from flask_artisan import env\n{extra}\nconfig = {{\n{body},\n}}\n"
        )
        if env_file is not None:
            (tmp_path / ".env").write_text(env_file)
        return tmp_path

    return _make


@pytest.fixture(autouse=True)
def reset_application():
    yield
    Application.set_instance(None)
