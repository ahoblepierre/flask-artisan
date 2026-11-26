import hashlib
import logging
import os

import pytest

from flask_artisan.cache import FileStore


def files(directory):
    return sorted(p.name for p in directory.iterdir()) if directory.exists() else []


def test_directory_created_on_first_write(tmp_path):
    store = FileStore("p:", tmp_path / "a" / "b")
    assert not (tmp_path / "a").exists()
    store.put("k", 1)
    assert store.get("k") == 1


def test_one_file_per_key_named_by_hash(tmp_path):
    FileStore("p:", tmp_path).put("secret-key", 1)
    assert files(tmp_path) == [hashlib.sha256(b"p:secret-key").hexdigest()]


def test_corrupt_file_counts_as_missing(tmp_path, caplog):
    store = FileStore("p:", tmp_path)
    store.put("k", 1)
    [name] = files(tmp_path)
    (tmp_path / name).write_text("{")
    with caplog.at_level(logging.WARNING):
        assert store.get("k", "d") == "d"
    assert files(tmp_path) == []
    assert "p:k" in caplog.text


def test_no_temp_file_left_when_write_fails(tmp_path, monkeypatch):
    store = FileStore("p:", tmp_path)

    def broken(*args):
        raise OSError("disque plein")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        store.put("k", 1)
    assert files(tmp_path) == []


def test_expired_file_removed_on_read(tmp_path, clock):
    store = FileStore("p:", tmp_path)
    store.put("k", 1, 10)
    clock.advance(11)
    assert store.get("k") is None
    assert files(tmp_path) == []


def test_flush_only_removes_cache_files(tmp_path):
    store = FileStore("p:", tmp_path)
    store.put("a", 1)
    store.flush()
    assert files(tmp_path) == []
    FileStore("p:", tmp_path / "missing").flush()  # dossier absent : rien à faire


def test_flush_keeps_foreign_files_and_pending_writes(tmp_path):
    store = FileStore("p:", tmp_path)
    store.put("a", 1)
    (tmp_path / ".gitignore").write_text("*\n")
    (tmp_path / "app.log").write_text("log")
    (tmp_path / ".tmp-pending").write_text("en cours")
    store.flush()
    assert files(tmp_path) == [".gitignore", ".tmp-pending", "app.log"]


@pytest.mark.parametrize(
    "content", ['{"expires": "x", "value": "1"}', '{"expires": null, "value": 1}']
)
def test_wrong_types_count_as_missing(tmp_path, content):
    store = FileStore("p:", tmp_path)
    store.put("k", 1)
    [name] = files(tmp_path)
    (tmp_path / name).write_text(content)
    assert store.get("k", "d") == "d"
