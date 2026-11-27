"""Tâches planifiées : `Schedule` (façade `Schedule`), `flask schedule:run|work|list`."""

import hashlib
import importlib.util
import inspect
import re
import shlex
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import click
from flask import current_app
from flask.cli import with_appcontext

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

    def lock_id(self, default_tz: str) -> str:
        key = self.expression + (self.tz or default_tz) + self.description
        return hashlib.sha1(key.encode()).hexdigest()

    def next_run(self, after: datetime, default_tz: str) -> datetime | None:
        """Prochaine minute due, strictement après `after`, dans le fuseau de la tâche ; None
        au-delà de 366 jours."""
        tz = zone(self.tz or default_tz, "timezone")
        cron = self._cron
        start = after.astimezone(tz).replace(second=0, microsecond=0, tzinfo=None)
        moment = start + timedelta(minutes=1)
        limit = start + timedelta(days=366)
        while moment <= limit:
            if not (cron.matches_month(moment) and cron.matches_day(moment)):
                moment = (moment + timedelta(days=1)).replace(hour=0, minute=0)
            elif not cron.matches_hour(moment):
                moment = (moment + timedelta(hours=1)).replace(minute=0)
            elif not cron.matches(moment):
                moment += timedelta(minutes=1)
            else:
                local = moment.replace(tzinfo=tz)
                # Heure inexistante (passage à l'heure d'été) : l'aller-retour UTC la décale.
                if local.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == moment:
                    return local
                moment += timedelta(minutes=1)
        return None

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


class Schedule:
    """Le registre des tâches (`"schedule"`, façade `Schedule`), rempli par routes/console.py."""

    def __init__(self, app):
        self._app = app
        self._events: list[Event] = []

    def command(self, name: str) -> Event:
        return self._add(Event("command", name, args=shlex.split(name)))

    def job(self, job, queue: str | None = None, connection: str | None = None) -> Event:
        event = Event("job", job)
        event.queue, event.connection = queue, connection
        return self._add(event)

    def call(self, fn, *args, **kwargs) -> Event:
        return self._add(Event("call", fn, args, kwargs))

    def _add(self, event: Event) -> Event:
        self._events.append(event)
        return event

    def events(self) -> list[Event]:
        return list(self._events)

    def timezone(self) -> str:
        name = self._app.make("config").get("app.timezone", "UTC")
        zone(name, "APP_TIMEZONE (config app.timezone)")
        return name

    def due_events(self, now: datetime) -> list[Event]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("due_events attend un datetime avec fuseau (tzinfo).")
        default = self.timezone()
        return [event for event in self._events if event.is_due(now, default)]

    def load(self, path: Path) -> None:
        """Vide le registre puis exécute routes/console.py ; un fichier absent est ignoré."""
        self._events = []
        self.timezone()  # APP_TIMEZONE invalide : détecté au chargement, pas une minute plus tard
        path = Path(path)
        if not path.exists():
            return
        spec = importlib.util.spec_from_file_location("flask_artisan_schedule_console", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise click.ClickException(f"Erreur dans {path} : {exc}") from exc
        self._check_lock_names()

    def _check_lock_names(self) -> None:
        """Deux tâches verrouillées au même identifiant se bloqueraient : l'une serait sautée."""
        default = self.timezone()
        seen = set()
        for event in self._events:
            if event.overlap_minutes is None and not event.one_server:
                continue
            ident = event.lock_id(default)
            if ident in seen:
                raise click.ClickException(
                    f"Deux tâches verrouillées portent le nom {event.description!r} avec la même "
                    "fréquence : donnez-leur un nom différent avec name(...)."
                )
            seen.add(ident)

    def run_due(self, now: datetime, echo) -> bool:
        """Exécute les tâches dues à `now`, l'une après l'autre ; False si une a échoué."""
        due = self.due_events(now)
        if not due:
            echo("Aucune tâche planifiée à exécuter.")
            return True
        default = self.timezone()
        ok = True
        for event in due:
            ok = self._run(event, now, default, echo) and ok
        return ok

    def _run(self, event: Event, now: datetime, default_tz: str, echo) -> bool:
        lock = None
        try:
            cache = self._app.make("cache")
            ident = event.lock_id(default_tz)
            if event.one_server:
                minute = now.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
                # Jamais libéré : le premier serveur qui le prend exécute la tâche cette minute.
                if not cache.lock(f"schedule:{ident}:{minute}", 3600).get():
                    echo(f"Sautée (autre serveur) : {event.description}")
                    return True
            if event.overlap_minutes is not None:
                candidate = cache.lock(f"schedule:{ident}", event.overlap_minutes * 60)
                if not candidate.get():
                    echo(f"Sautée (déjà en cours) : {event.description}")
                    return True
                lock = candidate
            echo(f"Exécution : {event.description}")
            # Un contexte par tâche, comme un job du worker : sa fin retire la session.
            with self._app.app_context():
                self._execute(event)
        # Une tâche en échec (verrou injoignable, sys.exit compris) n'arrête pas les suivantes.
        except (Exception, SystemExit):  # noqa: BLE001
            click.echo(traceback.format_exc(), err=True)
            return False
        finally:
            if lock is not None:
                try:
                    lock.release()
                except Exception:  # noqa: BLE001 — le TTL libérera le verrou
                    click.echo(traceback.format_exc(), err=True)
        echo("OK")
        return True

    def _execute(self, event: Event) -> None:
        if event.kind == "command":
            try:
                code = self._app.cli.main(
                    args=list(event.args), prog_name="flask", standalone_mode=False
                )
            except SystemExit as exc:
                code = exc.code
            except click.ClickException as exc:
                raise RuntimeError(f"{event.description} : {exc.format_message()}") from None
            # Comme Python : None et 0 réussissent, un autre entier ou un message échoue.
            # main() renvoie aussi le code d'un click Exit ; il ne distingue pas un `return 3`.
            if (isinstance(code, int) and code != 0) or isinstance(code, str):
                raise RuntimeError(f"{event.description} : code de sortie {code!r}")
        elif event.kind == "job":
            job = event.target.on_queue(event.queue) if event.queue else event.target
            queue = self._app.make("queue")
            (queue.connection(event.connection) if event.connection else queue).push(job)
        else:
            # Positionnels nommés d'après la signature : le conteneur injecte le reste.
            named = inspect.signature(event.target).bind_partial(*event.args).arguments
            self._app.call(event.target, **named, **event.kwargs)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _schedule():
    schedule = current_app.make("schedule")
    try:
        schedule.load(current_app.base_path("routes/console.py"))
    except ValueError as exc:  # APP_TIMEZONE invalide : un message, pas une trace
        raise click.ClickException(str(exc)) from None
    return schedule


@click.command("schedule:run")
@with_appcontext
def schedule_run():
    """Exécute les tâches planifiées dues à cette minute (à lancer par cron chaque minute)."""
    if not _schedule().run_due(_now(), click.echo):
        raise SystemExit(1)


@click.command("schedule:work")
@with_appcontext
def schedule_work():
    """Exécute les tâches dues chaque minute, sans cron (Ctrl+C pour arrêter)."""
    app = current_app._get_current_object()
    schedule = _schedule()
    click.echo("Planificateur démarré (Ctrl+C pour arrêter).")
    try:
        while True:
            now = _now()
            _sleep(60 - now.second - now.microsecond / 1_000_000)
            # Un contexte neuf par minute : sa fin retire la session de base de données.
            with app.app_context():
                schedule.run_due(_now(), click.echo)
    except KeyboardInterrupt:
        click.echo("Planificateur arrêté.")


@click.command("schedule:list")
@with_appcontext
def schedule_list():
    """Liste les tâches planifiées et leur prochaine exécution."""
    schedule = _schedule()
    events = schedule.events()
    if not events:
        click.echo("Aucune tâche planifiée.")
        return
    default, now = schedule.timezone(), _now()
    rows = [("Expression", "Prochaine exécution", "Tâche")]
    for event in events:
        upcoming = event.next_run(now, default)
        shown = f"{upcoming:%Y-%m-%d %H:%M} ({event.tz or default})" if upcoming else "—"
        rows.append((event.expression, shown, event.description))
    widths = [max(len(row[i]) for row in rows) for i in range(2)]
    for expression, shown, name in rows:
        click.echo(f"{expression.ljust(widths[0])}   {shown.ljust(widths[1])}   {name}")


COMMANDS = [schedule_run, schedule_work, schedule_list]
