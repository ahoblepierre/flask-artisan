from datetime import datetime
from zoneinfo import ZoneInfo

import click
import pytest

from flask_artisan import Schedule
from flask_artisan.application import Application
from flask_artisan.queue import Job

UTC = ZoneInfo("UTC")
AT_0913 = datetime(2026, 11, 27, 9, 13, tzinfo=UTC)


class SCReport(Job):
    def handle(self):
        pass


def report():
    pass


def test_facade_registers_events(make_project):
    app = Application(make_project())
    with app.app_context():
        Schedule.call(report).daily()
        assert [e.expression for e in Schedule.events()] == ["0 0 * * *"]


def test_due_events_filters(scheduled):
    scheduled(
        """
        from flask_artisan import Schedule
        Schedule.command("a").every_minute()
        Schedule.command("b").daily_at("08:00")
        """
    )
    assert [e.description for e in Schedule.due_events(AT_0913)] == ["a"]


def test_due_events_requires_aware_datetime(scheduled):
    scheduled()
    with pytest.raises(ValueError):
        Schedule.due_events(datetime(2026, 11, 27, 9, 13))


def test_default_timezone_is_utc(scheduled):
    scheduled()
    assert Schedule.timezone() == "UTC"


def test_app_timezone_used(scheduled):
    scheduled(
        """
        from flask_artisan import Schedule
        Schedule.command("a").daily_at("08:00")
        """,
        timezone="'Europe/Paris'",
    )
    assert len(Schedule.due_events(datetime(2026, 11, 27, 7, 0, tzinfo=UTC))) == 1
    assert Schedule.due_events(datetime(2026, 11, 27, 8, 0, tzinfo=UTC)) == []


def test_invalid_app_timezone_names_env_var(scheduled):
    scheduled("from flask_artisan import Schedule\nSchedule.command('a')\n", timezone="'Nowhere/X'")
    with pytest.raises(ValueError, match="APP_TIMEZONE"):
        Schedule.due_events(AT_0913)


def test_load_runs_file_and_clears(scheduled):
    app = scheduled(
        """
        from flask_artisan import Schedule
        Schedule.command("a")
        Schedule.command("b")
        """
    )
    schedule = app.make("schedule")
    schedule.load(app.base_path("routes/console.py"))
    assert len(schedule.events()) == 2


def test_load_missing_file_is_empty(make_project):
    app = Application(make_project())
    schedule = app.make("schedule")
    schedule.load(app.base_path("routes/console.py"))
    assert schedule.events() == []


def test_load_error_names_file(make_project):
    root = make_project()
    (root / "routes").mkdir()
    (root / "routes" / "console.py").write_text("raise RuntimeError('boom')\n")
    app = Application(root)
    with pytest.raises(click.ClickException) as info:
        app.make("schedule").load(root / "routes" / "console.py")
    assert "console.py" in info.value.message
    assert "boom" in info.value.message


def test_web_app_does_not_load_console_routes(make_project):
    root = make_project()
    (root / "routes").mkdir()
    (root / "routes" / "console.py").write_text("raise RuntimeError('boom')\n")
    app = Application(root)
    assert app.test_client().get("/").status_code == 404


def test_command_is_split(scheduled):
    scheduled("from flask_artisan import Schedule\nSchedule.command('emails:send --to \"a b\"')\n")
    (event,) = Schedule.events()
    assert event.args == ("emails:send", "--to", "a b")
    assert event.description == 'emails:send --to "a b"'


def test_job_records_queue_and_connection(make_project):
    app = Application(make_project())
    with app.app_context():
        job = SCReport()
        event = Schedule.job(job, queue="emails", connection="sync")
    assert (event.kind, event.target, event.queue, event.connection) == (
        "job",
        job,
        "emails",
        "sync",
    )


def test_call_records_arguments(make_project):
    app = Application(make_project())
    with app.app_context():
        event = Schedule.call(report, 1, x=2)
    assert (event.args, event.kwargs) == ((1,), {"x": 2})
