import pytest

from flask_artisan import Auth, HttpKernel, Route
from flask_artisan.auth import Authenticate, AuthenticationError

from .models import AMember


class Kernel(HttpKernel):
    middleware = {"auth": Authenticate}


def me():
    return Auth.user()


def login_as(id):
    Auth.login(AMember.find(id))
    return {"ok": True}


def guard_name():
    return {"guard": type(Auth.guard()).__name__}


@pytest.fixture
def client_for(auth_app):
    def _make(declare):
        app = auth_app(declare, kernel=Kernel)
        app.testing = True
        with app.app_context():
            member = AMember.create(email="m@x", password="secret")
            token = member.create_token("t")
        return app.test_client(), member, token

    return _make


def test_auth_lets_logged_in_session_through(client_for):
    def routes():
        Route.get("/login-as/<int:id>", login_as)
        Route.get("/me", me).middleware("auth")

    client, member, _ = client_for(routes)
    client.get(f"/login-as/{member.id}")
    response = client.get("/me")
    assert response.status_code == 200
    assert response.get_json()["email"] == "m@x"
    assert "password" not in response.get_json()


def test_auth_api_with_bearer_sets_default_guard(client_for):
    client, member, token = client_for(lambda: Route.get("/api/me", me).middleware("auth:api"))
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["id"] == member.id


def test_auth_multiple_guards(client_for):
    client, _, token = client_for(lambda: Route.get("/me", me).middleware("auth:web,api"))
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_unauthenticated_json_when_client_wants_json(client_for):
    def routes():
        Route.get("/login", lambda: "form").name("login")
        Route.get("/me", me).middleware("auth")

    client, _, _ = client_for(routes)
    response = client.get("/me", headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.get_json() == {"message": "Unauthenticated."}


def test_browser_redirected_to_login_when_route_exists(client_for):
    def routes():
        Route.get("/connexion", lambda: "form").name("login")
        Route.get("/me", me).middleware("auth")

    client, _, _ = client_for(routes)
    response = client.get("/me", headers={"Accept": "text/html,*/*"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/connexion")


def test_browser_gets_401_without_login_route(client_for):
    client, _, _ = client_for(lambda: Route.get("/me", me).middleware("auth"))
    response = client.get("/me", headers={"Accept": "text/html,*/*"})
    assert response.status_code == 401
    assert response.get_json() == {"message": "Unauthenticated."}


def test_star_accept_alone_is_not_json(client_for):
    def routes():
        Route.get("/login", lambda: "form").name("login")
        Route.get("/me", me).middleware("auth")

    client, _, _ = client_for(routes)
    assert client.get("/me", headers={"Accept": "*/*"}).status_code == 302


def test_guard_does_not_leak_between_requests(client_for):
    def routes():
        Route.get("/api/me", me).middleware("auth:api")
        Route.get("/guard", guard_name)

    client, _, token = client_for(routes)
    client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert client.get("/guard").get_json() == {"guard": "SessionGuard"}


def test_unknown_guard_param_raises_on_request(client_for):
    client, _, _ = client_for(lambda: Route.get("/me", me).middleware("auth:nope"))
    with pytest.raises(AuthenticationError, match="nope"):
        client.get("/me")
