import pytest
from flask import request as flask_request

from flask_artisan import Route
from flask_artisan.validation import FormRequest

calls = []


class StoreRequest(FormRequest):
    def rules(self):
        rules = {"title": "required|string|max:5"}
        if "id" in flask_request.view_args:
            rules["id_echo"] = f"sometimes|in:{flask_request.view_args['id']}"
        return rules


class DenyRequest(FormRequest):
    def authorize(self):
        return False

    def rules(self):
        return {}


class Ctl:
    def store(self, request: StoreRequest):
        calls.append(request.validated())
        return request.validated(), 201

    def deny(self, request: DenyRequest):
        calls.append("deny")
        return "x"


@pytest.fixture
def client(routed_app):
    calls.clear()

    def routes():
        Route.post("/posts", Ctl.store)
        Route.post("/posts/<id>", Ctl.store)
        Route.post("/deny", Ctl.deny)

    return routed_app(routes).test_client()


def test_valid_request_reaches_controller(client):
    r = client.post("/posts", json={"title": "Hi", "extra": 1})
    assert r.status_code == 201
    assert r.get_json() == {"title": "Hi"}


def test_invalid_request_is_422_and_controller_not_called(client):
    r = client.post("/posts", json={})
    assert r.status_code == 422
    assert r.get_json()["errors"] == {"title": ["The title field is required."]}
    assert calls == []


def test_unauthorized_is_403(client):
    r = client.post("/deny")
    assert r.status_code == 403
    assert r.get_json() == {"message": "This action is unauthorized."}
    assert calls == []


def test_form_and_query_sources(client):
    assert client.post("/posts?title=Query").get_json() == {"title": "Query"}
    assert client.post("/posts?title=Query", data={"title": "Form"}).get_json() == {"title": "Form"}


@pytest.mark.parametrize("body", ["[1]", "{broken"])
def test_non_object_json_is_empty_body(client, body):
    r = client.post("/posts", data=body, content_type="application/json")
    assert r.status_code == 422


def test_route_params_usable_in_rules(client):
    assert client.post("/posts/7", json={"title": "a", "id_echo": "7"}).status_code == 201
    assert client.post("/posts/7", json={"title": "a", "id_echo": "8"}).status_code == 422


def test_all_and_input(routed_app):
    seen = {}

    class Probe:
        def show(self, request: StoreRequest):
            seen.update(all=request.all(), title=request.input("title"), x=request.input("x", 0))
            return ""

    client = routed_app(lambda: Route.post("/p", (Probe, "show"))).test_client()
    client.post("/p?q=1", json={"title": "a"})
    assert seen == {"all": {"q": "1", "title": "a"}, "title": "a", "x": 0}


def test_outside_request_is_an_error():
    with pytest.raises(RuntimeError):
        StoreRequest()
