from pathlib import Path

import pytest
from flask import render_template, request

from flask_artisan import Route
from flask_artisan.validation import validate
from flask_artisan.views import ErrorBag, csrf_field, csrf_token

TEMPLATE = "{{ errors.first('email') }}|{{ old('email') }}|{{ errors.any() }}|{{ csrf_field() }}"


def store():
    validate(request.form.to_dict(), {"email": "required|email"})
    return {"ok": True}


@pytest.fixture
def client(routed_app):
    def routes():
        Route.get("/form", lambda: render_template("form.html"))
        Route.post("/form", store)
        Route.get("/json", lambda: {"ok": True})

    app = routed_app(routes)
    views = Path(app.root_path) / "resources" / "views"
    views.mkdir(parents=True)
    (views / "form.html").write_text(TEMPLATE)
    return app.test_client()


def page(client):
    return client.get("/form").get_data(as_text=True)


def test_errors_and_old_in_template(client):
    client.post("/form", data={"email": "x"})
    error, old, any_, field = page(client).split("|")
    assert "email" in error.lower() and old == "x" and any_ == "True"
    assert 'name="_token"' in field


def test_flash_lasts_one_request(client):
    client.post("/form", data={"email": "x"})
    page(client)
    assert page(client).startswith("||False|")


def test_no_session_cookie_without_flash(client):
    assert "Set-Cookie" not in client.get("/json").headers


def test_error_bag():
    bag = ErrorBag({"email": ["a", "b"], "name": ["c"]})
    assert bag.first("email") == "a" and bag.get("x") == [] and bag.first("x") == ""
    assert bag.all() == ["a", "b", "c"] and bag.has("name") and not bag.has("x")
    assert bag.any() and bool(bag) and not ErrorBag({}) and not ErrorBag({}).any()


def test_csrf_field_escapes_and_reuses_token(client):
    with client.application.test_request_context():
        token = csrf_token()
        assert csrf_token() == token and len(token) >= 40
        assert f'name="_token" value="{token}"' in str(csrf_field())
