import pytest
from flask import request

from flask_artisan import Route
from flask_artisan.routing import RouteGroup, Router
from flask_artisan.validation import AuthorizationError, validate

REFERER = {"Referer": "http://localhost/form"}
DATA = {"email": "x", "name": "Ada", "password": "s"}


def store():
    validate(
        request.form.to_dict() or request.get_json(silent=True) or {}, {"email": "required|email"}
    )
    return {"ok": True}


def deny():
    raise AuthorizationError()


@pytest.fixture
def app(routed_app):
    def routes():
        from flask_artisan import App

        Route.post("/form", store)
        Route.get("/deny", deny)
        with RouteGroup(App.make(Router), prefix="/api", json=True):
            Route.post("/form", store)

    return routed_app(routes)


def flashed(client):
    with client.session_transaction() as session:
        return dict(session)


def test_html_validation_redirects_back(app):
    client = app.test_client()
    client.post("/form", data=DATA, headers=REFERER).assert_redirect("http://localhost/form")
    session = flashed(client)
    assert "email" in session["_flash_errors"]
    assert session["_flash_old"] == {"email": "x", "name": "Ada"}


def test_json_request_keeps_422(app):
    app.test_client().post("/form", json=DATA).assert_status(422).assert_json_validation_errors(
        ["email"]
    )


def test_api_route_always_json(app):
    response = app.test_client().post("/api/form", data=DATA, headers=REFERER)
    response.assert_status(422).assert_json_validation_errors(["email"])
    assert "Set-Cookie" not in response.headers


@pytest.mark.parametrize("headers", [{"Referer": "https://evil.example/x"}, {}])
def test_foreign_referer_redirects_home(app, headers):
    app.test_client().post("/form", data=DATA, headers=headers).assert_redirect("/")


def test_long_input_not_flashed(app):
    client = app.test_client()
    client.post("/form", data={**DATA, "bio": "a" * 1001}, headers=REFERER)
    assert "bio" not in flashed(client)["_flash_old"]


def test_html_authorization_is_html_403(app):
    client = app.test_client()
    response = client.get("/deny").assert_status(403)
    assert response.mimetype == "text/html"
    client.get("/deny", headers={"Accept": "application/json"}).assert_status(403).assert_json(
        {"message": "This action is unauthorized."}
    )
