import pytest
from auth.conftest import auth_app  # noqa: F401 — fixture partagée
from auth.models import AMember

from flask_artisan import Auth, HttpKernel, Route
from flask_artisan.auth import Authenticate
from flask_artisan.rate_limiting import ThrottleRequests

from .conftest import CACHE


class Kernel(HttpKernel):
    middleware = {"throttle": ThrottleRequests, "auth": Authenticate}


def ok():
    return {"ok": True}


def login_as():
    Auth.login(AMember.find(1))
    return {"ok": True}


@pytest.fixture
def make_client(auth_app):  # noqa: F811
    def _make(declare):
        app = auth_app(declare, kernel=Kernel)
        app.make("config").set("cache", dict(CACHE))
        app.testing = True
        return app, app.test_client()

    return _make


def test_429_after_max(make_client, clock):
    _, c = make_client(lambda: Route.get("/t", ok).middleware("throttle:2,1"))
    assert c.get("/t").status_code == 200
    assert c.get("/t").status_code == 200
    r = c.get("/t")
    assert r.status_code == 429
    assert r.get_json() == {"message": "Too Many Attempts."}
    assert r.headers["Retry-After"] == "60"
    assert r.headers["X-RateLimit-Limit"] == "2"
    assert r.headers["X-RateLimit-Remaining"] == "0"
    assert r.headers["X-RateLimit-Reset"] == str(int(clock.now) + 60)


def test_headers_on_success(make_client, clock):
    _, c = make_client(lambda: Route.get("/t", ok).middleware("throttle:2,1"))
    r = c.get("/t")
    assert r.headers["X-RateLimit-Limit"] == "2"
    assert r.headers["X-RateLimit-Remaining"] == "1"


def test_window_reopens(make_client, clock):
    _, c = make_client(lambda: Route.get("/t", ok).middleware("throttle:1,1"))
    c.get("/t")
    assert c.get("/t").status_code == 429
    clock.advance(61)
    assert c.get("/t").status_code == 200


def test_refused_request_not_counted(make_client, clock):
    _, c = make_client(lambda: Route.get("/t", ok).middleware("throttle:2,1"))
    assert [c.get("/t").status_code for _ in range(3)] == [200, 200, 429]
    clock.advance(61)
    assert [c.get("/t").status_code for _ in range(2)] == [200, 200]


def test_limits_are_independent(make_client, clock):
    def routes():
        Route.get("/a", ok).middleware("throttle:1,1")
        Route.get("/b", ok).middleware("throttle:5,1")

    _, c = make_client(routes)
    c.get("/a")
    assert c.get("/a").status_code == 429
    assert c.get("/b").status_code == 200


def test_by_ip(make_client, clock):
    _, c = make_client(lambda: Route.get("/t", ok).middleware("throttle:1,1"))
    c.get("/t", environ_base={"REMOTE_ADDR": "1.1.1.1"})
    assert c.get("/t", environ_base={"REMOTE_ADDR": "1.1.1.1"}).status_code == 429
    assert c.get("/t", environ_base={"REMOTE_ADDR": "2.2.2.2"}).status_code == 200


def test_by_user_after_auth(make_client, clock):
    app, c = make_client(lambda: Route.get("/t", ok).middleware("auth:api", "throttle:1,1"))
    with app.app_context():
        first = AMember.create(email="a@x", password="secret").create_token("t")
        second = AMember.create(email="b@x", password="secret").create_token("t")

    def get(token):
        return c.get("/t", headers={"Authorization": f"Bearer {token}"}).status_code

    assert get(first) == 200
    assert get(first) == 429
    assert get(second) == 200


def test_throttle_does_not_authenticate(make_client, clock):
    def routes():
        Route.post("/login", login_as)
        Route.get("/t", ok).middleware("throttle:5,1")

    app, c = make_client(routes)
    with app.app_context():
        AMember.create(email="a@x", password="secret")
    c.post("/login")
    assert "Cookie" not in c.get("/t").headers.get("Vary", "")


def test_inner_429_headers_survive_outer(make_client, clock):
    _, c = make_client(lambda: Route.post("/login", ok).middleware("throttle:60,1", "throttle:1,1"))
    c.post("/login")
    r = c.post("/login")
    assert r.status_code == 429
    assert r.headers["X-RateLimit-Limit"] == "1"
    assert r.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.parametrize("params", ["abc,1", "0,1", "5,0"])
def test_invalid_parameters(make_client, clock, params):
    _, c = make_client(lambda: Route.get("/t", ok).middleware(f"throttle:{params}"))
    with pytest.raises(ValueError, match="throttle"):
        c.get("/t")


def test_parallel_burst_cannot_overshoot(make_client, clock, monkeypatch):
    from flask_artisan.rate_limiting import RateLimiter as Limiter

    _, c = make_client(lambda: Route.get("/t", ok).middleware("throttle:2,1"))
    # Rafale : toutes les requêtes lisent le compteur avant qu'aucune n'ait compté.
    monkeypatch.setattr(Limiter, "too_many_attempts", lambda self, key, limit: False)
    assert [c.get("/t").status_code for _ in range(4)] == [200, 200, 429, 429]
    monkeypatch.undo()
    clock.advance(61)
    assert [c.get("/t").status_code for _ in range(3)] == [200, 200, 429]


def test_identity_includes_guard_name():
    from types import SimpleNamespace

    from flask_artisan.rate_limiting import _identity

    def request(state):
        return SimpleNamespace(environ={"flask_artisan.auth": state}, remote_addr="1.1.1.1")

    user = SimpleNamespace(id=1)
    assert _identity(request({"user:web": user})) != _identity(request({"user:admin": user}))
    assert _identity(request({"user:web": None})) == "ip:1.1.1.1"
