import hashlib
from datetime import timedelta

import pytest

from flask_artisan import DB
from flask_artisan.auth import passwords
from flask_artisan.auth.notifications import ResetPassword
from flask_artisan.auth.passwords import Password, PasswordResetToken
from flask_artisan.notifications import Notification

from .conftest import AUTH_CONFIG
from .models import PwTokenUser, PwUser


@pytest.fixture
def app(db_app):
    app = db_app("flask_artisan.auth.AuthServiceProvider", configs={"auth": AUTH_CONFIG})
    app.make("config").set("auth.model", PwUser)
    with app.app_context():
        yield app


@pytest.fixture
def fake():
    with Notification.fake() as fake:
        yield fake


@pytest.fixture
def clock(monkeypatch):
    start = passwords._now()
    state = {"now": start}
    monkeypatch.setattr(passwords, "_now", lambda: state["now"])

    def advance(**delta):
        state["now"] = state["now"] + timedelta(**delta)

    return advance


@pytest.fixture
def ada(app):
    return PwUser.create(email="ada@x.org", password="old-secret")


def emailed_token(fake, user) -> str:
    return fake.sent(ResetPassword)[-1][1].token


def test_send_reset_link_stores_hashed_token(ada, fake):
    assert Password.send_reset_link("ada@x.org") == Password.RESET_LINK_SENT
    token = emailed_token(fake, ada)
    fake.assert_sent_to(ada, ResetPassword)
    [row] = PasswordResetToken.all()
    assert row.email == "ada@x.org"
    assert row.token == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row.token


def test_unknown_email(app, fake):
    assert Password.send_reset_link("nobody@x.org") == Password.INVALID_USER
    fake.assert_nothing_sent()
    assert PasswordResetToken.all() == []


def test_throttled_within_60_seconds(ada, fake, clock):
    Password.send_reset_link("ada@x.org")
    clock(seconds=30)
    assert Password.send_reset_link("ada@x.org") == Password.RESET_THROTTLED
    fake.assert_sent_times(ResetPassword, 1)
    clock(seconds=31)
    assert Password.send_reset_link("ada@x.org") == Password.RESET_LINK_SENT
    [row] = PasswordResetToken.all()
    assert row.token == hashlib.sha256(emailed_token(fake, ada).encode()).hexdigest()


def test_reset_changes_password_and_consumes_token(ada, fake):
    Password.send_reset_link("ada@x.org")
    token = emailed_token(fake, ada)
    assert Password.reset("ada@x.org", token, "new-secret") == Password.PASSWORD_RESET
    DB.session.expire_all()
    assert PwUser.find(ada.id).check_password("new-secret")
    assert PasswordResetToken.all() == []
    assert Password.reset("ada@x.org", token, "again") == Password.INVALID_TOKEN


def test_reset_rejects_wrong_token(ada, fake):
    Password.send_reset_link("ada@x.org")
    assert Password.reset("ada@x.org", "wrong", "new-secret") == Password.INVALID_TOKEN
    assert Password.reset("nobody@x.org", "wrong", "new-secret") == Password.INVALID_USER
    DB.session.expire_all()
    assert PwUser.find(ada.id).check_password("old-secret")


def test_reset_accepts_fresh_token_after_reload(ada, fake, clock):
    Password.send_reset_link("ada@x.org")
    token = emailed_token(fake, ada)
    DB.session.expire_all()
    clock(minutes=59)
    assert Password.reset("ada@x.org", token, "new-secret") == Password.PASSWORD_RESET


def test_reset_rejects_expired_token(ada, fake, clock):
    Password.send_reset_link("ada@x.org")
    token = emailed_token(fake, ada)
    DB.session.expire_all()
    clock(minutes=61)
    assert Password.reset("ada@x.org", token, "new-secret") == Password.INVALID_TOKEN


def test_reset_revokes_api_tokens(app, fake):
    app.make("config").set("auth.model", PwTokenUser)
    bob = PwTokenUser.create(email="bob@x.org", password="old-secret")
    bob.create_token("a")
    bob.create_token("b")
    Password.send_reset_link("bob@x.org")
    Password.reset("bob@x.org", emailed_token(fake, bob), "new-secret")
    assert bob.tokens().count() == 0


def test_config_overrides_expiry(app, ada, fake, clock):
    app.make("config").set("auth.passwords.expire", 5)
    Password.send_reset_link("ada@x.org")
    clock(minutes=6)
    assert Password.reset("ada@x.org", emailed_token(fake, ada), "x") == Password.INVALID_TOKEN


def test_token_is_keyed_on_stored_email(ada, fake, monkeypatch):
    # Base insensible à la casse (MySQL) : "Ada@x.org" trouve le compte "ada@x.org".
    monkeypatch.setattr(Password, "_user", staticmethod(lambda email: ada))
    assert Password.send_reset_link("Ada@x.org") == Password.RESET_LINK_SENT
    [row] = PasswordResetToken.all()
    assert row.email == "ada@x.org"
    assert Password.send_reset_link("ADA@x.org") == Password.RESET_THROTTLED
    token = emailed_token(fake, ada)
    assert Password.reset("Ada@X.org", token, "new-secret") == Password.PASSWORD_RESET


def test_concurrent_request_is_throttled_not_500(ada, fake, monkeypatch):
    Password.send_reset_link("ada@x.org")
    session = DB.session
    real_get = session.get
    # L'autre requête a inséré sa ligne entre notre lecture et notre commit.
    monkeypatch.setattr(session, "get", lambda *a, **k: None)
    session.expunge_all()
    assert Password.send_reset_link("ada@x.org") == Password.RESET_THROTTLED
    monkeypatch.setattr(session, "get", real_get)
    fake.assert_sent_times(ResetPassword, 1)
    assert len(PasswordResetToken.all()) == 1


def test_expired_rows_are_purged(app, ada, fake, clock):
    PwUser.create(email="bob@x.org", password="secret")
    Password.send_reset_link("bob@x.org")
    clock(minutes=61)
    Password.send_reset_link("ada@x.org")
    assert [row.email for row in PasswordResetToken.all()] == ["ada@x.org"]
