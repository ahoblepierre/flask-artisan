import os
import re
import subprocess
import sys

import pytest
from click.testing import CliRunner

from flask_artisan.cli import main


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith(("FLASK_", "APP_"))}


def run(project, *args, **kwargs):
    return subprocess.run(
        [sys.executable, *args],
        check=False,
        cwd=project,
        env=clean_env(),
        capture_output=True,
        text=True,
        **kwargs,
    )


@pytest.fixture
def project(tmp_path):
    result = CliRunner().invoke(main, ["new", str(tmp_path / "blog")])
    assert result.exit_code == 0, result.output
    return tmp_path / "blog"


def test_new_creates_project(project):
    for path in [
        "wsgi.py",
        "bootstrap/app.py",
        "config/app.py",
        ".env",
        ".env.example",
        ".gitignore",
    ]:
        assert (project / path).exists(), path


def test_env_has_key_and_name(project, tmp_path):
    content = (project / ".env").read_text()
    assert "APP_NAME=blog" in content
    key = re.search(r"^APP_KEY=([0-9a-f]{64})$", content, re.MULTILINE)
    assert key
    CliRunner().invoke(main, ["new", str(tmp_path / "other")])
    assert key.group(1) not in (tmp_path / "other" / ".env").read_text()


def test_refuses_non_empty_dir(tmp_path):
    target = tmp_path / "blog"
    target.mkdir()
    (target / "keep.txt").write_text("x")
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code != 0
    assert "n'est pas vide" in result.output
    assert (target / "keep.txt").read_text() == "x"
    assert not (target / "wsgi.py").exists()


def test_accepts_existing_empty_dir(tmp_path):
    (tmp_path / "blog").mkdir()
    assert CliRunner().invoke(main, ["new", str(tmp_path / "blog")]).exit_code == 0
    assert (tmp_path / "blog" / "wsgi.py").exists()


def test_generated_app_responds(project):
    code = (
        "from wsgi import app; r = app.test_client().get('/'); print(r.status_code, r.get_json())"
    )
    out = run(project, "-c", code)
    assert "200" in out.stdout and "'blog'" in out.stdout, out.stderr


def test_flask_run_path_debug(project):
    show = "print('DEBUG=' + str(app.debug))\n"
    assert "DEBUG=True" in run(project, "-m", "flask", "shell", input=show).stdout
    env_file = project / ".env"
    env_file.write_text(env_file.read_text().replace("APP_DEBUG=true", "APP_DEBUG=false"))
    assert "DEBUG=False" in run(project, "-m", "flask", "shell", input=show).stdout


def test_generated_project_tests_pass(project):
    result = run(project, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    assert result.returncode == 0, result.stdout + result.stderr


def test_generated_project_has_routes(project):
    for path in ("routes/web.py", "routes/api.py", "app/http/kernel.py"):
        assert (project / path).exists(), path


def test_generated_home_is_named_route(project):
    code = (
        "from flask import url_for\nfrom wsgi import app\n"
        "with app.test_request_context():\n    print('URL=' + url_for('home'))\n"
        "print('VIEW=' + app.view_functions['home'].__qualname__)\n"
    )
    out = run(project, "-c", code)
    assert "URL=/" in out.stdout, out.stderr
    assert "VIEW=Router." in out.stdout, out.stdout  # déclarée via Route, pas @app.route


def test_generated_project_has_database_files(project):
    for path in ("config/database.py", "app/models/user.py", "database/migrations/.gitkeep"):
        assert (project / path).exists(), path


def test_generated_project_migrates(project):
    import sqlite3

    for args in (("make:migration", "create users"), ("migrate",)):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(project / "database" / "database.sqlite") as db:
        tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    assert {"users", "personal_access_tokens"} <= tables


AUTH_FLOW = """
from wsgi import app
from app.models.user import User

with app.app_context():
    User.create(name="A", email="a@x", password="secret")
c = app.test_client()
assert c.post("/api/login", json={"email": "a@x", "password": "bad"}).status_code == 401
assert c.post("/api/login").status_code == 401
assert c.post("/api/login", json=[1]).status_code == 401
assert c.post("/api/login", json={"email": "a@x", "password": 1}).status_code == 401
r = c.post("/api/login", json={"email": "a@x", "password": "secret"})
assert r.status_code == 200, r.data
auth = {"Authorization": "Bearer " + r.get_json()["token"]}
r = c.get("/api/user", headers=auth)
assert r.status_code == 200 and r.get_json()["email"] == "a@x", r.data
assert "password" not in r.get_json()
assert c.post("/api/logout", headers=auth).status_code == 204
assert c.get("/api/user", headers=auth).status_code == 401
print("OK")
"""


def test_generated_api_auth_flow(project):
    for args in (("make:migration", "init"), ("migrate",)):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    out = run(project, "-c", AUTH_FLOW)
    assert out.stdout.strip() == "OK", out.stdout + out.stderr
