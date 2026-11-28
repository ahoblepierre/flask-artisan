import hashlib
import logging
import os

import pytest

from flask_artisan.cache import FileStore


def files(directory):
    """Fichiers du dossier, hors `.lock` (verrou flock du store, permanent)."""
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if p.name != ".lock")


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


def test_expired_read_does_not_delete_fresh_write(tmp_path, monkeypatch):
    import time as time_module

    store = FileStore("p:", tmp_path)
    store.put("k", "old", 10)
    now = time_module.time()
    calls = []

    def clock():
        # Juste après la lecture du fichier expiré, une autre requête écrit une valeur fraîche.
        if not calls:
            calls.append(1)
            monkeypatch.setattr(time_module, "time", lambda: now + 20)
            FileStore("p:", tmp_path).put("k", "fresh")
        return now + 20

    monkeypatch.setattr(time_module, "time", clock)
    # La relecture sous le verrou voit déjà l'écriture fraîche.
    assert store.get("k") == "fresh"
    assert store.get("k") == "fresh"


def test_cache_files_readable_by_group_and_others(tmp_path):
    FileStore("p:", tmp_path).put("k", 1)
    [path] = tmp_path.iterdir()
    assert path.stat().st_mode & 0o777 == 0o644


def test_prune_removes_expired_and_unreadable_files(tmp_path, clock):
    store = FileStore("p:", tmp_path)
    store.put("old", 1, 10)
    store.put("live", 1, 100)
    store.forever("always", 1)
    corrupt = tmp_path / ("0" * 64)
    corrupt.write_text("{pas du json")
    clock.advance(11)
    assert store.prune() == 2
    assert len(files(tmp_path)) == 2
    assert store.get("live") == 1 and store.get("always") == 1


def test_prune_leaves_foreign_files(tmp_path):
    store = FileStore("p:", tmp_path)
    store.put("k", 1)
    for name in (".gitignore", ".tmp-abc"):
        (tmp_path / name).write_text("x")
    (tmp_path / ("a" * 64)).mkdir()
    assert store.prune() == 0
    assert {".gitignore", ".tmp-abc", "a" * 64} <= set(files(tmp_path))


def test_prune_missing_directory(tmp_path):
    store = FileStore("p:", tmp_path / "absent")
    assert store.prune() == 0
    assert not (tmp_path / "absent").exists()


def test_prune_spares_a_file_rewritten_meanwhile(tmp_path, clock):
    store = FileStore("p:", tmp_path)
    store.put("k", "old", 10)
    clock.advance(11)
    real_locked = store._locked

    def rewrite_then_lock():
        store.put("k", "new", 100)  # os.replace entre la lecture et le verrou
        return real_locked()

    store._locked = rewrite_then_lock  # pas monkeypatch.undo() : il annulerait aussi l'horloge
    assert store.prune() == 0
    del store._locked
    assert store.get("k") == "new"


def test_prune_reclaims_throttle_counters(tmp_path, clock):
    # Scénario de l'audit : deux clés par client anonyme, jamais relues.
    store = FileStore("p:", tmp_path)
    for i in range(30):
        store.add(f"throttle:{i}:timer", 1, 60)
        store.add(f"throttle:{i}", 0, 60)
    assert len(files(tmp_path)) == 60
    clock.advance(61)
    assert store.prune() == 60
    assert files(tmp_path) == []
