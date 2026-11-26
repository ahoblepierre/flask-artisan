import logging
import smtplib

import pytest

from flask_artisan import Mail

from .mailables import Hello


class FakeSMTP:
    calls: list = []
    fail = False

    def __init__(self, host, port, timeout=None):
        self.calls.append(("connect", type(self).__name__, host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.calls.append(("quit",))

    def starttls(self):
        self.calls.append(("starttls",))

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message, to_addrs=None):
        if self.fail:
            raise smtplib.SMTPRecipientsRefused({"a@x.org": (550, b"no")})
        self.calls.append(("send", message["Subject"], to_addrs))


class FakeSSL(FakeSMTP):
    pass


@pytest.fixture
def smtp(mail_app, monkeypatch):
    FakeSMTP.calls = []
    FakeSMTP.fail = False
    monkeypatch.setattr("flask_artisan.mail.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("flask_artisan.mail.smtplib.SMTP_SSL", FakeSSL)

    def use(**options):
        config = mail_app.make("config")
        config.set("mail.default", "smtp")
        config.set("mail.mailers.smtp", {"transport": "smtp", **options})

    return use


def test_smtp_starttls_and_login(smtp):
    smtp(host="h", port="587", username="u", password="p", encryption="tls")
    Mail.to("a@x.org").bcc("b@x.org").send(Hello("A"))
    assert FakeSMTP.calls == [
        ("connect", "FakeSMTP", "h", 587, 10),
        ("starttls",),
        ("login", "u", "p"),
        ("send", "Hi", ["a@x.org", "b@x.org"]),
        ("quit",),
    ]


def test_smtp_ssl(smtp):
    smtp(host="h", port=465, encryption="ssl", timeout=3)
    Mail.to("a@x.org").send(Hello("A"))
    assert FakeSMTP.calls[0] == ("connect", "FakeSSL", "h", 465, 3)
    assert ("starttls",) not in FakeSMTP.calls


@pytest.mark.parametrize("encryption", [None, ""])
def test_smtp_plain_without_login(smtp, encryption):
    smtp(host="h", port=2525, username="", encryption=encryption)
    Mail.to("a@x.org").send(Hello("A"))
    assert [c[0] for c in FakeSMTP.calls] == ["connect", "send", "quit"]


def test_smtp_unknown_encryption(smtp):
    smtp(host="h", port=25, encryption="starttls")
    with pytest.raises(ValueError, match="starttls"):
        Mail.to("a@x.org").send(Hello("A"))


def test_smtp_error_propagates(smtp):
    smtp(host="h", port=25)
    FakeSMTP.fail = True
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        Mail.to("a@x.org").send(Hello("A"))


def test_smtp_rebuilt_each_send(smtp, mail_app):
    smtp(host="one", port=25)
    Mail.to("a@x.org").send(Hello("A"))
    mail_app.make("config").set("mail.mailers.smtp.host", "two")
    Mail.to("a@x.org").send(Hello("A"))
    assert [c[2] for c in FakeSMTP.calls if c[0] == "connect"] == ["one", "two"]


def test_unknown_transport(mail_app):
    mail_app.make("config").set("mail.mailers.x", {"transport": "carrier-pigeon"})
    with pytest.raises(ValueError, match="carrier-pigeon"):
        Mail.mailer("x").to("a@x.org").send(Hello("A"))


def test_log_transport(mail_app, caplog):
    config = mail_app.make("config")
    config.set("mail.default", "log")
    config.set("mail.mailers.smtp", {"transport": "smtp", "password": "s3cret"})
    with caplog.at_level(logging.INFO):
        Mail.to("a@x.org").send(Hello("A"))
    assert "a@x.org" in caplog.text and "Subject: Hi" in caplog.text
    assert "Hello A" in caplog.text and "s3cret" not in caplog.text
