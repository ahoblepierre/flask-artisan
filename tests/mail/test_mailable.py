from types import SimpleNamespace

import pytest

from flask_artisan.mail import Attachment, _addresses

from .mailables import Hello


def test_context_is_public_attributes():
    m = Hello("A")
    m._secret = 1
    assert m.context() == {"name": "A"}


def test_attachment_from_path_guesses_name_and_mime(tmp_path):
    p = tmp_path / "facture.pdf"
    p.write_bytes(b"%PDF")
    a = Attachment.from_path(p)
    assert (a.name, a.mime, a.read()) == ("facture.pdf", "application/pdf", b"%PDF")


def test_attachment_from_path_custom_name(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"1")
    assert Attachment.from_path(p, name="r.csv").mime == "text/csv"


def test_attachment_from_data_defaults_to_octet_stream():
    a = Attachment.from_data("é", "blob")
    assert a.mime == "application/octet-stream" and a.read() == "é".encode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a@x.org", [("", "a@x.org")]),
        ("Alice <a@x.org>", [("Alice", "a@x.org")]),
        (("a@x.org", "Alice"), [("Alice", "a@x.org")]),
        (SimpleNamespace(email="a@x.org", name="Alice"), [("Alice", "a@x.org")]),
        (SimpleNamespace(email="a@x.org"), [("", "a@x.org")]),
        (SimpleNamespace(email="a@x.org", name=None), [("", "a@x.org")]),
        (["a@x.org", ("b@x.org", "B")], [("", "a@x.org"), ("B", "b@x.org")]),
    ],
)
def test_addresses_forms(value, expected):
    assert _addresses(value) == expected


def test_addresses_invalid_form():
    with pytest.raises(TypeError, match="42"):
        _addresses(42)


def test_addresses_without_at():
    with pytest.raises(ValueError, match="nobody"):
        _addresses("nobody")


@pytest.mark.parametrize("bad", ["a@x.org\nBcc: z@x.org", ("a@x.org", "A\r\nB")])
def test_addresses_reject_newlines(bad):
    with pytest.raises(ValueError):
        _addresses(bad)
