import pytest
from conftest import project_modules

from flask_artisan.application import Application

HELLO = """
import click
from flask import current_app

from flask_artisan import config


@click.command("app:hello")
def hello():
    click.echo(config("app.name"))


@click.command("app:ctx")
def ctx():
    click.echo("ctx=" + current_app.name)


def helper():
    return 1


LIMIT = 3
"""


@pytest.fixture
def project(make_project):
    root = make_project()
    commands = root / "app" / "console" / "commands"
    commands.mkdir(parents=True)
    for folder in (root / "app", root / "app" / "console", commands):
        (folder / "__init__.py").touch()
    (commands / "hello.py").write_text(HELLO)
    with project_modules(root):
        yield root


def runner(root):
    app = Application(root)
    return app, lambda *args: app.test_cli_runner().invoke(args=list(args))


def test_project_command_runs(project):
    _, run = runner(project)
    result = run("app:hello")
    assert result.exit_code == 0, result.output
    assert "Blog" in result.output


def test_project_command_has_app_context(project):
    app, run = runner(project)
    result = run("app:ctx")
    assert result.exit_code == 0, result.output
    assert f"ctx={app.name}" in result.output


def test_listed_in_help(project):
    _, run = runner(project)
    result = run("--help")
    assert result.exit_code == 0, result.output
    assert "app:hello" in result.output
    assert "make:controller" in result.output


def test_non_command_values_ignored(project):
    app, run = runner(project)
    run("--help")
    names = set(app.cli.commands)
    assert {"app:hello", "app:ctx"} <= names
    assert "helper" not in names and "LIMIT" not in names


def test_broken_command_file_does_not_break_app(project):
    (project / "app" / "console" / "commands" / "broken.py").write_text(
        "raise RuntimeError('boom')\n"
    )
    app, run = runner(project)
    assert app.test_client().get("/").status_code == 404
    result = run("--help")
    assert result.exit_code != 0
    assert "app/console/commands/broken.py" in result.output
    assert "boom" in result.output


def test_missing_folder_is_fine(make_project):
    _, run = runner(make_project())
    assert run("--help").exit_code == 0


def test_callbacks_wrapped_once_across_apps(project):
    first, run = runner(project)
    run("app:hello")
    callback = first.cli.commands["app:hello"].callback
    for _ in range(3):
        app, run = runner(project)
        assert run("app:hello").exit_code == 0
        assert app.cli.commands["app:hello"].callback is callback


def test_imported_commands_are_not_reregistered(project):
    from flask_artisan.console import make_model

    callback = make_model.callback
    (project / "app" / "console" / "commands" / "reuse.py").write_text(
        "from flask_artisan.console import make_model  # noqa: F401\n"
    )
    app, run = runner(project)
    assert run("--help").exit_code == 0
    assert app.cli.commands["make:model"] is make_model
    assert make_model.callback is callback


def test_framework_commands_work_with_broken_project_file(project):
    (project / "app" / "console" / "commands" / "broken.py").write_text(
        "raise RuntimeError('boom')\n"
    )
    _, run = runner(project)
    result = run("make:controller", "PhotoController")
    assert result.exit_code == 0, result.output


def test_failed_discovery_is_retried(project):
    broken = project / "app" / "console" / "commands" / "broken.py"
    broken.write_text("raise RuntimeError('boom')\n")
    _, run = runner(project)
    assert "boom" in run("app:hello").output
    assert "boom" in run("app:hello").output
    broken.unlink()
    assert run("app:hello").exit_code == 0
