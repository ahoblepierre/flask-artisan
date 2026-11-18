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
