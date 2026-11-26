# Queues sur RQ (GH-28) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** jobs façon Laravel (`Job`, `dispatch`, `on_queue`, `delay`, `failed`) enveloppant RQ, pilotes `sync` / `rq`, `flask queue:work` et commandes d'échecs, `Queue.fake()`, `Mail.queue` / `later`, écouteurs `ShouldQueue`, `flask make:job`, doc complète.

**Architecture:** un sous-paquet `src/flask_artisan/queue/` :
- `serialization.py` : `serialize(obj) -> dict`, `restore(payload, base) -> obj` ;
- `jobs.py` : `Job`, `ShouldQueue`, jobs internes `SendQueuedMailable`, `CallQueuedListener`, `execute(job)` (contexte, injection, `failed`) ;
- `manager.py` : `QueueManager` (`"queue"`, façade `Queue`), pilotes `SyncDriver` / `RqDriver`, mode fake, `QueueFake` ;
- `worker.py` : fonctions appelées par RQ (`run`, `on_failure`) et `connect(url)` ;
- `commands.py` : `queue:work`, `queue:failed`, `queue:retry`, `queue:forget`, `queue:flush`.

`rq` et `redis` ne sont importés que dans `worker.py` / `RqDriver` / `commands.py`, à l'utilisation. `Application.__init__` crée le `QueueManager` à côté du `Mailer`.

**Tech Stack:** Flask ≥ 3, RQ 3 (extra `rq`), redis-py, fakeredis[lua] (tests), click, pytest, ruff.

**Spec:** `docs/superpowers/specs/GH-28-spec.md`

## Global Constraints

- Extras : `rq = ["rq>=3,<4"]` ; `dev` gagne `"rq>=3,<4"`, `"fakeredis[lua]>=2.20"`. Aucun import de `rq`/`redis` au chargement de `flask_artisan`. Pilote `rq` sans RQ → `RuntimeError` contenant `pip install "flask-artisan[rq]"`.
- Défauts `Job` : `queue = "default"`, `tries = 1`, `backoff = 0`, `timeout = 60`.
- Sérialisation JSON uniquement ; `JSONSerializer` passé à **chaque** `Queue`, registre, `Job.fetch` et worker. Reconstruction sans `__init__`. Valeurs : JSON natives, `list`/`tuple`/`dict` à clés `str` (récursif), `Model` (par `id`, `find_or_fail` à l'exécution), `datetime`, `date`, `Decimal`. Autre valeur, modèle sans `id`, classe non importable (`<locals>`) → `TypeError` à l'envoi qui nomme la classe et l'attribut.
- Vérifications à l'exécution (défense en profondeur, pas une frontière de sécurité) : classe de job sous-classe de `Job` ; mailable sous-classe de `Mailable` ; écouteur sous-classe de `ShouldQueue` ; `__model__` sous-classe de `Model` ; nom de méthode ne commençant pas par `_`. Sinon `TypeError`.
- `backoff` liste plus courte que `tries - 1` : complétée avec sa dernière valeur. `failed(exc)` appelé une seule fois, quand `retries_left` vaut 0 ou `None` ; exception dans `failed` rattrapée et journalisée.
- Chaque job s'exécute dans `with app.app_context():` (le teardown du provider de base retire la session).
- `queue:retry` remet `retries_left = tries - 1` avant `requeue`.
- Config relue à chaque envoi ; sans `config/queue.py` : `sync`.
- Exports : `Queue`, `dispatch` dans `flask_artisan.__all__` ; `Job`, `ShouldQueue`, `QueueFake`, `QueueManager` dans `flask_artisan.queue.__all__`.
- Aucun test ne touche le réseau ; jobs de test définis au niveau module. Commits `… (#28)`, ruff propre.

## Review Focus

1. Deux jobs successifs dans le même worker : le second ne voit pas les objets ni la transaction non validée du premier (session retirée) — test Task 3.
2. Job qui échoue à tous ses essais avec `backoff` en liste courte : intervalles complétés, `failed` appelé une seule fois, l'exception du job (pas celle de `failed`) dans le registre — test Task 3.
3. Payload modifié dans Redis qui nomme une classe non-`Job` (ex. `os.path`) ou un modèle non-`Model` : `TypeError`, rien d'instancié — test Task 3.
4. Écouteur `ShouldQueue` sur un événement contenant un modèle : le worker reçoit le modèle rechargé à jour, pas l'objet d'origine — test Task 7.
5. Sous `Queue.fake()`, un job non sérialisable lève quand même `TypeError` (l'erreur ne doit pas apparaître seulement en production) — test Task 5.

---

### Task 1: Sérialisation

**Files:**
- Create: `src/flask_artisan/queue/__init__.py`, `src/flask_artisan/queue/serialization.py`, `tests/queue/__init__.py`, `tests/queue/conftest.py`, `tests/queue/models.py`, `tests/queue/test_serialization.py`

**Interfaces:**
- Produces: `class_path(cls) -> str` (`TypeError` si `<locals>` dans `__qualname__`) ; `import_class(path: str, base: type) -> type` (`TypeError` si pas sous-classe de `base`) ; `dump(value, where: str)` / `load(value)` (une valeur) ; `serialize(obj) -> {"class": str, "data": dict}` ; `restore(payload, base) -> obj` (`cls.__new__` + attributs).

- [ ] **Step 1: Tests.** `tests/queue/models.py` : modèle `QPodcast(Model)` (`title: Mapped[str]`), préfixe `Q` réservé à ce dossier. `conftest.py` : fixture `queue_app` = `db_app("…")` (SQLite mémoire) dans un `app_context`. Classes de test au niveau module : `Holder` (attributs libres). Tests :

```python
@pytest.mark.parametrize("value", [None, 1, 1.5, True, "é", [1, "a"], {"k": [1, {"n": None}]}])
def test_json_values_round_trip(value): ...                      # load(dump(v, "x")) == v
def test_tuple_becomes_list(): assert load(dump((1, 2), "x")) == [1, 2]
def test_datetime_date_decimal_round_trip(): ...                 # types et valeurs identiques (tz conservée)
def test_model_round_trip_reloads_fresh(queue_app):              # modèle créé, titre changé en base après dump → load rend le titre à jour
def test_deleted_model_raises_not_found(queue_app):              # ModelNotFound
def test_unsaved_model_rejected(queue_app):                      # TypeError match "id"
def test_unsupported_value_names_attribute():                    # Holder avec attribut `fh = object()` → TypeError match "Holder" et "fh"
def test_non_str_dict_keys_rejected(): ...
def test_local_class_rejected():                                 # class L: ... dans le test → TypeError match "<locals>|L"
def test_restore_skips_init():                                   # __init__ qui lève → restore marche ; attributs privés `_x` non sérialisés
def test_restore_requires_base():                                # payload {"class": "os.path", ...} ou Holder hors base → TypeError, rien instancié
def test_model_marker_must_be_model():                           # {"__model__": "collections.OrderedDict", "id": 1} → TypeError
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/queue -q` — Expected: erreur d'import.
- [ ] **Step 3: Implement** `serialization.py`. Marqueurs : `{"__model__": path, "id": id}`, `{"__datetime__": iso}`, `{"__date__": iso}`, `{"__decimal__": str}` ; un `dict` utilisateur contenant une de ces clés seules est refusé (`TypeError`) pour éviter l'ambiguïté. `import_class` utilise `importlib.import_module` + `getattr` sur le chemin `module.Qualname`.
- [ ] **Step 4: Run** — Expected: PASS ; `ruff check`.
- [ ] **Step 5: Commit** `feat: sérialisation des jobs (modèles par identifiant, JSON) (#28)`

---

### Task 2: `Job`, `QueueManager`, pilote `sync`, façade `Queue`, `dispatch`

**Files:**
- Create: `src/flask_artisan/queue/jobs.py`, `src/flask_artisan/queue/manager.py`, `tests/queue/jobs.py`, `tests/queue/test_sync.py`
- Modify: `src/flask_artisan/queue/__init__.py`, `application.py`, `facades.py` (`class Queue(Facade): accessor = "queue"`), `helpers.py` (`dispatch(job)`), `__init__.py`

**Interfaces:**
- Consumes: `serialize`, `restore` (Task 1).
- Produces:
  - `class Job` : attributs par défaut ; `on_queue(name) -> self` ; `delay(seconds | timedelta) -> self` ; propriétés `queue_name` (file effective) et `delay_seconds` (`int`, 0 par défaut) ; classmethods `dispatch(*a, **kw)`, `dispatch_sync(*a, **kw)` ; `handle()` (à surcharger), `failed(exc)` (vide).
  - `execute(app, job) -> None` dans `jobs.py` : `with app.app_context(): app.call(job.handle)` ; sur exception, appelle `job.failed(exc)` si `final=True` (paramètre), rattrape et journalise une exception de `failed`, puis relance l'exception du job.
  - `class QueueManager` : `__init__(app)`, `push(job) -> str | None`, `connection(name) -> _Connection` (objet avec `push`), `_driver(name)`.
  - `class SyncDriver` : `push(job, options) -> None` = `restore(serialize(job), Job)` puis `execute(..., final=True)`.
  - Options d'envoi calculées par le manager : `{"queue": str, "tries": int, "backoff": list[int], "timeout": int, "delay": int}`.
  - `dispatch(job)` (helpers) = `app("queue").push(job)`.

- [ ] **Step 1: Tests.** `tests/queue/jobs.py` : `Record = []` ; `Ping(Job)` (`__init__(self, word)`, `handle(self)` → `Record.append(self.word)`) ; `Injected(Job)` (`handle(self, svc: Service)`, `Service` classe du module) ; `Boom(Job)` (`handle` lève `RuntimeError("boom")`, `failed(self, exc)` → `Record.append(("failed", str(exc)))`) ; `BadFailed(Boom)` (`failed` lève). Tests `test_sync.py` :

```python
def test_registered(queue_app): assert queue_app.make("queue") is queue_app.make(QueueManager)
def test_dispatch_runs_immediately(queue_app): assert Ping.dispatch("a") is None; assert Record == ["a"]
def test_dispatch_helper_and_facade(queue_app): dispatch(Ping("b")); Queue.push(Ping("c")); assert Record == ["b", "c"]
def test_handle_injected(queue_app): ...                          # Service injecté
def test_sync_round_trips_models(queue_app): ...                   # job avec modèle → handle reçoit une instance rechargée (pas `is` l'originale)
def test_exception_propagates_after_failed(queue_app):             # RuntimeError remonte ; Record == [("failed", "boom")]
def test_failed_error_logged_not_masking(queue_app, caplog):       # BadFailed → RuntimeError("boom") remonte, log mentionne l'erreur de failed
def test_unserializable_job_raises(queue_app): ...                 # TypeError avant exécution
def test_options_and_properties():                                 # Ping("a").on_queue("x").delay(timedelta(minutes=1)) → queue_name "x", delay_seconds 60
def test_dispatch_sync_ignores_driver(queue_app): ...              # avec default "redis" inexistant → s'exécute quand même
def test_unknown_connection(queue_app): ...                        # Queue.connection("nope") → ValueError match "nope"
def test_defaults_without_config(make_project): ...                # Application sans config/queue.py → sync
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/queue -q` — Expected: FAIL (import).
- [ ] **Step 3: Implement.** Défauts de connexion comme `DEFAULT_MAILERS` dans `mail.py` : `{"sync": {"driver": "sync"}}` et `default = "sync"`. Pilote `rq` non géré encore : `ValueError` pour pilote inconnu.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS (dont les tests qui interdisent de masquer Flask).
- [ ] **Step 5: Commit** `feat: Job, dispatch, pilote sync et façade Queue (#28)`

---

### Task 3: Pilote `rq` et exécution dans le worker

**Files:**
- Create: `src/flask_artisan/queue/worker.py`, `tests/queue/test_rq.py`
- Modify: `src/flask_artisan/queue/manager.py`, `pyproject.toml` (extras `rq`, `dev`)

**Interfaces:**
- Consumes: `execute`, `serialize`, `restore`, options d'envoi (Task 2).
- Produces:
  - `worker.connect(url) -> redis.Redis` (`Redis.from_url`) — point de remplacement unique pour les tests ;
  - `worker.run(payload: dict) -> None` : `restore(payload, Job)`, `execute(app, job, final=<retries_left in (0, None)>)` en lisant `rq.get_current_job()` ;
  - `worker.on_failure(job, connection, type, value, traceback)` : rien d'autre que ce qu'exige `execute` (`failed` est appelé dans `run` ; si RQ appelle le callback, il ne relance pas `failed`). Si l'exécutant constate que `run` ne peut pas connaître la dernière tentative, ledger une ruling et utiliser `on_failure` à la place ;
  - `worker.rq_queue(connection_config, name) -> rq.Queue` (avec `JSONSerializer`) ;
  - `RqDriver.push(job, options) -> str` : `enqueue` ou `enqueue_in` de `worker.run` avec `serialize(job)`, `job_timeout`, `retry=Retry(max=tries-1, interval=backoff complété)` si `tries > 1`.

- [ ] **Step 1: Tests** (`pytest.importorskip("rq")`). Fixture `rq_app(queue_app, monkeypatch)` : `server = fakeredis.FakeServer()`, `monkeypatch.setattr("flask_artisan.queue.worker.connect", lambda url: fakeredis.FakeRedis(server=server))`, config `queue.default = "redis"`, connexion `{"driver": "rq", "url": "redis://x", "queue": "default"}`. Helper `work(queues=("default",))` = `SimpleWorker([...], connection=..., serializer=JSONSerializer).work(burst=True)`.

```python
def test_push_returns_id_and_worker_runs(rq_app): assert isinstance(Ping.dispatch("a"), str); assert Record == []; work(); assert Record == ["a"]
def test_payload_is_json_not_pickle(rq_app): ...                    # Job.fetch(id, serializer=JSONSerializer).args[0]["class"] == "tests.queue.jobs.Ping"; le hash Redis ne contient pas b"\x80\x04"
def test_queue_selection(rq_app): ...                               # Ping("a").on_queue("audio") → file "audio" ; work(("default",)) ne l'exécute pas
def test_delay_schedules(rq_app): ...                               # delay(60) → dans ScheduledJobRegistry, pas exécuté par work()
def test_timeout_passed(rq_app): ...                                # class Slow(Job): timeout = 5 → fetched.timeout == 5
def test_retries_then_failed_once(rq_app):                          # Boom avec tries=3, backoff=0 : work() répétés → 3 exécutions, Record contient ("failed", "boom") une seule fois, job dans FailedJobRegistry, exc_info contient "boom"
def test_backoff_padded_with_last_value(rq_app): ...                # tries=4, backoff=[5, 30] → fetched.retry_intervals == [5, 30, 30]
def test_failed_error_does_not_replace_job_error(rq_app): ...       # BadFailed : exc_info du registre contient "boom"
def test_session_removed_between_jobs(rq_app): ...                  # job 1 ajoute un QPodcast sans commit ; job 2 compte les QPodcast → 0
def test_forged_payload_rejected(rq_app): ...                       # queue.enqueue(worker.run, {"class": "os.path", "data": {}}) → échec, TypeError dans exc_info
def test_missing_rq_message(queue_app, monkeypatch): ...            # monkeypatch.setitem(sys.modules, "rq", None) → RuntimeError match 'flask-artisan\[rq\]'
```

- [ ] **Step 2: Run** `.venv/bin/pip install -e ".[dev]"` puis `.venv/bin/pytest tests/queue/test_rq.py -q` — Expected: FAIL (pilote `rq` inconnu).
- [ ] **Step 3: Implement** `worker.py` et `RqDriver` ; extras dans `pyproject.toml`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: pilote rq (JSON, tentatives, délais, failed) (#28)`

---

### Task 4: Commandes `queue:*`

**Files:**
- Create: `src/flask_artisan/queue/commands.py`, `tests/queue/test_commands.py`
- Modify: `src/flask_artisan/console.py` (ajout des commandes à `COMMANDS`)

**Interfaces:**
- Consumes: `worker.connect`, `worker.rq_queue`, config des connexions (Tasks 2–3).
- Produces: `queue:work [CONNECTION] [--queue a,b] [--burst]` (`SimpleWorker(..., serializer=JSONSerializer).work(burst=..., with_scheduler=True)`) ; `queue:failed [--connection]`, `queue:retry IDS... | all`, `queue:forget ID`, `queue:flush` (`FailedJobRegistry` avec `JSONSerializer`, files de la connexion = sa `queue` par défaut). Avec `sync` : message « Connexion sync : aucune file à inspecter. », code 0.

- [ ] **Step 1: Tests** (fixture `rq_app` partagée, déplacée dans `conftest.py`, runner `app.test_cli_runner()`).

```python
def test_work_burst_runs_jobs(rq_app): ...                    # dispatch puis `queue:work --burst` → Record == ["a"]
def test_failed_lists_job(rq_app): ...                        # Boom tries=1 → sortie contient id, "Boom", "default", "boom"
def test_retry_restores_all_tries(rq_app): ...                # Boom tries=2 échoue 2 fois ; queue:retry <id> → job relancé 2 fois avant de revenir en échec
def test_retry_all_forget_flush(rq_app): ...
def test_sync_connection_has_no_queue(queue_app): ...         # "aucune file", exit 0
def test_work_requires_rq_connection(queue_app): ...          # queue:work sur sync → message clair, exit != 0
```

- [ ] **Step 2: Run** — Expected: FAIL (commandes inconnues).
- [ ] **Step 3: Implement** ; `queue:work --burst` avec planificateur : si `with_scheduler=True` pose problème en burst sous fakeredis, ledger une ruling (planificateur seulement hors burst).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: queue:work et commandes des jobs en échec (#28)`

---

### Task 5: `Queue.fake()`

**Files:**
- Modify: `src/flask_artisan/queue/manager.py`
- Test: `tests/queue/test_queue_fake.py`

**Interfaces:**
- Produces: `QueueManager.fake() -> QueueFake` ; `QueueFake` : `restore`, `__enter__/__exit__`, `pushed(cls)`, `assert_pushed(cls, callback=None)`, `assert_pushed_times(cls, n)`, `assert_not_pushed(cls, callback=None)`, `assert_nothing_pushed()`, `assert_pushed_on(queue, cls)`. Enregistre l'instance passée (avec ses options) après un `serialize` de contrôle. `dispatch_sync` n'est pas intercepté.

- [ ] **Step 1: Tests** sur le modèle de `tests/mail/test_mail_fake.py` : enregistrement sans exécution (`Record == []`), callback, comptes et messages d'échec (« Job Ping poussé 2 fois, attendu 1. »), `assert_pushed_on("audio", Ping)`, sous-classes, **`TypeError` d'un job non sérialisable sous fake**, gestionnaire injecté avant `fake()`, `restore` et fake remplacé, `dispatch_sync` exécuté sous fake.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** (même structure que `MailFake`).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Queue.fake() et ses assertions (#28)`

---

### Task 6: Mail en file d'attente

**Files:**
- Modify: `src/flask_artisan/mail.py` (`PendingMail.queue`, `PendingMail.later`, enregistrement sous fake, `MailFake.queued/assert_queued/assert_not_queued/assert_nothing_queued`), `src/flask_artisan/queue/jobs.py` (`SendQueuedMailable`)
- Test: `tests/mail/test_mail_queue.py`

**Interfaces:**
- Consumes: `dispatch` / `QueueManager.push`, `serialize`/`restore` avec base `Mailable`.
- Produces: `PendingMail.queue(mailable) -> str | None`, `PendingMail.later(delay, mailable) -> str | None` ; `SendQueuedMailable(Job)` avec attributs `mailable` (payload sérialisé), `envelope` (`{"to": [[nom, adresse]], ...}`), `mailer` ; `queue` = `mailable.queue` si défini. Son `handle(mailer: Mailer)` reconstruit et appelle `mailer._send(...)`.

- [ ] **Step 1: Tests** (fixtures `mail_app` de `tests/mail/conftest.py`, avec `queue` en `sync` par défaut, et `rq_app`-like pour le worker) :

```python
def test_queue_sync_sends_now(mail_app): Mail.to("a@x.org").queue(Hello("A")); assert len(Mail.transport("array").messages) == 1
def test_queue_pushes_job_under_queue_fake(mail_app): ...      # Queue.fake() → assert_pushed(SendQueuedMailable, lambda j: j.mailer is None or ...) ; rien envoyé
def test_later_sets_delay(mail_app): ...                       # Queue.fake() → delay_seconds == 30
def test_recipients_validated_at_queue_time(mail_app): ...     # Mail.to("nobody").queue(...) → ValueError
def test_mailable_queue_attribute(mail_app): ...               # class Q(Hello): queue = "mails" → queue_name "mails"
def test_mail_fake_records_queued_separately(mail_app):        # Mail.fake() : queue → assert_queued(Hello) ; assert_not_sent(Hello) ; send → assert_sent ; assert_nothing_queued échoue
def test_worker_sends_queued_mail(...):                        # pilote rq + fakeredis : queue puis work() → message dans le transport array, rendu "Hello A"
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** Import de `flask_artisan.queue` dans `mail.py` à l'intérieur des méthodes (pas d'import circulaire au chargement).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Mail.to().queue() et later() (#28)`

---

### Task 7: Écouteurs `ShouldQueue`

**Files:**
- Modify: `src/flask_artisan/events.py` (`_normalize`), `src/flask_artisan/queue/jobs.py` (`ShouldQueue`, `CallQueuedListener`)
- Test: `tests/queue/test_queued_listeners.py`

**Interfaces:**
- Produces: `class ShouldQueue` (marqueur, peut porter `queue`, `tries`, `backoff`, `timeout`) ; `CallQueuedListener(Job)` avec `listener` (chemin), `method`, `event` (payload sérialisé, base `object` mais classe importable obligatoire), réglages copiés de l'écouteur. `_normalize` : classe ou tuple dont la classe hérite de `ShouldQueue` → callable qui pousse `CallQueuedListener` et renvoie `None`.

- [ ] **Step 1: Tests** (événements et écouteurs au niveau module dans `tests/queue/jobs.py`) :

```python
def test_should_queue_listener_is_pushed(queue_app): ...       # Queue.fake() ; Event.dispatch(Shipped(p)) → assert_pushed(CallQueuedListener) ; écouteur non appelé ; dispatch renvoie [None]
def test_tuple_listener_queued(queue_app): ...                 # (QueuedListener, "on_ship")
def test_sync_runs_listener_with_restored_event(queue_app): ... # sync : l'écouteur reçoit un événement reconstruit, son modèle rechargé (titre à jour)
def test_listener_settings_copied(queue_app): ...              # queue = "listeners", tries = 3 → options du job
def test_plain_listener_unchanged(queue_app): ...              # écouteur sans ShouldQueue appelé directement
def test_private_method_rejected(): ...                        # restore d'un CallQueuedListener avec method "_x" → TypeError
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** (import de `flask_artisan.queue.jobs` dans `_normalize`, au besoin, pour éviter un cycle).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: écouteurs ShouldQueue mis en file (#28)`

---

### Task 8: `make:job`, squelette, bout en bout

**Files:**
- Create: `src/flask_artisan/stubs/job.stub`, `src/flask_artisan/skeleton/config/queue.py`, `src/flask_artisan/skeleton/app/jobs/__init__.py`
- Modify: `src/flask_artisan/console.py` (`make_job`), `src/flask_artisan/skeleton/.env.example`
- Test: `tests/test_console.py`, `tests/test_cli.py`

- [ ] **Step 1: Tests.** `make:job ProcessPodcast` (fichier, sous-classe de `Job`, `handle` présent, ruff propre, sortie contient `ProcessPodcast.dispatch(`), sous-dossier ; `test_new_creates_project` + `config/queue.py`, `app/jobs/__init__.py` ; `.env` contient `QUEUE_CONNECTION=sync` ; e2e `test_generated_project_queue_flow` : `make:job Hello`, `handle` remplacé par `print("RAN")`, script qui fait `Hello.dispatch()` (sync → `RAN`) puis `with Queue.fake() as fake: Hello.dispatch()` et `fake.assert_pushed(Hello)`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; `config/queue.py` et `.env.example` : texte de la spec (section « Pilotes et configuration »), `REDIS_URL` commenté.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` et `ruff check . && ruff format --check .` — Expected: vert.
- [ ] **Step 5: Commit** `feat: make:job, config/queue.py et app/jobs du squelette (#28)`

---

### Task 9: Documentation

**Files:** `README.md`, `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: README, section « Queues »** (après « Mail ») couvrant chaque point de la section « Documentation » de la spec, plus : Redis de confiance (mot de passe, réseau privé, `rediss://`), `JSONSerializer` pour `rq-dashboard` / `rq` (`--serializer rq.serializers.JSONSerializer`), redémarrer le worker après déploiement, exemple de superviseur (systemd ou supervisord, quelques lignes), job émis dans une transaction. Section Mail : `queue` / `later` et `assert_queued`. Section Événements : `ShouldQueue`. « Console » : `make:job`, `queue:*`. « Après la v0.1 » : ✅ Queues.
- [ ] **Step 2: CLAUDE.md** : puce « Queues » (sous-paquet, RQ importé à l'usage, JSON partout, SimpleWorker en processus, contexte par job, fake = mode, Redis de confiance).
- [ ] **Step 3: CHANGELOG** « Non publié ».
- [ ] **Step 4: Vérifier** que chaque symbole cité dans le README existe (`grep` dans `src/flask_artisan/queue/`), suite verte.
- [ ] **Step 5: Commit** `docs: queues dans le README, CLAUDE.md et le CHANGELOG (#28)`
