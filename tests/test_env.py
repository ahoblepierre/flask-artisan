import pytest

from flask_artisan.env import env, load_env_file


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("(true)", True),
        ("TRUE", True),
        ("false", False),
        ("(false)", False),
        ("null", None),
        ("(null)", None),
        ("empty", ""),
        ("(empty)", ""),
        ('"hello"', "hello"),
        ("'hello'", "hello"),
        ("plain", "plain"),
    ],
)
def test_env_casts(monkeypatch, raw, expected):
    monkeypatch.setenv("LF_TEST", raw)
    assert env("LF_TEST") == expected


def test_env_default_when_missing(monkeypatch):
    monkeypatch.delenv("LF_TEST", raising=False)
    assert env("LF_TEST", "fallback") == "fallback"


def test_load_env_file_does_not_override(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LF_A=from_file\nLF_B=from_file\n")
    monkeypatch.setenv("LF_A", "from_os")
    monkeypatch.delenv("LF_B", raising=False)
    load_env_file(tmp_path / ".env")
    assert env("LF_A") == "from_os" and env("LF_B") == "from_file"
    monkeypatch.delenv("LF_B")


def test_load_env_file_missing_is_silent(tmp_path):
    load_env_file(tmp_path / ".env")
