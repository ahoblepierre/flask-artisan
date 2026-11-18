import pytest

from flask_artisan.config import ConfigError, Repository


def test_dot_notation():
    assert Repository({"app": {"db": {"host": "x"}}}).get("app.db.host") == "x"


def test_default():
    repo = Repository({"app": {"name": "Blog"}})
    assert repo.get("app.missing", "d") == "d"
    assert repo.get("app.name.deep", "d") == "d"


def test_set_creates_nested():
    repo = Repository()
    repo.set("a.b.c", 1)
    assert repo.get("a.b.c") == 1


def test_has():
    repo = Repository({"app": {"name": "Blog"}})
    assert repo.has("app.name")
    assert not repo.has("app.nope")


def test_from_directory(tmp_path):
    (tmp_path / "app.py").write_text('config = {"name": "Blog"}\n')
    (tmp_path / "flask.py").write_text('config = {"X": 1}\n')
    (tmp_path / "_private.py").write_text("raise RuntimeError('ne doit pas être chargé')\n")
    assert Repository.from_directory(tmp_path).all() == {"app": {"name": "Blog"}, "flask": {"X": 1}}


def test_missing_config_dict(tmp_path):
    (tmp_path / "app.py").write_text("name = 'Blog'\n")
    with pytest.raises(ConfigError, match="app.py"):
        Repository.from_directory(tmp_path)


def test_syntax_error(tmp_path):
    (tmp_path / "broken.py").write_text("config = {\n")
    with pytest.raises(ConfigError, match="broken.py"):
        Repository.from_directory(tmp_path)


def test_from_missing_directory(tmp_path):
    assert Repository.from_directory(tmp_path / "nope").all() == {}
