import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from flask_artisan import scheduling
from flask_artisan.scheduling import Event

UTC = ZoneInfo("UTC")
NOW = datetime(2026, 11, 27, 8, 0, tzinfo=UTC)


def report():
    pass


def event():
    return Event("call", report)


def test_next_run():
    assert event().daily_at("08:00").next_run(NOW, "UTC") == datetime(
        2026, 11, 28, 8, 0, tzinfo=UTC
    )
    assert event().weekly_on(1, "09:00").next_run(NOW, "UTC") == datetime(
        2026, 11, 30, 9, 0, tzinfo=UTC
    )
    assert event().every_minute().next_run(NOW, "UTC") == datetime(2026, 11, 27, 8, 1, tzinfo=UTC)
    assert event().cron("0 0 31 2 *").next_run(NOW, "UTC") is None


def test_next_run_in_event_timezone():
    paris = ZoneInfo("Europe/Paris")
    result = event().daily_at("08:00").timezone("Europe/Paris").next_run(NOW, "UTC")
    assert result == datetime(2026, 11, 28, 8, 0, tzinfo=paris)
    assert result.tzinfo == paris


def test_next_run_skips_dst_gap():
    start = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
    result = event().daily_at("02:30").timezone("Europe/Paris").next_run(start, "UTC")
    assert result.replace(tzinfo=None) == datetime(2026, 3, 30, 2, 30)


def test_next_run_is_fast():
    started = time.perf_counter()
    assert event().cron("0 0 29 2 *").next_run(NOW, "UTC") is None
    assert time.perf_counter() - started < 0.5


@pytest.fixture
def cli(scheduled, monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr(scheduling, "_now", lambda: state["now"])

    def _make(source: str):
        app = scheduled(source)
        return app, state, lambda *args: app.test_cli_runner().invoke(args=list(args))

    return _make


def test_list_shows_table(cli):
    _, _, invoke = cli(
        """
        from flask_artisan import Schedule
        Schedule.command("emails:send").daily_at("08:00")
        Schedule.command("never").cron("0 0 31 2 *")
        """
    )
    result = invoke("schedule:list")
    assert result.exit_code == 0, result.output
    for text in ("Expression", "Prochaine exécution", "Tâche", "0 8 * * *", "emails:send"):
        assert text in result.output
    assert "2026-11-28 08:00" in result.output
    never = next(line for line in result.output.splitlines() if "never" in line)
    assert "—" in never


def test_list_empty(cli):
    _, _, invoke = cli("")
    result = invoke("schedule:list")
    assert result.exit_code == 0
    assert "Aucune tâche planifiée." in result.output


WORK = """
from flask import g

from flask_artisan import Schedule

SEEN = []


def tick():
    SEEN.append(g._get_current_object())  # gardé : un id libéré pourrait être réutilisé
    with open(__file__ + ".log", "a") as f:
        f.write(str(id(SEEN[-1])) + "\\n")


Schedule.call(tick).every_minute()
"""


def test_work_runs_each_minute_then_stops(cli, monkeypatch):
    app, state, invoke = cli(WORK)
    state["now"] = NOW + timedelta(seconds=30)
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt
        state["now"] = state["now"].replace(second=0) + timedelta(minutes=1)

    monkeypatch.setattr(scheduling, "_sleep", fake_sleep)
    result = invoke("schedule:work")
    assert result.exit_code == 0, result.output
    log = app.base_path("routes/console.py.log").read_text().split()
    assert len(log) == 2
    assert sleeps[0] == 30
    assert all(0 < s <= 60 for s in sleeps)
    assert log[0] != log[1]  # un contexte d'application neuf par minute


def test_next_run_visits_repeated_hour():
    paris = event().every_fifteen_minutes().timezone("Europe/Paris")
    # 00:50 UTC = 02:50 heure d'été ; à 01:00 UTC, il est 02:00 heure d'hiver (heure doublée).
    first = paris.next_run(datetime(2026, 10, 25, 0, 50, tzinfo=UTC), "UTC")
    assert first.astimezone(UTC) == datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
    second = paris.next_run(datetime(2026, 10, 25, 1, 5, tzinfo=UTC), "UTC")
    assert second.astimezone(UTC) == datetime(2026, 10, 25, 1, 15, tzinfo=UTC)


def test_work_does_not_replay_a_minute(cli, monkeypatch):
    app, state, invoke = cli(WORK)
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt
        # Réveil en avance : l'horloge reste dans la minute déjà traitée au 2e tour.
        if len(sleeps) == 1:
            state["now"] = NOW + timedelta(minutes=1)
        else:
            state["now"] = NOW + timedelta(minutes=1, seconds=59)

    monkeypatch.setattr(scheduling, "_sleep", fake_sleep)
    result = invoke("schedule:work")
    assert result.exit_code == 0, result.output
    assert len(app.base_path("routes/console.py.log").read_text().split()) == 1
