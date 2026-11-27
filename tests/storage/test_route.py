import pytest

from flask_artisan import Application, Storage
from flask_artisan.routing import Router

SERVED = """config = {{
    "disks": {{
        "public": {{"driver": "local", "root": {root!r}, "url": "/storage", "serve": {serve}}},
    }},
}}
"""


def make_app(make_project, tmp_path, serve=True):
    base = make_project()
    (base / "config" / "filesystems.py").write_text(
        SERVED.format(root=str(tmp_path / "public"), serve=serve)
    )
    return Application(base)


@pytest.fixture
def app(make_project, tmp_path):
    return make_app(make_project, tmp_path)


@pytest.fixture
def client(app):
    return app.test_client()


def test_route_serves_safe_inline(app, client):
    Storage.disk("public").put("a.png", b"\x89PNG")
    response = client.get("/storage/a.png").assert_ok()
    assert response.data == b"\x89PNG"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "attachment" not in response.headers.get("Content-Disposition", "")


@pytest.mark.parametrize("name", ["a.html", "a.svg", "a.js", "noext"])
def test_route_attachment_for_unsafe_types(app, client, name):
    Storage.disk("public").put(name, b"<script>alert(1)</script>")
    response = client.get(f"/storage/{name}").assert_ok()
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("path", ["../config/app.py", "%2e%2e/config/app.py", "absent.txt", "a//b"])
def test_route_rejects_traversal(app, client, path):
    client.get(f"/storage/{path}").assert_status(404)


def test_route_serves_fake(app, client):
    Storage.fake("public").put("x.txt", "f")
    assert client.get("/storage/x.txt").assert_ok().data == b"f"
    Storage.restore()


def test_route_in_route_list(app):
    names = [endpoint for _, endpoint, _ in app.make(Router).registered]
    assert "storage.public" in names


def test_no_route_without_serve(make_project, tmp_path):
    app = make_app(make_project, tmp_path, serve=False)
    app.test_client().get("/storage/x").assert_status(404)
    assert "storage.public" not in app.view_functions


MINE = """
from flask_artisan import Route
from flask_artisan.providers import ServiceProvider


def mine(p):
    return "mine"


class Mine(ServiceProvider):
    def boot(self):
        Route.get("/storage/<path:p>", mine)
"""


def test_project_storage_route_wins(make_project):
    app = Application(make_project(providers="[Mine]", extra=MINE))
    assert app.test_client().get("/storage/hello.txt").data == b"mine"


def test_route_attachment_has_filename(app, client):
    Storage.disk("public").put("page.html", b"x")
    assert 'filename="page.html"' in client.get("/storage/page.html").headers["Content-Disposition"]


def test_route_serves_bmp_inline(app, client):
    Storage.disk("public").put("a.bmp", b"BM")
    assert "attachment" not in client.get("/storage/a.bmp").headers.get("Content-Disposition", "")


@pytest.mark.parametrize("path", [".env", "a/.tmp-abc", ".git/config"])
def test_route_hides_dotfiles(app, client, path):
    Storage.disk("public").put(path, "secret")
    client.get(f"/storage/{path}").assert_status(404)
