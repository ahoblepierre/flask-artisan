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
        "config/mail.py",
        "app/mail/__init__.py",
        "resources/views/emails/.gitkeep",
        "config/queue.py",
        "app/jobs/__init__.py",
        "config/cache.py",
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


# 5 POST /api/login exactement : la route est limitée à 5 par minute (throttle:5,1).
AUTH_FLOW = """
from wsgi import app
from app.models.user import User

with app.app_context():
    User.create(name="A", email="a@x.org", password="secret")
c = app.test_client()
assert c.post("/api/login", json={"email": "a@x.org", "password": "bad"}).status_code == 401
r = c.post("/api/login")
assert r.status_code == 422 and set(r.get_json()["errors"]) == {"email", "password"}, r.data
assert c.post("/api/login", json=[1]).status_code == 422
assert c.post("/api/login", json={"email": "a@x.org", "password": 1}).status_code == 422
r = c.post("/api/login", json={"email": "a@x.org", "password": "secret"})
assert r.status_code == 200, r.data
auth = {"Authorization": "Bearer " + r.get_json()["token"]}
r = c.get("/api/user", headers=auth)
assert r.status_code == 200 and r.get_json()["email"] == "a@x.org", r.data
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


THROTTLE_FLOW = """
from wsgi import app
c = app.test_client()
for _ in range(5):
    assert c.post("/api/login", json={"email": "a@x.org", "password": "bad"}).status_code == 401
r = c.post("/api/login", json={"email": "a@x.org", "password": "bad"})
assert r.status_code == 429 and r.headers["Retry-After"], (r.status_code, r.data)
print("OK")
"""


def test_generated_login_is_throttled(project):
    for args in (("make:migration", "init"), ("migrate",)):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    out = run(project, "-c", THROTTLE_FLOW)
    assert out.stdout.strip() == "OK", out.stdout + out.stderr


def test_generated_project_console(project):
    from pathlib import Path

    repo_config = str(Path(__file__).resolve().parent.parent / "pyproject.toml")
    assert (project / "app/console/commands/__init__.py").exists()
    for args in (
        ("make:controller", "PhotoController", "--resource"),
        ("make:command", "SendEmails"),
    ):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    result = run(project, "-m", "flask", "app:send-emails")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "app:send-emails : terminé." in result.stdout
    result = run(project, "-m", "flask", "route:list")
    assert result.returncode == 0, result.stdout + result.stderr
    for text in ("api.login", "AuthController@login", "Authenticate:api", "ThrottleRequests:5,1"):
        assert text in result.stdout, result.stdout
    generated = [
        "app/http/controllers/photo_controller.py",
        "app/console/commands/send_emails.py",
    ]
    for args in (["check"], ["format", "--check"]):
        result = run(project, "-m", "ruff", *args, "--config", repo_config, *generated)
        assert result.returncode == 0, result.stdout + result.stderr


def test_generated_project_broken_command_is_reported(project):
    (project / "app/console/commands/broken.py").write_text("raise RuntimeError('boom')\n")
    # Flask attrape l'erreur pendant --help : trace affichée (code 0).
    result = run(project, "-m", "flask", "--help")
    assert "broken.py" in result.stdout + result.stderr
    # Les commandes du framework marchent toujours, pour pouvoir réparer.
    assert run(project, "-m", "flask", "route:list").returncode == 0
    # Une commande du projet échoue en nommant le fichier.
    result = run(project, "-m", "flask", "app:send-emails")
    assert result.returncode != 0
    assert "app/console/commands/broken.py" in result.stdout + result.stderr
    assert run(project, "-c", "from wsgi import app; print(app.name)").returncode == 0


def test_generated_requirements_pin_pypi_release(project):
    import flask_artisan

    major, minor = map(int, flask_artisan.__version__.split(".")[:2])
    requirements = (project / "requirements.txt").read_text().splitlines()
    assert f"flask-artisan>={major}.{minor},<{major}.{minor + 1}" in requirements


def test_generated_project_events_flow(project):
    for args in (
        ("make:event", "OrderShipped"),
        ("make:listener", "LogShipment", "--event", "OrderShipped"),
    ):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    listener = project / "app/listeners/log_shipment.py"
    listener.write_text(listener.read_text().replace("        pass", '        print("SHIPPED")'))
    provider = project / "app/providers/event_service_provider.py"
    source = provider.read_text()
    assert "class EventServiceProvider" in source
    provider.write_text(
        "from app.events.order_shipped import OrderShipped\n"
        "from app.listeners.log_shipment import LogShipment\n"
        + source.replace("listen = {}", "listen = {OrderShipped: [LogShipment]}")
    )
    code = (
        "from wsgi import app\nfrom flask_artisan import Event\n"
        "from app.events.order_shipped import OrderShipped\nEvent.dispatch(OrderShipped())\n"
    )
    out = run(project, "-c", code)
    assert "SHIPPED" in out.stdout, out.stdout + out.stderr


def test_generated_env_has_mail_settings(project):
    assert "MAIL_MAILER=log" in (project / ".env").read_text().splitlines()


def test_generated_project_mail_flow(project):
    result = run(project, "-m", "flask", "make:mail", "Welcome")
    assert result.returncode == 0, result.stdout + result.stderr
    (project / "resources/views/emails/welcome.html").write_text("<p>Bienvenue {{ name }}</p>")
    mail = project / "app/mail/welcome.py"
    mail.write_text(
        mail.read_text() + "\n\nWelcome.__init__ = lambda self, name: setattr(self, 'name', name)\n"
    )
    code = (
        "from wsgi import app\nfrom flask_artisan import Mail\nfrom app.mail.welcome import Welcome\n"
        "with Mail.fake() as fake:\n    Mail.to('a@x.org').send(Welcome('A'))\n"
        "fake.assert_sent(Welcome, lambda m: m.has_to('a@x.org'))\n"
        "Mail.to('a@x.org').send(Welcome('A'))\n"
        "Mail.mailer('array').to('a@x.org').send(Welcome('A'))\n"
        "print(Mail.transport('array').messages[0].get_body(('html',)).get_content())\n"
    )
    out = run(project, "-c", code)
    assert "Bienvenue A" in out.stdout, out.stdout + out.stderr


def test_generated_env_has_queue_settings(project):
    assert "QUEUE_CONNECTION=sync" in (project / ".env").read_text().splitlines()


def test_generated_project_queue_flow(project):
    result = run(project, "-m", "flask", "make:job", "Hello")
    assert result.returncode == 0, result.stdout + result.stderr
    job = project / "app/jobs/hello.py"
    source = job.read_text()
    assert "def handle(self):" in source
    job.write_text(
        source.replace("def handle(self):", 'def handle(self):\n        print("RAN")', 1)
    )
    code = (
        "from wsgi import app\nfrom flask_artisan import Queue\nfrom app.jobs.hello import Hello\n"
        "with app.app_context():\n"
        "    Hello.dispatch()\n"
        "    with Queue.fake() as fake:\n        Hello.dispatch()\n"
        "    fake.assert_pushed(Hello)\n    print('FAKED')\n"
    )
    out = run(project, "-c", code)
    assert out.stdout.split() == ["RAN", "FAKED"], out.stdout + out.stderr


def test_generated_project_cache_settings(project):
    assert "CACHE_STORE=file" in (project / ".env").read_text().splitlines()
    assert "storage/" in (project / ".gitignore").read_text().splitlines()


def test_generated_project_cache_flow(project):
    code = (
        "from wsgi import app\nfrom flask_artisan import Cache\n"
        "with app.app_context():\n    print(Cache.remember('k', 60, lambda: 41) + 1)\n"
    )
    out = run(project, "-c", code)
    assert out.stdout.strip() == "42", out.stdout + out.stderr
    cache_dir = project / "storage" / "cache"
    assert len(list(cache_dir.iterdir())) == 1
    result = run(project, "-m", "flask", "cache:clear")
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(cache_dir.iterdir()) == []


def test_generated_project_schedule(project):
    assert "APP_TIMEZONE=UTC" in (project / ".env").read_text().splitlines()
    assert "Schedule" in (project / "routes" / "console.py").read_text()
    result = run(project, "-m", "flask", "schedule:list")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cache:prune" in result.stdout
    # À la minute 0 la tâche horaire s'exécute : seul le code de sortie est stable.
    result = run(project, "-m", "flask", "schedule:run")
    assert result.returncode == 0, result.stdout + result.stderr


STORAGE_FLOW = """
from wsgi import app
from flask_artisan import Storage
with app.app_context():
    Storage.disk("public").put("x.txt", "hi")
    assert Storage.disk().root.as_posix().endswith("storage/app/private")
r = app.test_client().get("/storage/x.txt")
assert r.status_code == 200 and r.data == b"hi", (r.status_code, r.data)
assert r.headers["X-Content-Type-Options"] == "nosniff"
print("OK")
"""


def test_generated_project_storage(project):
    assert (project / "config" / "filesystems.py").exists()
    assert "FILESYSTEM_DISK=local" in (project / ".env").read_text().splitlines()
    out = run(project, "-c", STORAGE_FLOW)
    assert out.stdout.strip() == "OK", out.stdout + out.stderr
    assert (project / "storage" / "app" / "public" / "x.txt").read_text() == "hi"


NOTIFICATION_FLOW = """
from wsgi import app
from app.models.user import User
from flask_artisan.notifications import Notification


class Welcome(Notification):
    def via(self, notifiable):
        return ["database"]

    def to_database(self, notifiable):
        return {"hello": notifiable.name}


with app.app_context():
    user = User.create(name="Ada", email="ada@example.org", password="secret")
    user.notify(Welcome())
    assert [n.data for n in user.unread_notifications.get()] == [{"hello": "Ada"}]
print("OK")
"""


def test_generated_project_notifications(project):
    assert (project / "app" / "notifications").is_dir()
    for args in (("make:migration", "init"), ("migrate",)):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    out = run(project, "-c", NOTIFICATION_FLOW)
    assert out.stdout.strip() == "OK", out.stdout + out.stderr


def test_generated_project_auth_install(project):
    def ok(*args):
        result = run(project, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    ok("-m", "flask", "auth:install")
    assert "skipped" in ok("-m", "pytest", "-q", "-p", "no:cacheprovider")

    user = project / "app" / "models" / "user.py"
    source = user.read_text()
    source = source.replace(
        "from flask_artisan.auth import Authenticatable, HasApiTokens",
        "from flask_artisan.auth import Authenticatable, HasApiTokens, MustVerifyEmail",
    ).replace("class User(Authenticatable,", "class User(MustVerifyEmail, Authenticatable,")
    assert "MustVerifyEmail, Authenticatable" in source
    user.write_text(source)
    assert "skipped" not in ok("-m", "pytest", "-q", "-p", "no:cacheprovider")

    ok("-m", "flask", "make:migration", "auth install")
    [migration] = (project / "database" / "migrations").glob("*auth_install*.py")
    text = migration.read_text()
    assert "password_reset_tokens" in text and "email_verified_at" in text
    ok("-m", "flask", "migrate")

    again = run(project, "-m", "flask", "auth:install")
    assert again.returncode == 1
