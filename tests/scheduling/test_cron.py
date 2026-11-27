from datetime import datetime

import pytest

from flask_artisan.scheduling import CronExpression


def at(day, hour=0, minute=0, month=11):
    return datetime(2026, month, day, hour, minute)


def test_star_matches_every_minute():
    cron = CronExpression("* * * * *")
    assert cron.matches(at(27, 8, 0))
    assert cron.matches(at(28, 23, 59))


def test_exact_values():
    cron = CronExpression("30 8 * * *")
    assert cron.matches(at(27, 8, 30))
    assert not cron.matches(at(27, 8, 31))


def test_ranges_steps_lists():
    cron = CronExpression("*/15 9-17 * * 1-5")
    assert cron.matches(at(23, 9, 45))  # lundi
    assert not cron.matches(at(28, 9, 45))  # samedi
    assert not cron.matches(at(23, 18, 0))
    assert CronExpression("0,30 * * * *").matches(at(27, 3, 30))
    assert CronExpression("10-20/5 * * * *").matches(at(27, 3, 15))
    assert not CronExpression("10-20/5 * * * *").matches(at(27, 3, 12))


def test_sunday_is_zero_or_seven():
    assert CronExpression("0 0 * * 7").matches(at(29))
    assert CronExpression("0 0 * * 0").matches(at(29))
    assert not CronExpression("0 0 * * 7").matches(at(28))


def test_day_of_month_or_day_of_week():
    cron = CronExpression("0 0 13 * 5")
    assert cron.matches(at(27))  # vendredi
    assert cron.matches(at(13))  # vendredi 13
    assert cron.matches(at(13, month=12))  # dimanche 13
    assert not cron.matches(at(26))  # jeudi 26
    only_13 = CronExpression("0 0 13 * *")
    assert only_13.matches(at(13))
    assert not only_13.matches(at(27))


def test_expression_is_kept():
    assert CronExpression("5 8 * * *").expression == "5 8 * * *"


@pytest.mark.parametrize(
    "expr",
    [
        "* * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "a * * * *",
        "@daily",
        "",
    ],
)
def test_invalid_expressions(expr):
    with pytest.raises(ValueError) as info:
        CronExpression(expr)
    assert repr(expr) in str(info.value)
