import pytest
from flask import session

from flask_artisan import Auth
from flask_artisan.auth import AuthenticationError

from .models import AMember, AMemberSD


@pytest.fixture
def app(auth_app):
    return auth_app()


@pytest.fixture
def member(app):
    with app.app_context():
        return AMember.create(email="m@x", password="secret")


def test_attempt_logs_in_and_user_returns_member(app, member):
    with app.test_request_context():
        assert Auth.attempt(email="m@x", password="secret") is True
        assert Auth.user().id == member.id
        assert Auth.id() == member.id
        assert Auth.check() and not Auth.guest()


@pytest.mark.parametrize(
    "creds",
    [
        {"email": "m@x", "password": "wrong"},
        {"email": "nobody@x", "password": "secret"},
        {"email": "m@x"},
    ],
)
def test_attempt_wrong_password_unknown_email_missing_password(app, member, creds):
    with app.test_request_context():
        assert Auth.attempt(**creds) is False
        assert Auth.user() is None


def test_validate_none_credential_is_rejected(app):
    with app.app_context():
        AMember.create(email=None, password="secret")
    with app.test_request_context():
        assert Auth.validate(email=None, password="secret") is None


def test_validate_returns_user_without_login(app, member):
    with app.test_request_context():
        assert Auth.validate(email="m@x", password="secret").id == member.id
        assert Auth.user() is None


def test_validate_unknown_email_checks_dummy_hash(app, monkeypatch):
    from flask_artisan.auth import manager

    calls = []
    real = manager.check_password_hash
    monkeypatch.setattr(manager, "check_password_hash", lambda h, p: calls.append(p) or real(h, p))
    with app.test_request_context():
        assert Auth.validate(email="nobody@x", password="secret") is None
    assert calls == ["secret"]


def test_login_clears_session_first(app, member):
    with app.test_request_context():
        session["foo"] = 1
        Auth.login(member)
        assert "foo" not in session
        assert Auth.user().id == member.id


def test_logout_forgets_user(app, member):
    with app.test_request_context():
        Auth.login(member)
        Auth.logout()
        assert Auth.user() is None
        assert not session


def test_session_user_missing_or_soft_deleted_is_none(auth_app):
    app = auth_app(model=AMemberSD)
    with app.test_request_context():
        m = AMemberSD.create(email="s@x", password="secret")
        Auth.login(m)
        uid = m.id
    with app.test_request_context():
        session["_auth_user_id"] = uid
        AMemberSD.find(uid).delete()
        assert Auth.user() is None
    with app.test_request_context():
        session["_auth_user_id"] = 12345
        assert Auth.user() is None


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_token_guard_reads_bearer(app, member):
    with app.app_context():
        plain = member.create_token("t")
    with app.test_request_context(headers=bearer(plain)):
        user = Auth.guard("api").user()
        assert user.id == member.id
        assert user.current_access_token().id == int(plain.split("|")[0])


@pytest.mark.parametrize("header", ["Token abc", "Bearer", "Bearer x|y", None])
def test_token_guard_malformed_headers(app, member, header):
    headers = {"Authorization": header} if header else {}
    with app.test_request_context(headers=headers):
        assert Auth.guard("api").user() is None


def test_token_of_deleted_user_is_none(app, member):
    with app.app_context():
        plain = member.create_token("t")
        AMember.find(member.id).delete()
    with app.test_request_context(headers=bearer(plain)):
        assert Auth.guard("api").user() is None


@pytest.mark.parametrize("call", ["attempt", "login", "logout"])
def test_token_guard_rejects_attempt_login_logout(app, member, call):
    args = {"attempt": ((), {"email": "m@x", "password": "secret"}), "login": ((member,), {})}
    a, kw = args.get(call, ((), {}))
    with app.test_request_context(), pytest.raises(AuthenticationError):
        getattr(Auth.guard("api"), call)(*a, **kw)


def test_unknown_guard_lists_configured(app):
    with app.test_request_context(), pytest.raises(AuthenticationError, match="web, api"):
        Auth.guard("nope")


def test_user_outside_request_is_none(app):
    with app.app_context():
        assert Auth.user() is None


def test_provider_without_auth_config_fails(db_app):
    with pytest.raises(AuthenticationError, match="config/auth.py"):
        db_app("flask_artisan.auth.AuthServiceProvider")


@pytest.mark.parametrize(
    "creds",
    [
        {"email": "m@x", "password": 123},
        {"email": ["m@x"], "password": "secret"},
        {"email": {"a": 1}, "password": "secret"},
    ],
)
def test_validate_non_string_credentials_is_none(app, member, creds):
    with app.test_request_context():
        assert Auth.validate(**creds) is None


def test_password_change_ends_existing_sessions(app, member):
    with app.test_request_context():
        Auth.login(member)
        saved = dict(session)
    with app.test_request_context():
        AMember.find(member.id).update(password="changed")
    with app.test_request_context():
        session.update(saved)
        assert Auth.user() is None
