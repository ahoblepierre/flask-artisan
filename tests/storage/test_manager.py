import pytest

from flask_artisan import Storage


@pytest.fixture
def configured(app, tmp_path):
    config = app.make("config")
    config.set(
        "filesystems",
        {
            "default": "local",
            "disks": {
                "local": {"driver": "local", "root": str(tmp_path / "private")},
                "public": {"driver": "local", "root": str(tmp_path / "public"), "url": "/storage"},
            },
        },
    )
    return app


def test_default_disk_relay(configured, tmp_path):
    Storage.put("a.txt", "1")
    assert (tmp_path / "private" / "a.txt").read_text() == "1"
    assert Storage.disk("public").url("x") == "/storage/x"


def test_unknown_disk(configured):
    with pytest.raises(ValueError, match="nope"):
        Storage.disk("nope")


def test_local_path_only(configured, tmp_path):
    assert Storage.path("a/b.txt") == (tmp_path / "private" / "a" / "b.txt").resolve()


def test_fake_is_isolated(app):
    disk = Storage.fake()
    disk.put("a.txt", "1")
    root = disk.root
    assert not app.base_path("storage").exists()
    Storage.restore()
    assert not root.exists()


def test_fake_twice_starts_empty(app):
    Storage.fake().put("a.txt", "1")
    assert Storage.fake().missing("a.txt")
    Storage.restore()


def test_fake_context_manager(app):
    with Storage.fake("public") as disk:
        disk.put("x.txt", "1")
        assert Storage.disk("public").exists("x.txt")
    assert Storage.disk("public").root == app.base_path("storage/app/public").resolve()


def test_defaults_without_config(app):
    assert Storage.disk("public").url("x") == "/storage/x"
    assert Storage.disk().root == app.base_path("storage/app/private").resolve()
