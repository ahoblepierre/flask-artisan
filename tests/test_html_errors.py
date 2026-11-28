import random

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


def noise(seed: int, n: int) -> str:
    """Texte CJK peu compressible, comme une vraie saisie."""
    rng = random.Random(seed)
    return "".join(chr(rng.randrange(0x4E00, 0x9FFF)) for _ in range(n))


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


@pytest.mark.parametrize(
    "headers",
    [
        {"Referer": "https://evil.example/x"},
        {"Referer": "http://localhost.evil.com/x"},
        {"Referer": "//evil.com/x"},
        {"Referer": "http://localhost@evil.com/x"},
        {},
    ],
)
def test_foreign_referer_redirects_home(app, headers):
    app.test_client().post("/form", data=DATA, headers=headers).assert_redirect("/")


def test_long_input_not_flashed(app):
    client = app.test_client()
    client.post("/form", data={**DATA, "bio": "a" * 2001}, headers=REFERER)
    assert "bio" not in flashed(client)["_flash_old"]


def test_html_authorization_is_html_403(app):
    client = app.test_client()
    response = client.get("/deny").assert_status(403)
    assert response.mimetype == "text/html"
    client.get("/deny", headers={"Accept": "application/json"}).assert_status(403).assert_json(
        {"message": "This action is unauthorized."}
    )


def test_non_latin_input_does_not_overflow_cookie(app):
    client = app.test_client()
    fields = {f"f{i}": noise(i, 1000) for i in range(5)}
    response = client.post("/form", data={**DATA, **fields}, headers=REFERER)
    cookie = response.headers.get("Set-Cookie", "")
    assert 0 < len(cookie) < 4000
    session = flashed(client)
    assert "email" in session["_flash_errors"] and session["_flash_old"]["email"] == "x"


def test_many_small_fields_stay_under_budget(app):
    client = app.test_client()
    fields = {f"f{i}": noise(i, 150) for i in range(40)}
    response = client.post("/form", data={**DATA, **fields}, headers=REFERER)
    cookie = response.headers.get("Set-Cookie", "")
    assert 0 < len(cookie) < 4000


def test_xhr_request_keeps_422(app):
    app.test_client().post(
        "/form", data=DATA, headers={"X-Requested-With": "XMLHttpRequest"}
    ).assert_status(422)


def test_fallback_respects_script_root(app):
    app.test_client().post("/form", data=DATA, base_url="http://localhost/blog").assert_redirect(
        "/blog/"
    )


def test_reset_token_is_never_flashed(app):
    client = app.test_client()
    data = {"email": "x", "token": "secret-reset-token", "password": "s"}
    client.post("/form?token=from-query", data=data, headers=REFERER)
    old = flashed(client)["_flash_old"]
    assert old == {"email": "x"}
