import pytest

from flask_artisan import HttpKernel, Route, VerifyCsrfToken
from flask_artisan.views import csrf_token


class Kernel(HttpKernel):
    middleware = {"csrf": VerifyCsrfToken}


@pytest.fixture
def app(routed_app):
    def routes():
        Route.get("/form", lambda: {"token": csrf_token()}).middleware("csrf")
        Route.post("/submit", lambda: {"ok": True}).middleware("csrf")

    return routed_app(routes, kernel=Kernel)


@pytest.fixture
def client(app):
    return app.test_client()


def token(client):
    return client.get("/form").get_json()["token"]


def test_csrf_get_passes(client):
    client.get("/form").assert_ok()


def test_csrf_form_token_passes(client):
    client.post("/submit", data={"_token": token(client)}).assert_ok()


def test_csrf_header_token_passes(client):
    client.post("/submit", headers={"X-CSRF-TOKEN": token(client)}).assert_ok()


def test_csrf_wrong_token_419(client):
    token(client)
    response = client.post("/submit", data={"_token": "nope"}).assert_status(419)
    assert "expir" in response.get_data(as_text=True).lower()
    client.post(
        "/submit", data={"_token": "nope"}, headers={"Accept": "application/json"}
    ).assert_status(419).assert_json({"message": "CSRF token mismatch."})


@pytest.mark.parametrize("data", [{"_token": ""}, {}, {"_token": "é"}])
def test_csrf_missing_session_token(client, data):
    client.post("/submit", data=data).assert_status(419)


def test_csrf_skipped_when_testing(app, client):
    app.testing = True
    client.post("/submit").assert_ok()


def test_csrf_non_ascii_token_is_419(client):
    token(client)
    client.post("/submit", data={"_token": "é"}).assert_status(419)


def test_csrf_not_skipped_outside_testing_env(app, client):
    app.testing = True
    app.make("config").set("app.env", "production")
    client.post("/submit").assert_status(419)
