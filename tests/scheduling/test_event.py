from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from flask_artisan.queue import Job
from flask_artisan.scheduling import Event

UTC = ZoneInfo("UTC")


class SEReport(Job):
    def handle(self):
        pass


def report():
    pass


def call():
    return Event("call", report)


@pytest.mark.parametrize(
    ("build", "expression"),
    [
        (lambda e: e, "* * * * *"),
        (lambda e: e.cron("5 4 * * 1"), "5 4 * * 1"),
        (lambda e: e.every_minute(), "* * * * *"),
        (lambda e: e.every_two_minutes(), "*/2 * * * *"),
        (lambda e: e.every_five_minutes(), "*/5 * * * *"),
        (lambda e: e.every_ten_minutes(), "*/10 * * * *"),
        (lambda e: e.every_fifteen_minutes(), "*/15 * * * *"),
        (lambda e: e.every_thirty_minutes(), "*/30 * * * *"),
        (lambda e: e.hourly(), "0 * * * *"),
        (lambda e: e.hourly_at(17), "17 * * * *"),
        (lambda e: e.daily(), "0 0 * * *"),
        (lambda e: e.daily_at("08:05"), "5 8 * * *"),
        (lambda e: e.weekly(), "0 0 * * 0"),
        (lambda e: e.weekly_on(1, "09:30"), "30 9 * * 1"),
        (lambda e: e.weekly_on(5), "0 0 * * 5"),
        (lambda e: e.monthly(), "0 0 1 * *"),
        (lambda e: e.monthly_on(15, "10:00"), "0 10 15 * *"),
        (lambda e: e.every_five_minutes().weekdays(), "*/5 * * * 1-5"),
        (lambda e: e.daily().weekends(), "0 0 * * 0,6"),
    ],
)
def test_frequency_expressions(build, expression):
    event = call()
    assert build(event) is event
    assert event.expression == expression


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("daily_at", ("25:00",)),
        ("daily_at", ("8h",)),
        ("daily_at", ("08:60",)),
        ("weekly_on", (7,)),
        ("hourly_at", (60,)),
        ("monthly_on", (0,)),
        ("monthly_on", (32,)),
        ("cron", ("bad",)),
    ],
)
def test_invalid_frequency_arguments(method, args):
    with pytest.raises(ValueError) as info:
        getattr(call(), method)(*args)
    assert method in str(info.value)


def test_unknown_timezone_raises():
    with pytest.raises(ValueError, match="timezone"):
        call().timezone("Mars/Base")


def test_is_due_uses_event_timezone():
    event = call().daily_at("08:00").timezone("Europe/Paris")
    assert event.is_due(datetime(2026, 11, 27, 7, 0, tzinfo=UTC), "UTC")
    assert not event.is_due(datetime(2026, 11, 27, 8, 0, tzinfo=UTC), "UTC")


def test_is_due_uses_default_timezone():
    event = call().daily_at("08:00")
    assert event.is_due(datetime(2026, 11, 27, 7, 0, tzinfo=UTC), "Europe/Paris")
    assert not event.is_due(datetime(2026, 11, 27, 8, 0, tzinfo=UTC), "Europe/Paris")


def test_is_due_ignores_seconds():
    event = call().daily_at("08:00")
    assert event.is_due(datetime(2026, 11, 27, 8, 0, 59, tzinfo=UTC), "UTC")


def test_dst_gap_skips_without_error():
    event = call().daily_at("02:30").timezone("Europe/Paris")
    start = datetime(2026, 3, 29, 0, 0, tzinfo=UTC)
    assert not any(event.is_due(start + timedelta(minutes=m), "UTC") for m in range(180))


def test_description_defaults():
    assert Event("command", "emails:send --force").description == "emails:send --force"
    assert Event("job", SEReport()).description == f"{__name__}.SEReport"
    assert call().description == "report"
    assert call().name("Rapport").description == "Rapport"


@pytest.mark.parametrize("method", ["without_overlapping", "on_one_server"])
def test_lambda_lock_without_name_raises(method):
    with pytest.raises(ValueError, match=method):
        getattr(Event("call", lambda: None), method)()
    getattr(Event("call", lambda: None).name("x"), method)()


def test_lock_options_recorded():
    event = call().without_overlapping(10).on_one_server()
    assert event.overlap_minutes == 10
    assert event.one_server is True
    plain = call()
    assert plain.overlap_minutes is None
    assert plain.one_server is False
