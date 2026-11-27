# Tâches planifiées : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** déclarer les tâches récurrentes dans `routes/console.py` avec la façade `Schedule`, et les exécuter avec `flask schedule:run`, `schedule:work` et `schedule:list`.

**Architecture :**
- Tout le code vit dans un seul module, `src/flask_artisan/scheduling.py`, qui contient :
  - `CronExpression` : analyse et correspondance d'une minute ;
  - `Event` : une tâche, ses fréquences et ses verrous ;
  - `Schedule` : le registre, le chargement de `routes/console.py` et l'exécution des tâches dues ;
  - les trois commandes Click.
- `Application` crée le registre (`"schedule"`), comme le `Dispatcher`. Les commandes sont ajoutées à `COMMANDS` dans `console.py`.

**Stack :** bibliothèque standard (`zoneinfo`, `shlex`, `hashlib`), Click, `Cache.lock` (#36), `QueueManager`.

**Spec :** [docs/superpowers/specs/GH-42-spec.md](../specs/GH-42-spec.md)

## Contraintes globales

- Aucune dépendance nouvelle, sauf `tzdata; sys_platform == "win32"`.
- Commandes : `schedule:run`, `schedule:work`, `schedule:list`.
- Messages, mot pour mot :
  - `Exécution : <name>` ;
  - `Sautée (déjà en cours) : <name>` ;
  - `Aucune tâche planifiée à exécuter.` ;
  - `Aucune tâche planifiée.`
- Config : `app.timezone`, défaut `"UTC"`. Une valeur invalide lève `ValueError` en nommant `APP_TIMEZONE`.
- Verrous :
  - identifiant `sha1(expression + fuseau effectif + name)` ;
  - `without_overlapping` : `schedule:<id>`, TTL `minutes * 60` ;
  - `on_one_server` : `schedule:<id>:<AAAAMMJJHHMM UTC>`, TTL 3600 s, jamais libéré ;
  - les deux sont pris par `Lock.get()`, `on_one_server` en premier.
- L'app web ne charge jamais `routes/console.py`.
- Erreur du développeur (argument invalide) : `ValueError` qui nomme la méthode.
- Commits et PR : `(#42)`. Tests dans `tests/scheduling/` (avec un `__init__.py`, comme `tests/cache/`).

## Points à surveiller

1. **Commande imbriquée :** `app.cli.main(..., standalone_mode=False)` est appelée depuis `schedule:run`, qui est lui-même une commande Click lancée par `flask`. Il faut vérifier que la commande appelée voit l'app et son contexte, et qu'un `sys.exit(2)` ou un `click.exceptions.Exit(2)` est compté comme un échec sans arrêter le planificateur. Ces cas sont testés à la tâche 3.
2. **Fuseau DST :** à Paris, le 2026-03-29 à 02:30 n'existe pas. Une tâche `daily_at("02:30")` en `Europe/Paris` n'est pas due ce jour-là, et ça ne plante pas. Testé à la tâche 1.
3. **`now` sans fuseau** passé à `due_events` : lève `ValueError`. Testé à la tâche 2.
4. **Charger deux fois :** le registre est vidé à chaque chargement, donc les tâches ne sont pas dupliquées. Testé à la tâche 2.
5. **Exception au milieu des tâches :** les tâches suivantes s'exécutent quand même, le verrou de `without_overlapping` est libéré, et le code de sortie vaut 1. Testé à la tâche 3.

---

### Task 1: expressions cron et fréquences

**Fichiers :**
- Créer : `src/flask_artisan/scheduling.py`, `tests/scheduling/__init__.py`, `tests/scheduling/test_cron.py`, `tests/scheduling/test_event.py`.

**Interfaces :**
- Produit :
  - `CronExpression(expr: str)`, qui lève `ValueError` si l'expression est invalide, avec `.matches(dt: datetime) -> bool` (`dt` naïf, en heure locale, tronqué à la minute) et `.expression: str` ;
  - `Event(kind: str, target, args=(), kwargs=None)` :
    - attributs `kind` (`"command"`, `"job"` ou `"call"`), `target`, `expression` (`"* * * * *"` par défaut) et `tz` (`str | None`) ;
    - toutes les méthodes de fréquence de la spec, ainsi que `timezone(name)` et `name(text)`, renvoient `self` ;
    - `is_due(now: datetime, default_tz: str) -> bool`, où `now` porte un fuseau : convertit `now` dans `ZoneInfo(self.tz or default_tz)`, tronque à la minute, puis teste l'expression ;
    - `description -> str` : le nom donné par `name()`, sinon la commande, le `module.Classe` du job, ou le `__qualname__` de la fonction.

- [ ] **Étape 1 : écrire les tests de `test_cron.py`.**
  - `test_star_matches_every_minute`
  - `test_exact_values` : `"30 8 * * *"` correspond à 08:30, pas à 08:31.
  - `test_ranges_steps_lists` : `"*/15 9-17 * * 1-5"` correspond au lundi 09:45, pas au samedi 09:45 ; `"0,30 * * * *"` correspond à :30 ; `"10-20/5 * * * *"` correspond à 15, pas à 12.
  - `test_sunday_is_zero_or_seven` : `"0 0 * * 7"` et `"0 0 * * 0"` correspondent tous deux au dimanche 2026-11-29 00:00.
  - `test_day_of_month_or_day_of_week` : `"0 0 13 * 5"` correspond au vendredi 2026-11-27 (jour 27) **et** au vendredi 13. Avec `"0 0 13 * *"`, seul le 13 correspond.
  - `test_invalid_expressions` : `pytest.mark.parametrize` sur `"* * * *"`, `"60 * * * *"`, `"* 24 * * *"`, `"* * 0 * *"`, `"* * * 13 *"`, `"* * * * 8"`, `"*/0 * * * *"`, `"5-1 * * * *"`, `"a * * * *"` et `"@daily"`. Chacune lève `ValueError`, avec un message qui contient l'expression.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/scheduling/test_cron.py -q`. Attendu : ÉCHEC à l'import (`CronExpression` n'existe pas).
- [ ] **Étape 3 : implémenter `CronExpression`.** Chaque champ est analysé en `frozenset[int]`, et le 7 du jour de semaine est ramené à 0. On retient aussi si les champs jour du mois et jour de semaine valent `*`, pour appliquer la règle du « ou ».
- [ ] **Étape 4 : écrire les tests de `test_event.py`.** Ils utilisent des dates avec fuseau : `datetime(..., tzinfo=ZoneInfo("UTC"))`.
  - `test_frequency_expressions` : un `parametrize` vérifie que chaque méthode du tableau de la spec produit l'expression attendue. Par exemple :
    - `daily_at("08:05")` → `"5 8 * * *"` ;
    - `weekly_on(1, "09:30")` → `"30 9 * * 1"` ;
    - `monthly_on(15, "10:00")` → `"0 10 15 * *"` ;
    - `every_five_minutes().weekdays()` → `"*/5 * * * 1-5"` ;
    - `daily().weekends()` → `"0 0 * * 0,6"`.
  - `test_invalid_frequency_arguments` : `daily_at("25:00")`, `daily_at("8h")`, `weekly_on(7)`, `hourly_at(60)`, `monthly_on(0)` et `cron("bad")` lèvent `ValueError`, avec un message qui contient le nom de la méthode.
  - `test_unknown_timezone_raises` : `timezone("Mars/Base")` lève `ValueError`.
  - `test_is_due_uses_event_timezone` : avec `daily_at("08:00").timezone("Europe/Paris")`, l'heure 2026-11-27 07:00 UTC est due, et 08:00 UTC ne l'est pas.
  - `test_is_due_uses_default_timezone` : la même tâche sans `timezone`, avec `default_tz="Europe/Paris"`, donne le même résultat.
  - `test_is_due_ignores_seconds` : `every_minute`, 08:00:59, est due.
  - `test_dst_gap_skips_without_error` : `daily_at("02:30").timezone("Europe/Paris")` n'est due à aucune minute du 2026-03-29 entre 00:00 et 02:59 UTC.
  - `test_description_defaults` :
    - une commande donne `"emails:send --force"` ;
    - un job donne `"<module>.<Classe>"` ;
    - une fonction donne son `__qualname__` ;
    - `name("Rapport")` donne `"Rapport"`.
  - `test_lambda_lock_without_name_raises` : `Event("call", lambda: None).without_overlapping()` lève `ValueError`, avec `on_one_server` en paramètre. `Event("call", lambda: None).name("x").without_overlapping()` passe.
- [ ] **Étape 5 : RED.** Lancer `.venv/bin/pytest tests/scheduling/test_event.py -q`. Attendu : ÉCHEC, `Event` n'existe pas.
- [ ] **Étape 6 : implémenter `Event`.**
  - `weekdays()` et `weekends()` remplacent le 5ᵉ champ de l'expression courante.
  - `without_overlapping(minutes=1440)` et `on_one_server()` enregistrent `self.overlap_minutes: int | None` et `self.one_server: bool`.
  - Une fonction dont le `__qualname__` contient `<lambda>` ou `<locals>`, sans nom explicite, lève `ValueError` dans ces deux méthodes.
- [ ] **Étape 7 : GREEN.** Lancer `.venv/bin/pytest tests/scheduling -q`. Attendu : tout passe.
- [ ] **Étape 8 : commit** `feat: expressions cron et fréquences des tâches planifiées (#42)`.

### Task 2: le registre `Schedule`, la façade et `app.timezone`

**Fichiers :**
- Modifier :
  - `scheduling.py` ;
  - `application.py` (instance `"schedule"` et `Schedule`) ;
  - `facades.py` (façade `Schedule`, accesseur `"schedule"`) ;
  - `__init__.py` (exporter la façade `Schedule` ; la classe `Event` du planificateur n'est pas exportée) ;
  - `pyproject.toml` (`tzdata; sys_platform == "win32"` dans `dependencies`).
- Créer : `tests/scheduling/conftest.py`, `tests/scheduling/test_schedule.py`.

**Interfaces :**
- Consomme : `Event` (tâche 1).
- Produit : la classe `Schedule(app)` dans `scheduling.py`, avec :
  - `command(name) -> Event` : `name` est découpé par `shlex.split` et gardé dans `event.args` ;
  - `job(job, queue=None, connection=None) -> Event` ;
  - `call(fn, *args, **kwargs) -> Event` ;
  - `events() -> list[Event]` ;
  - `timezone() -> str` : lit `app.timezone` et la valide ;
  - `due_events(now) -> list[Event]` ;
  - `load(path: Path) -> None` : vide le registre, puis exécute le fichier comme `Router.load` ; une erreur devient `click.ClickException("Erreur dans <path> : <exc>")`, et un fichier absent est ignoré.
- Fixture `scheduled(make_project)` dans `conftest.py` : elle renvoie une fonction `(source: str, **app_overrides) -> Application`. Cette fonction écrit `routes/console.py` avec `source`, crée l'app et charge le planning.

- [ ] **Étape 1 : écrire les tests de `test_schedule.py`.**
  - `test_facade_registers_events` : dans un contexte d'app, `Schedule.call(f).daily()` donne `Schedule.events()` de longueur 1, avec l'expression `"0 0 * * *"`.
  - `test_due_events_filters` : deux tâches (`every_minute` et `daily_at("08:00")`). À 09:13 UTC, une seule tâche est due.
  - `test_due_events_requires_aware_datetime` : un `datetime` naïf lève `ValueError`.
  - `test_default_timezone_is_utc` : `Schedule.timezone()` renvoie `"UTC"` sans la clé.
  - `test_app_timezone_used` : avec `timezone="'Europe/Paris'"`, `daily_at("08:00")` est due à 07:00 UTC le 2026-11-27.
  - `test_invalid_app_timezone_names_env_var` : avec `timezone="'Nowhere/X'"`, `due_events` lève une `ValueError` dont le message contient `APP_TIMEZONE`.
  - `test_load_runs_file_and_clears` : on charge deux fois le même `routes/console.py`, qui déclare 2 tâches. Le registre en contient toujours 2.
  - `test_load_missing_file_is_empty`.
  - `test_load_error_names_file` : un fichier qui lève `RuntimeError("boom")` donne une `ClickException` dont le message contient `console.py` et `boom`.
  - `test_web_app_does_not_load_console_routes` : un `routes/console.py` qui lève une exception n'empêche ni `Application(root)` ni `app.test_client().get("/")` de fonctionner (404 accepté).
  - `test_job_records_queue_and_connection` : `Schedule.job(J(), queue="emails", connection="sync")` enregistre ces valeurs sur l'`Event`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/scheduling/test_schedule.py -q`. Attendu : ÉCHEC (la façade `Schedule` n'existe pas).
- [ ] **Étape 3 : implémenter `Schedule`,** l'enregistrer dans `Application.__init__` après le `RateLimiter`, ajouter la façade, les exports et `tzdata`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/scheduling tests/test_application.py tests/test_facades.py tests/test_package.py -q`. Attendu : tout passe, y compris le test qui interdit de masquer un attribut de Flask.
- [ ] **Étape 5 : commit** `feat: registre Schedule, façade et app.timezone (#42)`.

### Task 3: exécution, verrous et `schedule:run`

**Fichiers :**
- Modifier : `scheduling.py` et `console.py` (ajouter les commandes à `COMMANDS`).
- Créer : `tests/scheduling/test_run.py`.

**Interfaces :**
- Consomme : `Schedule.load`, `due_events` et `Event` (tâches 1 et 2), ainsi que `Cache.lock(name, seconds).get()` et `.release()`.
- Produit :
  - la fonction de module `_now() -> datetime`, qui renvoie `datetime.now(timezone.utc)` et que les tests remplacent par `monkeypatch` ;
  - `Schedule.run_due(now: datetime, echo) -> bool`, qui renvoie `True` si aucune tâche n'a échoué ;
  - la commande `schedule_run` (`schedule:run`), qui appelle `load(app.base_path("routes/console.py"))` puis `run_due(_now(), click.echo)`, et sort avec 1 si `run_due` renvoie `False`.

- [ ] **Étape 1 : écrire les tests de `test_run.py`.** Ils passent par `app.test_cli_runner().invoke(args=["schedule:run"])`, avec `_now` fixé au 2026-11-27 08:00 UTC et `cache.default=array`.
  - `test_runs_due_call_with_injection` : `Schedule.call(fn).daily_at("08:00")`, où `fn(app: Application)` écrit dans un fichier. On vérifie que le fichier est écrit, que la sortie contient `Exécution : ` et que le code de sortie vaut 0.
  - `test_skips_not_due`.
  - `test_nothing_due_message` : `Aucune tâche planifiée à exécuter.` et le code de sortie 0.
  - `test_runs_command_in_process` : un projet avec `app/console/commands/hello.py`, réutilisé de `test_console_discovery.py`, et `Schedule.command("app:hello").every_minute()`. La sortie contient `Blog`.
  - `test_command_nonzero_exit_is_failure` : une commande qui fait `sys.exit(2)`, puis une deuxième tâche `call`. La deuxième tâche s'exécute et le code de sortie vaut 1.
  - `test_unknown_command_is_failure`.
  - `test_exception_isolated` : la première tâche lève une exception et la seconde s'exécute. La trace sort sur stderr (`CliRunner(mix_stderr=False)`, ou `result.stderr` selon la version de Click), et le code de sortie vaut 1.
  - `test_job_is_pushed` : avec `Queue.fake()` actif dans la fixture, `Schedule.job(J(), queue="emails")` fait que le job est enregistré sur la file `"emails"`.
  - `test_without_overlapping_skips_when_locked` : on prend d'abord `Cache.lock("schedule:<id>")` à la main, en calculant l'id comme la spec. La tâche ne s'exécute pas, et la sortie contient `Sautée (déjà en cours) : `.
  - `test_without_overlapping_releases_after_failure` : la tâche lève une exception. Après le run, le verrou est libre (`Cache.lock(...).get()` renvoie `True`).
  - `test_on_one_server_runs_once_per_minute` : deux `schedule:run` sur la même minute ne lancent la tâche qu'une seule fois. Une minute plus tard, elle se lance à nouveau.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/scheduling/test_run.py -q`. Attendu : ÉCHEC, `No such command 'schedule:run'`.
- [ ] **Étape 3 : implémenter `run_due` et `schedule:run`.**
  - **Commande :** `app.cli.main(args=event.args, prog_name="flask", standalone_mode=False)`, avec `SystemExit`, `click.exceptions.Exit` et `ClickException` interceptés. Un code non nul compte comme un échec.
  - **Job :** `event.target.on_queue(queue)` si `queue` est précisée, puis `Queue.connection(connection).push(job)` ou `Queue.push(job)`.
  - **Fonction :** `app.call(fn, *args, **kwargs)`.
  - **Verrous :** pris dans l'ordre des contraintes globales. Le verrou de `without_overlapping` est libéré dans un `finally`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/scheduling -q`. Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: flask schedule:run, verrous des tâches (#42)`.

### Task 4: `schedule:work` et `schedule:list`

**Fichiers :**
- Modifier : `scheduling.py`.
- Créer : `tests/scheduling/test_work_list.py`.

**Interfaces :**
- Consomme : `run_due` et `_now` (tâche 3).
- Produit :
  - la fonction de module `_sleep(seconds: float)`, qui est `time.sleep` et que les tests remplacent ;
  - `Event.next_run(after: datetime, default_tz: str) -> datetime | None`, qui renvoie la prochaine minute qui correspond, strictement après `after`, dans le fuseau effectif, ou `None` au-delà de 366 jours ;
  - les commandes `schedule_work` et `schedule_list`.

- [ ] **Étape 1 : écrire les tests.**
  - `test_next_run` :
    - à partir du 2026-11-27 08:00 UTC, `daily_at("08:00")` donne le 2026-11-28 08:00 ;
    - `weekly_on(1, "09:00")` donne le lundi 2026-11-30 09:00 ;
    - `"0 0 31 2 *"` donne `None`.
  - `test_next_run_is_fast` : `"0 0 29 2 *"` (le prochain 29 février est en 2028, donc au-delà de 366 jours) renvoie `None` en moins de 0,5 s.
  - `test_list_shows_table` : la sortie contient `Expression`, `Prochaine exécution`, `Tâche`, l'expression et le nom de la tâche. Une tâche impossible affiche `—`.
  - `test_list_empty` : `Aucune tâche planifiée.`
  - `test_work_runs_each_minute_then_stops` :
    - `_now` renvoie des minutes successives ;
    - `_sleep` compte ses appels et lève `KeyboardInterrupt` au 3ᵉ appel ;
    - résultat : la tâche `every_minute` s'est exécutée 2 fois, le code de sortie vaut 0, et le premier `_sleep` attend jusqu'au début de la minute suivante (la valeur est comprise entre 0 et 60).
  - `test_work_pushes_fresh_app_context_per_minute` : la tâche enregistre `id(flask.g._get_current_object())`. Les deux valeurs sont différentes.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/scheduling/test_work_list.py -q`. Attendu : ÉCHEC (`next_run` n'existe pas, ni les commandes).
- [ ] **Étape 3 : implémenter.**
  - `next_run` avance d'abord jusqu'à la prochaine heure qui correspond, puis minute par minute. Il saute les jours entiers qui ne correspondent ni au mois, ni au jour du mois, ni au jour de semaine.
  - `schedule:work` charge le planning une fois. Ensuite, il dort jusqu'au début de la minute suivante, puis fait `with app.app_context(): run_due(...)`. Il recommence ainsi jusqu'à `KeyboardInterrupt`, qu'il intercepte pour sortir avec le code 0.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/scheduling -q`. Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: flask schedule:work et schedule:list (#42)`.

### Task 5: squelette, documentation et projet généré

**Fichiers :**
- Créer :
  - `src/flask_artisan/skeleton/routes/console.py`, avec des exemples commentés et `from flask_artisan import Schedule` ;
  - `docs/planification.md`.
- Modifier :
  - le squelette : `config/app.py` (`"timezone": env("APP_TIMEZONE", "UTC")`) et `.env.example` (`APP_TIMEZONE=UTC`) ;
  - le site : `mkdocs.yml` (« Tâches planifiées: planification.md » dans « Tâches de fond ») ;
  - les docs du repo : `README.md` (une ligne dans la liste), `CLAUDE.md` (une puce d'architecture), `CHANGELOG.md` (`[Non publié]`) ;
  - les tests : `tests/test_cli.py`.

- [ ] **Étape 1 : écrire le test.** Dans `tests/test_cli.py`, `test_generated_schedule_list` lance `flask schedule:list` en sous-processus, dans un projet généré, avec le même environnement que les autres tests du projet généré. Il attend le code de sortie 0 et `Aucune tâche planifiée.`, puisque les exemples sont commentés.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_cli.py -k schedule -q`. Attendu : ÉCHEC, parce que `config/app.py` n'a pas `timezone`, ou parce que le squelette n'a pas de `routes/console.py`. Si le test passe déjà grâce aux valeurs par défaut, le noter en `Ruling` et le garder comme non-régression.
- [ ] **Étape 3 : écrire le squelette et `docs/planification.md`.** La page couvre tout ce qu'exige la section « Documentation » de la spec : la ligne cron, les trois types de tâches, le tableau des fréquences, le fuseau et le changement d'heure, les verrous et le store `redis` pour `on_one_server`, `without_overlapping` qui ne couvre que l'envoi d'un job, `schedule:work` qui ne rattrape pas les minutes manquées, `schedule:list`, et comment tester avec `Schedule.due_events(datetime(..., tzinfo=...))`.
- [ ] **Étape 4 : GREEN et vérification complète.** Lancer, dans cet ordre :
  - `.venv/bin/pytest -q` ;
  - `.venv/bin/ruff check .` ;
  - `.venv/bin/ruff format --check .` ;
  - `.venv/bin/mkdocs build --strict`.

  Attendu : tout passe.
- [ ] **Étape 5 : commit** `docs: tâches planifiées dans le squelette et la documentation (#42)`.
