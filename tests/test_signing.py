import pytest

from flask_artisan import Route, ValidateSignature, signed_url, signing


@pytest.fixture
def app(routed_app):
    def routes():
        Route.get("/files/<int:id>", lambda id: "ok").name("files.show").middleware(
            ValidateSignature
        )

    return routed_app(routes)


@pytest.fixture
def client(app):
    return app.test_client()


def sign(app, **kw):
    with app.test_request_context():
        return signed_url("files.show", **kw)


def test_signed_url_is_accepted(app, client):
    response = client.get(sign(app, id=3)).assert_ok()
    assert response.get_data(as_text=True) == "ok"


def test_signed_url_with_expiry(app, client, monkeypatch):
    url = sign(app, id=3, expires=60)
    assert "expires=" in url
    client.get(url).assert_ok()
    now = signing._now()
    monkeypatch.setattr(signing, "_now", lambda: now + 61)
    response = client.get(url)
    assert response.status_code == 403
    assert response.get_json() == {"message": "Invalid signature."}


def test_tampered_urls_are_rejected(app, client):
    url = sign(app, id=3, expires=60)
    path, query = url.split("?")
    params = query.split("&")
    expires = next(p for p in params if p.startswith("expires="))
    signature = next(p for p in params if p.startswith("signature="))
    later = f"expires={int(expires.split('=')[1]) + 1000}"
    for bad in (
        url.replace("/files/3", "/files/4"),
        url.replace(expires, later),
        url + "&signature=x",
        f"{path}?{expires}",
        f"{path}?{expires}&a=1&{signature}",
        f"{path}?expires=abc&{signature}",
    ):
        assert client.get(bad).status_code == 403, bad


def test_external_signed_url(app, client):
    url = sign(app, id=3, _external=True)
    assert url.startswith("http://localhost/")
    client.get(url.removeprefix("http://localhost")).assert_ok()


def test_signature_depends_on_app_key(app, client):
    url = sign(app, id=3)
    app.config["SECRET_KEY"] = "another-key"
    assert client.get(url).status_code == 403


def test_encoded_path_params_are_accepted(routed_app):
    app = routed_app(
        lambda: Route.get("/s/<name>", lambda name: name).name("s").middleware(ValidateSignature)
    )
    client = app.test_client()
    for name in ("a b", "é", "x@y"):
        with app.test_request_context():
            url = signed_url("s", name=name)
        assert client.get(url).get_data(as_text=True) == name, url


def test_app_under_script_root(app, client):
    with app.test_request_context(base_url="http://localhost/app/"):
        url = signed_url("files.show", id=3)
    assert url.startswith("/app/files/3")
    response = client.get(url.removeprefix("/app"), base_url="http://localhost/app/")
    response.assert_ok()


def test_non_utf8_query_is_forbidden_not_500(client):
    # WSGI : QUERY_STRING en latin-1, l'octet 0xFF n'est pas de l'UTF-8 valide.
    response = client.get("/files/3", environ_overrides={"QUERY_STRING": "a=\xff&signature=x"})
    assert response.status_code == 403
