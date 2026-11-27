import flask
import pytest
from flask import redirect

from flask_artisan import Application
from flask_artisan.testing import TestClient, TestResponse

JSON = {"Content-Type": "application/json"}
BODY = {"user": {"id": 1, "email": "a@x"}, "tags": ["a", "b"]}


@pytest.fixture
def app(make_project):
    app = Application(make_project())
    app.add_url_rule("/json", "json", lambda: BODY)
    app.add_url_rule("/html", "html", lambda: "<p>hi</p>")
    app.add_url_rule("/created", "created", lambda: ("", 201))
    app.add_url_rule(
        "/invalid",
        "invalid",
        lambda: ({"message": "m", "errors": {"email": ["requis"]}}, 422),
    )
    app.add_url_rule(
        "/invalid-200", "invalid_200", lambda: {"message": "m", "errors": {"email": ["x"]}}
    )
    app.add_url_rule("/header", "header", lambda: ("", 200, {"X-Thing": "yes"}))
    app.add_url_rule("/go", "go", lambda: redirect("/login"))
    app.add_url_rule("/binary", "binary", lambda: (b"\xff\xfe\x00", 200))
    app.add_url_rule("/list-422", "list_422", lambda: (flask.json.dumps([1]), 422, JSON))
    app.add_url_rule("/flags", "flags", lambda: {"active": True, "count": 1})
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_test_client_is_artisan(app):
    client = app.test_client()
    assert isinstance(client, TestClient)
    assert isinstance(client.get("/json"), TestResponse)


def test_response_keeps_app_response_class(app):
    class MyResponse(flask.Response):
        def hello(self):
            return "hi"

    app.response_class = MyResponse
    response = app.test_client().get("/json")
    assert isinstance(response, MyResponse)
    assert response.hello() == "hi"
    response.assert_ok()


def test_assert_status_and_ok(client):
    client.get("/json").assert_ok().assert_status(200)
    with pytest.raises(AssertionError) as error:
        client.get("/json").assert_status(201)
    assert "201" in str(error.value) and "200" in str(error.value)
    with pytest.raises(AssertionError):
        client.get("/created").assert_ok()


def test_assertions_chain(client):
    response = client.get("/json")
    assert response.assert_ok().assert_json({"tags": ["a", "b"]}) is response


def test_assert_json_subset(client):
    response = client.get("/json")
    response.assert_json({"user": {"id": 1}})
    for data in ({"user": {"id": 2}}, {"tags": ["a"]}, {"absent": 1}):
        with pytest.raises(AssertionError):
            response.assert_json(data)


def test_assert_json_not_json(client):
    for path in ("/html", "/created"):
        with pytest.raises(AssertionError, match="JSON"):
            client.get(path).assert_json({"a": 1})


def test_assert_json_path(client):
    response = client.get("/json")
    response.assert_json_path("user.email", "a@x").assert_json_path("tags.1", "b")
    with pytest.raises(AssertionError):
        response.assert_json_path("user.email", "b@x")


@pytest.mark.parametrize(
    ("path", "segment"), [("user.phone", "phone"), ("tags.5", "5"), ("tags.x", "x")]
)
def test_assert_json_path_missing(client, path, segment):
    with pytest.raises(AssertionError, match=segment):
        client.get("/json").assert_json_path(path, 1)


def test_assert_json_validation_errors(client):
    response = client.get("/invalid")
    response.assert_json_validation_errors("email").assert_json_validation_errors(["email"])
    with pytest.raises(AssertionError, match="name"):
        response.assert_json_validation_errors(["name"])
    with pytest.raises(AssertionError, match="422"):
        client.get("/invalid-200").assert_json_validation_errors(["email"])


def test_assert_header(client):
    response = client.get("/header")
    response.assert_header("X-Thing").assert_header("X-Thing", "yes")
    with pytest.raises(AssertionError):
        response.assert_header("X-Other")
    with pytest.raises(AssertionError):
        response.assert_header("X-Thing", "no")


def test_assert_redirect(client):
    client.get("/go").assert_redirect().assert_redirect("/login")
    with pytest.raises(AssertionError):
        client.get("/go").assert_redirect("/home")
    with pytest.raises(AssertionError):
        client.get("/json").assert_redirect()


def test_failure_on_binary_body_is_assertion(client):
    with pytest.raises(AssertionError, match="201"):
        client.get("/binary").assert_status(201)


def test_validation_errors_on_non_dict_json(client):
    with pytest.raises(AssertionError, match="email"):
        client.get("/list-422").assert_json_validation_errors(["email"])


def test_assert_json_path_unicode_digit(client):
    with pytest.raises(AssertionError, match="²"):
        client.get("/json").assert_json_path("tags.²", "a")


def test_bool_and_int_are_distinct(client):
    response = client.get("/flags")
    response.assert_json({"active": True, "count": 1}).assert_json_path("count", 1)
    for data in ({"active": 1}, {"count": True}):
        with pytest.raises(AssertionError):
            response.assert_json(data)
    with pytest.raises(AssertionError):
        response.assert_json_path("active", 1)
