# Tâches planifiées

Les tâches récurrentes (un rapport chaque matin, un nettoyage toutes les 5 minutes) se déclarent en Python dans `routes/console.py`. Sur le serveur, une seule ligne cron lance le planificateur chaque minute, et il exécute les tâches dues.

## Installer la ligne cron

```bash
* * * * * cd /chemin/du/projet && .venv/bin/flask schedule:run >> /dev/null 2>&1
```

En développement, ou dans un conteneur sans cron, `flask schedule:work` fait la même chose dans une boucle (voir [plus bas](#schedulework)).

## Déclarer les tâches

```python
# routes/console.py
from flask_artisan import Schedule
from flask_artisan.database import DatabaseManager

from app.jobs.send_report import SendReport

Schedule.command("cache:clear").daily_at("03:00")
Schedule.job(SendReport(), queue="reports").weekly_on(1, "08:00")


def prune_tokens(db: DatabaseManager):
    ...


Schedule.call(prune_tokens).hourly()
```

Trois types de tâches :

| Tâche | Ce qui s'exécute |
|-------|------------------|
| `Schedule.command("emails:send --force")` | une commande `flask` (du framework ou de `app/console/commands/`), dans le même processus |
| `Schedule.job(job, queue=None, connection=None)` | le job est **envoyé** dans la queue ; le planificateur n'attend pas sa fin |
| `Schedule.call(fn, *args, **kwargs)` | la fonction, avec l'injection du conteneur pour les paramètres annotés |

Les tâches dues s'exécutent l'une après l'autre, dans l'ordre de déclaration. Pour un travail long, utilisez `Schedule.job` : le worker s'en charge et le planificateur passe à la suite. La classe du job doit être importable (dans `app/jobs/`, par exemple), pas définie dans `routes/console.py`.

Une tâche qui échoue (exception, commande inconnue, code de sortie différent de 0) affiche sa trace sur stderr ; les tâches suivantes s'exécutent quand même, et `schedule:run` sort avec le code 1.

`routes/console.py` n'est chargé que par les commandes `schedule:*` : une erreur dans ce fichier ne bloque pas l'app web.

## Fréquences

| Méthode | Expression cron |
|---------|-----------------|
| `cron("5 4 * * 1")` | l'expression telle quelle |
| `every_minute()` | `* * * * *` |
| `every_two_minutes()`, `every_five_minutes()`, `every_ten_minutes()`, `every_fifteen_minutes()`, `every_thirty_minutes()` | `*/n * * * *` |
| `hourly()` | `0 * * * *` |
| `hourly_at(17)` | `17 * * * *` |
| `daily()` | `0 0 * * *` |
| `daily_at("08:05")` | `5 8 * * *` |
| `weekly()` | `0 0 * * 0` (dimanche) |
| `weekly_on(1, "09:30")` | `30 9 * * 1` (0 = dimanche … 6 = samedi) |
| `monthly()` | `0 0 1 * *` |
| `monthly_on(15, "10:00")` | `0 10 15 * *` |
| `weekdays()` | jours de semaine restreints à `1-5` |
| `weekends()` | jours de semaine restreints à `0,6` |

Les méthodes s'enchaînent : `Schedule.command("report").every_fifteen_minutes().weekdays()`. Sans fréquence, une tâche s'exécute chaque minute.

Les expressions cron ont 5 champs (minute, heure, jour du mois, mois, jour de semaine) et acceptent `*`, `n`, `a-b`, `*/n`, `a-b/n` et les listes `a,b`. Le jour de semaine va de 0 à 7 (0 et 7 = dimanche). Les noms (`mon`, `jan`) et les macros (`@daily`) ne sont pas acceptés. Comme dans cron, si le jour du mois **et** le jour de semaine sont restreints, la tâche est due quand l'un **ou** l'autre correspond.

Un argument invalide (`daily_at("25:00")`, `weekly_on(7)`, une expression mal formée) lève `ValueError` dès la déclaration.

## Fuseau horaire

Les heures s'entendent dans le fuseau de `APP_TIMEZONE` (`config/app.py`, clé `timezone`, `UTC` par défaut) :

```bash
APP_TIMEZONE=Europe/Paris
```

Une tâche peut avoir son propre fuseau :

```python
Schedule.command("report").daily_at("08:00").timezone("America/New_York")
```

Au changement d'heure, le planificateur se comporte comme cron : une heure qui n'existe pas (passage à l'heure d'été, 2 h 30 un dimanche de mars à Paris) est sautée, et une heure qui existe deux fois (passage à l'heure d'hiver) peut lancer la tâche deux fois. Pour une tâche qui ne doit jamais sauter, choisissez une heure hors de cette plage, ou `UTC`.

## Éviter les doubles exécutions

```python
Schedule.call(prune_tokens).hourly().without_overlapping()
Schedule.command("report").daily_at("08:00").on_one_server()
```

- `without_overlapping(minutes=1440)` : si l'exécution précédente tourne encore, la tâche est sautée (`Sautée (déjà en cours) : …`). Le verrou est libéré à la fin, même en cas d'échec ; `minutes` est sa durée maximale si le processus meurt.
- `on_one_server()` : sur plusieurs serveurs qui lancent tous `schedule:run`, un seul exécute la tâche pour une minute donnée. Les autres affichent `Sautée (autre serveur) : …`.

Les deux reposent sur les [verrous](limitation-de-debit.md#verrous) du store de cache par défaut. `on_one_server` n'a de sens qu'avec un store partagé entre les serveurs, donc `redis` (voir [Quel store choisir](limitation-de-debit.md#quel-store-choisir)).

Pour un job, `without_overlapping` couvre l'envoi dans la queue, pas l'exécution par le worker.

Une lambda ou une fonction locale doit recevoir un nom avant ces deux méthodes, sinon toutes les lambdas partageraient le même verrou :

```python
Schedule.call(lambda: ...).name("purge").without_overlapping()
```

## `schedule:work`

```bash
flask schedule:work
```

La commande attend le début de chaque minute, exécute les tâches dues, et recommence jusqu'à Ctrl+C. Si une tâche dure plus d'une minute, les minutes manquées ne sont pas rattrapées : pour un travail long, utilisez `Schedule.job`.

## `schedule:list`

```bash
flask schedule:list
```

```
Expression   Prochaine exécution      Tâche
0 3 * * *    2026-11-28 03:00 (UTC)   cache:clear
0 8 * * 1    2026-11-30 08:00 (UTC)   app.jobs.send_report.SendReport
```

La colonne « Tâche » montre le nom donné par `name("…")`, sinon la commande, la classe du job ou le nom de la fonction. Une tâche qui ne tombe jamais dans l'année (`0 0 31 2 *`) affiche `—`.

## Tester

`Schedule.due_events(moment)` renvoie les tâches dues à un instant donné (un `datetime` avec fuseau) :

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_artisan import Schedule


def test_report_runs_monday_morning(app):
    with app.app_context():
        Schedule.load(app.base_path("routes/console.py"))
        due = Schedule.due_events(datetime(2026, 11, 30, 8, 0, tzinfo=ZoneInfo("UTC")))
        assert [event.description for event in due] == ["app.jobs.send_report.SendReport"]
```
