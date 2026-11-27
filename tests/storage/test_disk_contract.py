import io
import re

import pytest
from werkzeug.datastructures import FileStorage


def upload(name, data=b"x"):
    return FileStorage(stream=io.BytesIO(data), filename=name)


def test_put_get(disk):
    assert disk.put("a/b.txt", "hé") == "a/b.txt"
    assert disk.get("a/b.txt") == "hé".encode()
    disk.put("c.bin", io.BytesIO(b"x"))
    assert disk.get("c.bin") == b"x"


def test_exists_missing_delete(disk):
    disk.put("a.txt", "1")
    assert disk.exists("a.txt") and not disk.missing("a.txt")
    assert disk.delete("a.txt", "absent.txt") is False
    disk.put("a.txt", "1")
    assert disk.delete("a.txt") is True
    assert disk.missing("a.txt")


def test_get_missing_raises(disk):
    with pytest.raises(FileNotFoundError):
        disk.get("absent.txt")


def test_size_and_files(disk):
    disk.put("a/2.txt", "22")
    disk.put("a/1.txt", "1")
    disk.put("a/sub/x.txt", "x")
    disk.put("root.txt", "r")
    assert disk.size("a/2.txt") == 2
    assert disk.files("a") == ["a/1.txt", "a/2.txt"]
    assert disk.files() == ["root.txt"]


def test_url(disk):
    assert disk.url("a b.png").endswith("/a%20b.png")


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/etc/passwd",
        "a\\b",
        "a//b",
        "a\x00",
        "",
        "a/../b",
        "D:evil.txt",
        "a/C:x",
        "CON.txt",
        "a/nul",
        "lpt1",
    ],
)
def test_rejected_paths(disk, path):
    for call in (lambda: disk.put(path, "x"), lambda: disk.get(path), lambda: disk.exists(path)):
        with pytest.raises(ValueError):
            call()
    with pytest.raises(ValueError):
        disk.delete(path)


@pytest.mark.parametrize(
    ("name", "ext"),
    [
        ("../../x.php", ".php"),
        ("évil.PNG", ".png"),
        ("noext", ""),
        ("", ""),
        ("фото.png", ".png"),
        ("a.p/hp", ""),
    ],
)
def test_put_file_names(disk, name, ext):
    path = disk.put_file("up", upload(name))
    assert re.fullmatch(rf"up/[0-9a-f]{{40}}{re.escape(ext)}", path), path
    assert disk.get(path) == b"x"


def test_put_file_as(disk):
    assert disk.put_file_as("up", upload("x.png"), "avatar.png") == "up/avatar.png"
    assert disk.exists("up/avatar.png")
    with pytest.raises(ValueError):
        disk.put_file_as("up", upload("x.png"), "a/b.png")


def test_download(disk, app):
    disk.put("a.txt", "1")
    with app.test_request_context():
        response = disk.download("a.txt", "facture.txt")
        disposition = response.headers["Content-Disposition"]
    assert "attachment" in disposition and "facture.txt" in disposition


def test_assertions(disk):
    disk.put("a.txt", "1")
    disk.assert_exists("a.txt").assert_missing("b.txt")
    with pytest.raises(AssertionError, match="b.txt"):
        disk.assert_exists("b.txt")
    with pytest.raises(AssertionError, match="a.txt"):
        disk.assert_missing("a.txt")


def test_directory_is_not_a_file(disk):
    disk.put("d/x.txt", "1")
    with pytest.raises(FileNotFoundError):
        disk.get("d")
    with pytest.raises(FileNotFoundError):
        disk.size("d")
    assert disk.delete("d") is False
    assert disk.exists("d/x.txt")


def test_files_skips_hidden(disk):
    disk.put("a/.gitignore", "*")
    disk.put("a/x.txt", "1")
    assert disk.files("a") == ["a/x.txt"]
