"""Tâches planifiées : `Schedule` (façade `Schedule`), `flask schedule:run|work|list`."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# (minimum, maximum) de chaque champ : minute, heure, jour du mois, mois, jour de semaine.
_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


class CronExpression:
    """Une expression cron à 5 champs ; `matches` teste une minute en heure locale."""

    def __init__(self, expression: str):
        self.expression = expression
        parts = expression.split() if isinstance(expression, str) else []
        if len(parts) != 5:
            raise ValueError(f"Expression cron invalide : {expression!r} (5 champs attendus).")
        try:
            fields = [_parse(part, *bounds) for part, bounds in zip(parts, _FIELDS, strict=True)]
        except ValueError as exc:
            raise ValueError(f"Expression cron invalide : {expression!r} ({exc}).") from None
        fields[4] = frozenset(0 if day == 7 else day for day in fields[4])
        self._minutes, self._hours, self._days, self._months, self._weekdays = fields
        self._any_day = parts[2] == "*"
        self._any_weekday = parts[4] == "*"

    def matches(self, moment: datetime) -> bool:
        if moment.minute not in self._minutes or moment.hour not in self._hours:
            return False
        return moment.month in self._months and self.matches_day(moment)

    def matches_day(self, moment) -> bool:
        day = moment.day in self._days
        weekday = (moment.isoweekday() % 7) in self._weekdays
        # Règle du cron classique : jour du mois et jour de semaine restreints -> l'un ou l'autre.
        if self._any_day or self._any_weekday:
            return day and weekday
        return day or weekday

    def matches_hour(self, moment) -> bool:
        return moment.hour in self._hours

    def matches_month(self, moment) -> bool:
        return moment.month in self._months


def _parse(part: str, low: int, high: int) -> frozenset:
    values = set()
    for item in part.split(","):
        span, _, step_text = item.partition("/")
        step = _number(step_text, 1, None) if step_text else 1
        if span == "*":
            start, end = low, high
        elif "-" in span:
            first, _, last = span.partition("-")
            start, end = _number(first, low, high), _number(last, low, high)
            if start > end:
                raise ValueError(f"intervalle {span!r} inversé")
        else:
            start = _number(span, low, high)
            end = high if step_text else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


def _number(text: str, low: int, high: int | None) -> int:
    if not text.isdigit() or not text.isascii():
        raise ValueError(f"valeur {text!r} invalide")
    value = int(text)
    if value < low or (high is not None and value > high):
        raise ValueError(f"valeur {value} hors de [{low}, {high}]")
    return value


def zone(name: str, origin: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError(f"{origin} : fuseau horaire inconnu {name!r}.") from None


class Event:
    """Une tâche planifiée. Les méthodes de fréquence renvoient la tâche, pour enchaîner."""

    def __init__(self, kind: str, target, args=(), kwargs=None):
        self.kind = kind
        self.target = target
        self.args = tuple(args)
        self.kwargs = dict(kwargs or {})
        self.queue = None
        self.connection = None
        self.expression = "* * * * *"
        self.tz: str | None = None
        self.overlap_minutes: int | None = None
        self.one_server = False
        self._name: str | None = None
        self._cron = CronExpression(self.expression)

    # Fréquences

    def cron(self, expression: str) -> "Event":
        try:
            self._cron = CronExpression(expression)
        except ValueError as exc:
            raise ValueError(f"cron : {exc}") from None
        self.expression = expression
        return self

    def every_minute(self):
        return self.cron("* * * * *")

    def every_two_minutes(self):
        return self.cron("*/2 * * * *")

    def every_five_minutes(self):
        return self.cron("*/5 * * * *")

    def every_ten_minutes(self):
        return self.cron("*/10 * * * *")

    def every_fifteen_minutes(self):
        return self.cron("*/15 * * * *")

    def every_thirty_minutes(self):
        return self.cron("*/30 * * * *")

    def hourly(self):
        return self.cron("0 * * * *")

    def hourly_at(self, minute: int):
        _check(minute, 0, 59, "hourly_at", "minute")
        return self.cron(f"{minute} * * * *")

    def daily(self):
        return self.cron("0 0 * * *")

    def daily_at(self, time: str):
        hour, minute = _time(time, "daily_at")
        return self.cron(f"{minute} {hour} * * *")

    def weekly(self):
        return self.cron("0 0 * * 0")

    def weekly_on(self, day: int, time: str = "00:00"):
        _check(day, 0, 6, "weekly_on", "jour (0 = dimanche)")
        hour, minute = _time(time, "weekly_on")
        return self.cron(f"{minute} {hour} * * {day}")

    def monthly(self):
        return self.cron("0 0 1 * *")

    def monthly_on(self, day: int = 1, time: str = "00:00"):
        _check(day, 1, 31, "monthly_on", "jour")
        hour, minute = _time(time, "monthly_on")
        return self.cron(f"{minute} {hour} {day} * *")

    def weekdays(self):
        return self._weekday_field("1-5")

    def weekends(self):
        return self._weekday_field("0,6")

    def _weekday_field(self, value: str):
        return self.cron(" ".join([*self.expression.split()[:4], value]))

    # Options

    def timezone(self, name: str) -> "Event":
        zone(name, "timezone")
        self.tz = name
        return self

    def name(self, text: str) -> "Event":
        self._name = text
        return self

    def without_overlapping(self, minutes: int = 1440) -> "Event":
        self._require_name("without_overlapping")
        _check(minutes, 1, None, "without_overlapping", "minutes")
        self.overlap_minutes = minutes
        return self

    def on_one_server(self) -> "Event":
        self._require_name("on_one_server")
        self.one_server = True
        return self

    def _require_name(self, method: str) -> None:
        qualname = getattr(self.target, "__qualname__", "")
        if self.kind == "call" and self._name is None and "<" in qualname:
            # Toutes les lambdas ont le même nom : elles partageraient le même verrou.
            raise ValueError(
                f"{method} : appelez name(...) avant, pour une lambda ou une fonction locale."
            )

    @property
    def description(self) -> str:
        if self._name is not None:
            return self._name
        if self.kind == "command":
            return self.target if isinstance(self.target, str) else " ".join(self.args)
        if self.kind == "job":
            cls = type(self.target)
            return f"{cls.__module__}.{cls.__qualname__}"
        return getattr(self.target, "__qualname__", repr(self.target))

    def is_due(self, now: datetime, default_tz: str) -> bool:
        local = now.astimezone(zone(self.tz or default_tz, "timezone"))
        return self._cron.matches(local.replace(second=0, microsecond=0, tzinfo=None))


def _check(value, low: int, high: int | None, method: str, label: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < low
        or (high is not None and value > high)
    ):
        bounds = f"entre {low} et {high}" if high is not None else f">= {low}"
        raise ValueError(f"{method} : {label} doit être un entier {bounds}, reçu {value!r}.")


def _time(text: str, method: str) -> tuple[int, int]:
    match = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})", text) if isinstance(text, str) else None
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f"{method} : heure {text!r} invalide (format HH:MM).")
    return int(match[1]), int(match[2])
