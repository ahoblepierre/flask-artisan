import pytest

from flask_artisan import Auth, HttpKernel, Route
from flask_artisan.auth import Authenticate, AuthenticationError

from .models import AMember


class Kernel(HttpKernel):
    middleware = {"auth": Authenticate}


def me():
    return Auth.user()


def token_name():
    return {"name": Auth.user().current_access_token().name}


def routes():
    Route.get("/me", me).middleware("auth")
    Route.get("/api/me", me).middleware("auth:api")
    Route.get("/api/token", token_name).middleware("auth:api")


@pytest.fixture
def setup(auth_app):
    app = auth_app(routes, kernel=Kernel)
    app.testing = True
    with app.app_context():
        a = AMember.create(email="a@x", password="secret")
        b = AMember.create(email="b@x", password="secret")
    return app.test_client(), a, b


def test_acting_as_session_guard(setup):
    client, a, _ = setup
    client.acting_as(a).get("/me").assert_ok().assert_json({"email": "a@x"})


def test_acting_as_token_guard(setup):
    client, a, _ = setup
    client.acting_as(a, "api").get("/api/me").assert_ok().assert_json({"email": "a@x"})
    client.get("/api/token").assert_ok().assert_json({"name": "test"})


def test_acting_as_default_guard_is_not_api(setup):
    client, a, _ = setup
    client.acting_as(a).get("/api/me").assert_status(401)


@pytest.mark.parametrize(("guard", "path"), [(None, "/me"), ("api", "/api/me")])
def test_acting_as_replaces_user(setup, guard, path):
    client, a, b = setup
    client.acting_as(a, guard).acting_as(b, guard).get(path).assert_json({"email": "b@x"})


def test_acting_as_unknown_guard(setup):
    client, a, _ = setup
    with pytest.raises(AuthenticationError):
        client.acting_as(a, "nope")


def test_acting_as_returns_client(setup):
    client, a, _ = setup
    assert client.acting_as(a) is client


def test_acting_as_keeps_callers_db_session(setup):
    from sqlalchemy import inspect

    from flask_artisan import DB

    client, a, _ = setup
    with client.application.app_context():
        member = AMember.find(a.id)
        session = DB.session
        for guard in (None, "api"):
            client.acting_as(member, guard)
            assert DB.session is session
            assert not inspect(member).detached


def test_acting_as_switching_guard_drops_previous_user(setup):
    client, a, b = setup
    client.acting_as(a, "api").acting_as(b)
    client.get("/api/me").assert_status(401)
    client.get("/me").assert_json({"email": "b@x"})
    client.acting_as(a).acting_as(b, "api")
    client.get("/me").assert_status(401)
    client.get("/api/me").assert_json({"email": "b@x"})


def test_acting_as_session_starts_fresh_like_login(setup):
    client, a, _ = setup
    with client.session_transaction() as session:
        session["cart"] = [1]
    client.acting_as(a)
    with client.session_transaction() as session:
        assert "cart" not in session
