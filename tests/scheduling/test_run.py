import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

import click
import pytest
from conftest import project_modules

from flask_artisan import Cache, Queue, scheduling

NOW = datetime(2026, 11, 27, 8, 0, tzinfo=ZoneInfo("UTC"))

HEADER = """
from pathlib import Path

from flask_artisan import Schedule
from flask_artisan.application import Application

LOG = Path(__file__).parent / "log.txt"


def log(text):
    with LOG.open("a") as f:
        f.write(text + "\\n")
"""

COMMANDS = """
import sys

import click


@click.command("app:hello")
def hello():
    click.echo("hello from command")


@click.command("app:exit2")
def exit2():
    sys.exit(2)
"""


@pytest.fixture
def run(scheduled, monkeypatch):
    """Écrit le planning, puis renvoie (app, invoke) ; `invoke()` lance schedule:run à NOW."""
    state = {"now": NOW}
    monkeypatch.setattr(scheduling, "_now", lambda: state["now"])

    def _make(source: str):
        app = scheduled(HEADER + source)
        app.make("config").set(
            "cache", {"default": "array", "stores": {"array": {"driver": "array"}}}
        )

        def invoke(now=None):
            state["now"] = now or NOW
            return app.test_cli_runner().invoke(args=["schedule:run"])

        return app, invoke

    return _make


def logged(app):
    path = app.base_path("routes/log.txt")
    return path.read_text().splitlines() if path.exists() else []


def lock_id(expression, tz, name):
    return hashlib.sha1((expression + tz + name).encode()).hexdigest()


def test_runs_due_call_with_injection(run):
    app, invoke = run(
        """
def report(app: Application):
    log("report " + app.name)

Schedule.call(report).daily_at("08:00")
"""
    )
    result = invoke()
    assert result.exit_code == 0, result.output
    assert "Exécution : report" in result.output
    assert logged(app) == [f"report {app.name}"]


def test_call_passes_arguments(run):
    app, invoke = run(
        """
def greet(word, app: Application, punct="."):
    log(word + punct)

Schedule.call(greet, "bonjour", punct="!")
"""
    )
    result = invoke()
    assert result.exit_code == 0, result.output
    assert logged(app) == ["bonjour!"]


def test_skips_not_due(run):
    app, invoke = run('Schedule.call(lambda: log("x")).daily_at("09:00")\n')
    result = invoke()
    assert logged(app) == []
    assert "Aucune tâche planifiée à exécuter." in result.output


def test_nothing_due_message(run):
    _, invoke = run("")
    result = invoke()
    assert result.exit_code == 0
    assert "Aucune tâche planifiée à exécuter." in result.output


@pytest.fixture
def with_commands(run):
    def _make(source):
        app, invoke = run(source)
        root = app.base_path()
        commands = root / "app" / "console" / "commands"
        commands.mkdir(parents=True)
        for folder in (root / "app", root / "app" / "console", commands):
            (folder / "__init__.py").touch()
        (commands / "tools.py").write_text(COMMANDS)
        return app, invoke

    return _make


def test_runs_command_in_process(with_commands):
    app, invoke = with_commands('Schedule.command("app:hello")\n')
    with project_modules(app.base_path()):
        result = invoke()
    assert result.exit_code == 0, result.output
    assert "hello from command" in result.output


def test_command_nonzero_exit_is_failure(with_commands):
    app, invoke = with_commands(
        'Schedule.command("app:exit2")\nSchedule.call(lambda: log("after"))\n'
    )
    with project_modules(app.base_path()):
        result = invoke()
    assert result.exit_code == 1, result.output
    assert logged(app) == ["after"]


def test_unknown_command_is_failure(run):
    app, invoke = run('Schedule.command("nope:nope")\nSchedule.call(lambda: log("after"))\n')
    result = invoke()
    assert result.exit_code == 1
    assert "nope:nope" in result.stderr
    assert logged(app) == ["after"]


def test_exception_isolated(run):
    app, invoke = run(
        """
def boom():
    raise RuntimeError("kaboom")

Schedule.call(boom)
Schedule.call(lambda: log("second"))
"""
    )
    result = invoke()
    assert result.exit_code == 1
    assert "kaboom" in result.stderr
    assert "Traceback" in result.stderr
    assert logged(app) == ["second"]


def test_job_is_pushed(run):
    app, invoke = run(
        """
from flask_artisan.queue import Job

class SRMail(Job):
    def handle(self):
        log("handled")

Schedule.job(SRMail(), queue="emails")
"""
    )
    with app.app_context():
        fake = Queue.fake()
    result = invoke()
    assert result.exit_code == 0, result.output
    assert [queue for _, queue in fake._recorded] == ["emails"]
    assert logged(app) == []


def test_job_runs_with_sync_connection(run):
    app, invoke = run(
        """
from scheduling.jobs import SRSync

Schedule.job(SRSync(), connection="sync")
"""
    )
    result = invoke()
    assert result.exit_code == 0, result.output
    assert logged(app) == ["handled"]


def test_without_overlapping_skips_when_locked(run):
    app, invoke = run(
        """
def job():
    log("ran")

Schedule.call(job).name("nettoyage").without_overlapping()
"""
    )
    with app.app_context():
        assert Cache.lock("schedule:" + lock_id("* * * * *", "UTC", "nettoyage"), 60).get()
    result = invoke()
    assert "Sautée (déjà en cours) : nettoyage" in result.output
    assert logged(app) == []


def test_without_overlapping_releases_after_failure(run):
    app, invoke = run(
        """
def boom():
    raise RuntimeError("x")

Schedule.call(boom).without_overlapping()
"""
    )
    assert invoke().exit_code == 1
    with app.app_context():
        assert Cache.lock("schedule:" + lock_id("* * * * *", "UTC", "boom"), 60).get()


def test_on_one_server_runs_once_per_minute(run):
    app, invoke = run(
        """
def job():
    log("ran")

Schedule.call(job).on_one_server()
"""
    )
    invoke()
    invoke()
    assert logged(app) == ["ran"]
    invoke(NOW.replace(minute=1))
    assert logged(app) == ["ran", "ran"]


def test_same_lock_name_twice_is_rejected(run):
    with pytest.raises(click.ClickException, match=r"'send'.*name\("):
        run(
            """
def send(who):
    log(who)

Schedule.call(send, "alice").hourly().on_one_server()
Schedule.call(send, "bob").hourly().on_one_server()
"""
        )


def test_same_name_without_lock_is_allowed(run):
    app, invoke = run(
        """
def send(who):
    log(who)

Schedule.call(send, "alice")
Schedule.call(send, "bob")
"""
    )
    assert invoke().exit_code == 0
    assert logged(app) == ["alice", "bob"]


def test_lock_store_failure_only_fails_that_task(run, monkeypatch):
    app, invoke = run(
        """
def locked():
    log("locked")

Schedule.call(locked).without_overlapping()
Schedule.call(lambda: log("free"))
"""
    )

    def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(type(app.make("cache")), "lock", broken, raising=False)
    result = invoke()
    assert result.exit_code == 1
    assert "redis down" in result.stderr
    assert logged(app) == ["free"]


def test_each_task_gets_its_own_app_context(run):
    app, invoke = run(
        """
from flask import g

def first():
    g.leak = "first"
    raise RuntimeError("x")

def second():
    log(getattr(g, "leak", "clean"))

Schedule.call(first)
Schedule.call(second)
"""
    )
    torn = []
    app.teardown_appcontext(lambda exc: torn.append(1))
    invoke()
    assert logged(app) == ["clean"]
    assert len(torn) >= 2


@pytest.mark.parametrize(("code", "ok"), [(None, True), (0, True), (3, False), ("fatal", False)])
def test_command_system_exit_codes(with_commands, code, ok):
    app, invoke = with_commands(
        "Schedule.command('app:code')\nSchedule.call(lambda: log('after'))\n"
    )
    tools = app.base_path("app/console/commands/tools.py")
    tools.write_text(
        tools.read_text() + f"\n\n@click.command('app:code')\ndef code():\n    sys.exit({code!r})\n"
    )
    with project_modules(app.base_path()):
        result = invoke()
    assert result.exit_code == (0 if ok else 1), result.output
    assert logged(app) == ["after"]


def test_system_exit_in_call_does_not_stop_others(run):
    app, invoke = run(
        """
import sys

Schedule.call(lambda: sys.exit(1)).name("quit")
Schedule.call(lambda: log("after"))
"""
    )
    result = invoke()
    assert result.exit_code == 1
    assert logged(app) == ["after"]
