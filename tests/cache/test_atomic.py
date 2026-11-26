import multiprocessing
import threading

from flask_artisan.cache import FileStore

from .conftest import configure


def test_delete_if_matches_only_same_text(store):
    k = store._key("x")
    store._put(k, '"a"', None)
    assert store._delete_if(k, '"b"') is False
    assert store.get("x") == "a"
    assert store._delete_if(k, '"a"') is True
    assert store.get("x") is None
    assert store._delete_if(k, '"a"') is False


def _bump(directory, n):
    s = FileStore("p:", directory)
    for _ in range(n):
        s.increment("hits")


def test_file_increment_is_exact_across_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_bump, args=(tmp_path / "c", 100)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    assert FileStore("p:", tmp_path / "c").get("hits") == 400


def test_file_add_creates_directory_and_flush_keeps_lock_file(tmp_path):
    s = FileStore("p:", tmp_path / "missing")
    assert s.add("k", 1) is True
    s.flush()
    assert (tmp_path / "missing" / ".lock").exists()
    assert s.get("k") is None


def test_array_add_wins_once_across_threads(cache_app, tmp_path):
    configure(cache_app, tmp_path, default="array")
    s = cache_app.make("cache").store()
    barrier, wins = threading.Barrier(8), []

    def race():
        barrier.wait()
        wins.append(s.add("once", 1))

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1
