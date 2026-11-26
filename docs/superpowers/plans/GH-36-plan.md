# Limitation de débit et verrous (GH-36) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** middleware `throttle:<max>,<minutes>`, service `RateLimiter`, `Cache.lock(...)`, store `file` atomique entre processus (`fcntl.flock`), option `app.trusted_proxies`, squelette protégé, doc complète.

**Architecture:**
- `cache.py` : nouvelle primitive de pilote `_delete_if(k, text)` ; sections critiques (`_add`, `_increment`, `_pull`, `_delete_if`) sous `threading.Lock` pour `array`, sous `flock` d'un fichier `.lock` du dossier pour `file`, script Lua pour `redis`. Classe `Lock` + `LockTimeoutError`, `Store.lock` / `Store.restore_lock` ajoutés à `PUBLIC`.
- Nouveau module `rate_limiting.py` : `RateLimiter(app)` (compteurs dans le store `cache.limiter` ou par défaut) et middleware `ThrottleRequests`.
- `Application.__init__` crée le `RateLimiter` (`"limiter"`) à côté du `CacheManager` et enveloppe `wsgi_app` dans `ProxyFix` si `app.trusted_proxies` > 0.

**Tech Stack:** Flask ≥ 3, Werkzeug `ProxyFix`, `fcntl`, redis-py, fakeredis[lua], pytest, ruff.

**Spec:** `docs/superpowers/specs/GH-36-spec.md`

## Global Constraints

- Aucune dépendance nouvelle. `fcntl` importé dans un `try` (absent sous Windows → pas de verrou, commentaire `shortcut:`).
- Horloge : `time.time()` et `time.sleep()` appelés via le module `time` (les tests les remplacent).
- Verrou : clé `prefix + "lock:" + name` (via `_key`), propriétaire stocké avec `_encode` (JSON), `seconds` ≤ 0 → sans TTL, `owner` par défaut `secrets.token_hex(16)`, attente de `block` par pas de 0,25 s.
- Limiteur : clés `key` et `key + ":timer"` ; `now = int(time.time())`.
- Refus du middleware : corps `{"message": "Too Many Attempts."}`, statut 429, en-têtes `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset`.
- Clé du middleware : `"throttle:" + hashlib.sha1(f"{max}|{decay_minutes}|{identité}".encode()).hexdigest()`, identité `user:<id>` ou `ip:<remote_addr>`.
- Messages d'erreur en français ; commits `… (#36)` ; ruff check + format propres ; aucun réseau dans les tests.
- Exports : `RateLimiter` (façade) dans `flask_artisan.__all__` ; `Lock`, `LockTimeoutError` dans `flask_artisan.cache.__all__` ; `RateLimiter`, `ThrottleRequests` dans `flask_artisan.rate_limiting.__all__`.

## Review Focus

1. Un verrou repris après expiration par un second propriétaire : le premier, en retard, appelle `release()` → `False`, le verrou du second reste (test dans la tâche 2).
2. `restore_lock(name, owner)` dans un autre store (autre instance, même dossier ou même Redis) libère bien : comparaison sur le texte encodé identique (tâche 2).
3. Requêtes concurrentes en threads sur un store `array` : `add` ne réussit qu'une fois (tâche 1).
4. Premier `lock`/`increment` du store `file` sans dossier `storage/cache` : le dossier est créé, pas de `FileNotFoundError` (tâche 1).
5. Le 429 d'un `throttle` intérieur traverse un `throttle` extérieur sans que ses en-têtes soient écrasés (tâche 4).

---

### Task 1: Primitives atomiques des pilotes

**Files:**
- Modify: `src/flask_artisan/cache.py` (classes `Store`, `ArrayStore`, `FileStore`, `RedisStore`)
- Test: `tests/cache/test_atomic.py`

**Interfaces:**
- Produces: `Store._delete_if(k: str, text: str) -> bool` (supprime seulement si la valeur brute stockée vaut `text`, atomique) ; `FileStore._locked()` (gestionnaire de contexte, `flock` exclusif sur `directory / ".lock"`, crée le dossier).

- [ ] **Step 1: Write the failing tests**

```python
# tests/cache/test_atomic.py
import multiprocessing
import threading

import pytest

from flask_artisan.cache import FileStore


def test_delete_if_matches_only_same_text(store):
    k = store._key("x")
    store._put(k, '"a"', None)
    assert store._delete_if(k, '"b"') is False
    assert store.get("x") == "a"
    assert store._delete_if(k, '"a"') is True
    assert store.get("x") is None
    assert store._delete_if(k, '"a"') is False


def _bump(directory, n):
    s = FileStore("p:", directory)
    for _ in range(n):
        s.increment("hits")


def test_file_increment_is_exact_across_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_bump, args=(tmp_path / "c", 100)) for _ in range(4)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    assert FileStore("p:", tmp_path / "c").get("hits") == 400


def test_file_add_creates_directory_and_flush_keeps_lock_file(tmp_path):
    s = FileStore("p:", tmp_path / "missing")
    assert s.add("k", 1) is True
    s.flush()
    assert (tmp_path / "missing" / ".lock").exists()
    assert s.get("k") is None


def test_array_add_wins_once_across_threads(cache_app, tmp_path):
    from .conftest import configure

    configure(cache_app, tmp_path, default="array")
    s = cache_app.make("cache").store()
    barrier, wins = threading.Barrier(8), []

    def race():
        barrier.wait()
        wins.append(s.add("once", 1))

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/cache/test_atomic.py -v`
Expected: `test_delete_if_*` FAIL (`NotImplementedError` ou `AttributeError`), `test_file_increment_*` FAIL (total < 400), `.lock` absent.

- [ ] **Step 3: Implement**
- `Store._delete_if` : `raise NotImplementedError` comme les autres primitives.
- `ArrayStore` : `self._mutex = threading.Lock()` ; `_add`, `_increment`, `_pull`, `_delete_if` sous `with self._mutex`.
- `FileStore._locked()` (`contextlib.contextmanager`) : si `fcntl is None`, `yield` seul avec `# shortcut: pas de flock sous Windows, add/increment/verrous non atomiques entre processus ; Redis si besoin.` ; sinon `mkdir(parents=True, exist_ok=True)`, `open(directory / ".lock", "a")`, `fcntl.flock(f, LOCK_EX)`, `yield`, `LOCK_UN` dans un `finally`. `_add`, `_increment`, `_pull`, `_delete_if` sous `with self._locked()`. Retirer les deux commentaires `shortcut:` actuels de `_add` / `_increment`.
- `RedisStore._delete_if` : `self.client.register_script("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end")(keys=[k], args=[text])`, résultat en `bool`. Le script est enregistré une fois par instance (attribut créé dans `__init__`).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/cache -q`
Expected: tout PASS.

- [ ] **Step 5: Commit**

```bash
git add src/flask_artisan/cache.py tests/cache/test_atomic.py
git commit -m "feat: primitives atomiques des stores, flock pour le store file (#36)"
```

---

### Task 2: `Cache.lock`

**Files:**
- Modify: `src/flask_artisan/cache.py` (`__all__`, `PUBLIC`, `Store.lock`, `Store.restore_lock`, classes `Lock`, `LockTimeoutError`)
- Test: `tests/cache/test_lock.py`

**Interfaces:**
- Consumes: `Store._add`, `Store._delete`, `Store._delete_if`, `Store._key`, `Store._encode`, `_seconds` (tâche 1 et existant).
- Produces: `Store.lock(name: str, seconds=0, owner: str | None = None) -> Lock` ; `Store.restore_lock(name: str, owner: str) -> Lock` ; `Lock.get(callback=None)`, `Lock.block(seconds, callback=None)`, `Lock.release() -> bool`, `Lock.force_release() -> None`, `Lock.owner: str`, `__enter__` / `__exit__` ; `LockTimeoutError(Exception)`.

- [ ] **Step 1: Write the failing tests** (fixtures `store` et `clock` de `tests/cache/conftest.py`, paramétrés sur les trois pilotes)

```python
import time

import pytest

from flask_artisan.cache import LockTimeoutError


def test_get_acquires_once(store):
    assert store.lock("job").get() is True
    assert store.lock("job").get() is False


def test_lock_expires(store, clock):
    assert store.lock("job", 10).get() is True
    clock.advance(11)
    assert store.lock("job", 10).get() is True


def test_release_only_by_owner(store, clock):
    first = store.lock("job", 10)
    first.get()
    clock.advance(11)
    second = store.lock("job", 10)
    assert second.get() is True
    assert first.release() is False
    assert store.lock("job").get() is False   # celui du second tient toujours
    assert second.release() is True
    assert store.lock("job").get() is True


def test_force_release_and_restore_lock(store):
    lock = store.lock("job")
    lock.get()
    assert store.restore_lock("job", "autre").release() is False
    assert store.restore_lock("job", lock.owner).release() is True
    store.lock("job").get()
    store.lock("job").force_release()
    assert store.lock("job").get() is True


def test_get_with_callback_releases_even_on_error(store):
    assert store.lock("job").get(lambda: 42) == 42
    with pytest.raises(RuntimeError):
        store.lock("job").get(lambda: (_ for _ in ()).throw(RuntimeError()))
    assert store.lock("job").get() is True
    assert store.lock("job").get(lambda: 1) is False


def test_block_waits_then_succeeds(store, clock, monkeypatch):
    monkeypatch.setattr(time, "sleep", clock.advance)
    store.lock("job", 1).get()
    assert store.lock("job", 5).block(3) is True


def test_block_times_out(store, clock, monkeypatch):
    monkeypatch.setattr(time, "sleep", clock.advance)
    store.lock("job").get()
    with pytest.raises(LockTimeoutError):
        store.lock("job").block(1)


def test_context_manager(store):
    with store.lock("job", 10):
        assert store.lock("job").get() is False
        with pytest.raises(LockTimeoutError), store.lock("job"):
            pass
    assert store.lock("job").get() is True


def test_lock_name_must_be_a_string(store):
    with pytest.raises(TypeError):
        store.lock(3)


def test_facade(cache_app, tmp_path):
    from flask_artisan import Cache

    from .conftest import configure

    configure(cache_app, tmp_path)
    assert Cache.lock("job").get() is True
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/cache/test_lock.py -v`
Expected: FAIL à l'import (`LockTimeoutError` introuvable).

- [ ] **Step 3: Implement** `Lock(store, name, seconds, owner)` selon la spec : `_k = store._key("lock:" + name)` après contrôle `isinstance(name, str)` (`TypeError` sinon), `_text = store._encode(name, owner)`, TTL `_seconds(seconds)` puis `None` si ≤ 0 ; `get` = `_add(_k, _text, ttl)` ; `block` boucle `get` / `time.sleep(0.25)` jusqu'à `time.time() >= début + seconds` puis `LockTimeoutError(f"Verrou {name!r} toujours pris après {seconds} s.")` ; `release` = `_delete_if` ; `force_release` = `_delete`. `"lock"` et `"restore_lock"` dans `PUBLIC`, `Lock` et `LockTimeoutError` dans `__all__`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/cache -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/flask_artisan/cache.py tests/cache/test_lock.py
git commit -m "feat: Cache.lock, verrous libérés par leur seul propriétaire (#36)"
```

---

### Task 3: `RateLimiter`

**Files:**
- Create: `src/flask_artisan/rate_limiting.py`
- Modify: `src/flask_artisan/application.py` (création du service), `src/flask_artisan/facades.py` (façade `RateLimiter`, accesseur `"limiter"`), `src/flask_artisan/__init__.py` (import + `__all__`)
- Test: `tests/rate_limiting/__init__.py`, `tests/rate_limiting/conftest.py`, `tests/rate_limiting/test_rate_limiter.py`

**Interfaces:**
- Consumes: `CacheManager.store(name)`, `Store.add/put/get/has/increment/forget`.
- Produces: `RateLimiter(app)` avec `hit(key, decay_seconds=60) -> int`, `attempts(key) -> int`, `too_many_attempts(key, max_attempts) -> bool`, `remaining(key, max_attempts) -> int`, `available_in(key) -> int`, `clear(key) -> None`, `attempt(key, max_attempts, callback, decay_seconds=60)`. Conteneur : `"limiter"` et la classe `RateLimiter`.

- [ ] **Step 1: Write the failing tests**

`tests/rate_limiting/conftest.py` : fixture `limiter_app(db_app, tmp_path)` qui configure `cache` avec stores `array` et `other` (array) par défaut `array`, entre dans `app.app_context()` ; reprend la fixture `clock` (même code que `tests/cache/conftest.py`, importée de là : `from tests.cache.conftest import clock  # noqa: F401`).

```python
from flask_artisan import RateLimiter


def test_hit_counts_and_window(limiter_app, clock):
    assert RateLimiter.hit("k", 60) == 1
    assert RateLimiter.hit("k", 60) == 2
    assert RateLimiter.attempts("k") == 2
    assert RateLimiter.remaining("k", 5) == 3
    clock.advance(61)
    assert RateLimiter.attempts("k") == 0


def test_too_many_attempts_and_available_in(limiter_app, clock):
    for _ in range(3):
        RateLimiter.hit("k", 60)
    assert RateLimiter.too_many_attempts("k", 3) is True
    assert RateLimiter.too_many_attempts("k", 4) is False
    clock.advance(20)
    assert RateLimiter.available_in("k") == 40
    RateLimiter.clear("k")
    assert RateLimiter.attempts("k") == 0
    assert RateLimiter.available_in("k") == 0


def test_lost_timer_resets(limiter_app):
    for _ in range(3):
        RateLimiter.hit("k", 60)
    limiter_app.make("cache").store().forget("k:timer")
    assert RateLimiter.too_many_attempts("k", 3) is False
    assert RateLimiter.attempts("k") == 0


def test_counter_never_eternal(limiter_app, clock, monkeypatch):
    RateLimiter.hit("k", 60)
    store = limiter_app.make("cache").store()
    original = type(store).increment

    def late_increment(self, key, by=1):
        clock.advance(61)          # la clé expire entre add et increment
        return original(self, key, by)

    monkeypatch.setattr(type(store), "increment", late_increment)
    assert RateLimiter.hit("k", 60) == 1
    monkeypatch.undo()
    clock.advance(61)
    assert RateLimiter.attempts("k") == 0


def test_attempt(limiter_app):
    assert RateLimiter.attempt("k", 2, lambda: "ok") == "ok"
    assert RateLimiter.attempt("k", 2, lambda: None) is True
    assert RateLimiter.attempt("k", 2, lambda: "ok") is False


def test_limiter_store_from_config(limiter_app):
    limiter_app.make("config").set("cache.limiter", "other")
    RateLimiter.hit("k")
    assert limiter_app.make("cache").store("other").get("k") == 1
    assert limiter_app.make("cache").store().get("k") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/rate_limiting -v`
Expected: FAIL à l'import (`RateLimiter` introuvable dans `flask_artisan`).

- [ ] **Step 3: Implement** `RateLimiter` selon la spec (algorithme `hit` de la spec mot pour mot ; `_store()` = `app.make("cache").store(config.get("cache.limiter"))`, relu à chaque appel). Dans `Application.__init__`, après le `CacheManager` : `limiter = RateLimiter(self)`, `self.instance("limiter", limiter)`, `self.instance(RateLimiter, limiter)`. Façade `class RateLimiter(Facade): accessor = "limiter"`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/rate_limiting tests/test_application.py tests/test_facades.py -q`
Expected: PASS (dont les deux tests qui interdisent de masquer Flask).

- [ ] **Step 5: Commit**

```bash
git add src/flask_artisan tests/rate_limiting
git commit -m "feat: RateLimiter, compteurs de tentatives dans le cache (#36)"
```

---

### Task 4: Middleware `ThrottleRequests`

**Files:**
- Modify: `src/flask_artisan/rate_limiting.py`
- Test: `tests/rate_limiting/test_throttle.py`

**Interfaces:**
- Consumes: `RateLimiter` (tâche 3), état d'auth `request.environ["flask_artisan.auth"]` (clés `"user:<guard>"`, valeur = utilisateur ou `None`).
- Produces: `ThrottleRequests(Middleware).handle(request, next, max_attempts="60", decay_minutes="1")`.

- [ ] **Step 1: Write the failing tests** (fixture `auth_app` de `tests/auth/conftest.py` pour l'identité ; sinon `limiter_app` + routes déclarées par un provider comme `routed_app` ; kernel avec `middleware = {"throttle": ThrottleRequests, "auth": Authenticate}`)

Tests et assertions :
- `test_429_after_max` : route `GET /t` en `throttle:2,1` ; réponses 200, 200 puis 429 ; corps `{"message": "Too Many Attempts."}` ; `Retry-After == "60"`, `X-RateLimit-Limit == "2"`, `X-RateLimit-Remaining == "0"`, `X-RateLimit-Reset == str(int(clock.now) + 60)`.
- `test_headers_on_success` : 1ʳᵉ réponse `X-RateLimit-Limit == "2"`, `X-RateLimit-Remaining == "1"`.
- `test_window_reopens` : après le 429, `clock.advance(61)` → 200.
- `test_refused_request_not_counted` : 3 requêtes (2 OK + 1 refusée), `clock.advance(61)`, puis 2 requêtes OK.
- `test_limits_are_independent` : routes `/a` en `throttle:1,1` et `/b` en `throttle:5,1` ; `/a` deux fois → 429 ; `/b` → 200.
- `test_by_ip` : `environ_base={"REMOTE_ADDR": "1.1.1.1"}` épuise la limite, `"2.2.2.2"` → 200.
- `test_by_user_after_auth` : avec `auth_app`, route `.middleware("auth:api", "throttle:1,1")`, deux utilisateurs avec chacun un token, même IP : 2ᵉ requête du premier → 429, 1ʳᵉ du second → 200.
- `test_throttle_does_not_authenticate` : route `throttle:5,1` seule sur `auth_app` avec un cookie de session valide → `"Vary"` absent ou sans `Cookie` (aucune résolution de guard).
- `test_inner_429_headers_survive_outer` : route `/login` avec `.middleware("throttle:60,1", "throttle:1,1")` : 2ᵉ requête → 429 avec `X-RateLimit-Limit == "1"` et `X-RateLimit-Remaining == "0"`.
- `test_invalid_parameters` : `throttle:abc,1` puis `throttle:0,1` → `pytest.raises(ValueError, match="throttle")` (client avec `app.testing = True` pour propager).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/rate_limiting/test_throttle.py -v`
Expected: FAIL à l'import (`ThrottleRequests`).

- [ ] **Step 3: Implement** selon la spec : `int()` des paramètres, `ValueError` si non entier ou ≤ 0 ; identité = premier utilisateur non `None` dans l'état d'auth (`user.id`), sinon `request.remote_addr` ; clé (Global Constraints) ; `too_many_attempts` avant `hit` ; refus = `current_app.make_response((body, 429, headers))` ; succès : `response.headers.setdefault(...)` pour `X-RateLimit-Limit` / `X-RateLimit-Remaining` (= `remaining` après `hit`). Ajouter `ThrottleRequests` à `__all__`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/rate_limiting tests/test_middleware.py tests/auth -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/flask_artisan/rate_limiting.py tests/rate_limiting/test_throttle.py
git commit -m "feat: middleware throttle, 429 avec Retry-After et en-têtes X-RateLimit (#36)"
```

---

### Task 5: `app.trusted_proxies`

**Files:**
- Modify: `src/flask_artisan/application.py` (`_bridge_flask_config` ou juste après)
- Test: `tests/test_application.py`

**Interfaces:**
- Produces: `config("app.trusted_proxies")` lu au démarrage ; `app.wsgi_app` enveloppé par `werkzeug.middleware.proxy_fix.ProxyFix(x_for=n, x_proto=n, x_host=n, x_port=n)` si n > 0.

- [ ] **Step 1: Write the failing tests** (`routed_app` / `make_project` de `tests/conftest.py`, route qui renvoie `request.remote_addr`)
- `test_trusted_proxies_reads_forwarded_for` : `make_project(trusted_proxies="1")`, requête avec `headers={"X-Forwarded-For": "203.0.113.7"}` et `environ_base={"REMOTE_ADDR": "10.0.0.1"}` → corps `"203.0.113.7"`.
- `test_forwarded_for_ignored_by_default` : sans option → `"10.0.0.1"`.
- `test_trusted_proxies_from_env_string` : `trusted_proxies="'1'"` (chaîne, comme `env`) → `"203.0.113.7"`.
- `test_invalid_trusted_proxies` : `trusted_proxies="'abc'"` → `pytest.raises(ValueError, match="TRUSTED_PROXIES")` à la construction de l'`Application` ; idem pour `"-1"`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_application.py -k proxies -v`
Expected: `reads_forwarded_for`, `from_env_string` et `invalid` FAIL.

- [ ] **Step 3: Implement** : `int(value)` (refuser `bool`), `ValueError("app.trusted_proxies (TRUSTED_PROXIES) : entier ≥ 0 attendu, reçu …")` sinon. Ruling déjà pris : la conversion en `int` est faite par `Application`, le squelette écrit simplement `env("TRUSTED_PROXIES", 0)` (la spec disait `int(env(...))` dans le squelette ; même effet, et un projet qui écrit `"1"` à la main marche aussi).

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_application.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/flask_artisan/application.py tests/test_application.py
git commit -m "feat: app.trusted_proxies, IP du client derrière un proxy (#36)"
```

---

### Task 6: Squelette, test du projet généré, documentation

**Files:**
- Modify: `src/flask_artisan/skeleton/app/http/kernel.py` (alias `"throttle": ThrottleRequests`, groupe `"api": ["throttle:60,1"]`), `skeleton/routes/api.py` (`/login` avec `.middleware("throttle:5,1")`), `skeleton/config/app.py` (`"trusted_proxies": env("TRUSTED_PROXIES", 0)` avec un commentaire), `skeleton/.env.example` (`# TRUSTED_PROXIES=1   # nombre de proxys devant l'app (nginx, load balancer)`), `skeleton/config/cache.py` (`# "limiter": "redis",` commenté : store des compteurs de `throttle`)
- Modify: `tests/test_cli.py` (nouveau test, commentaire sur `AUTH_FLOW`, `ThrottleRequests:5,1` dans l'assertion de `route:list`)
- Modify: `README.md` (section « Limitation de débit et verrous » après « Cache », ligne de feuille de route), `CLAUDE.md` (puce d'architecture), `CHANGELOG.md` (section `## [Non publié]`)

- [ ] **Step 1: Write the failing test** dans `tests/test_cli.py`

```python
THROTTLE_FLOW = """
from wsgi import app
c = app.test_client()
for _ in range(5):
    assert c.post("/api/login", json={"email": "a@x.org", "password": "bad"}).status_code == 401
r = c.post("/api/login", json={"email": "a@x.org", "password": "bad"})
assert r.status_code == 429 and r.headers["Retry-After"], (r.status_code, r.data)
print("OK")
"""


def test_generated_login_is_throttled(project):
    for args in (("make:migration", "init"), ("migrate",)):
        result = run(project, "-m", "flask", *args)
        assert result.returncode == 0, result.stdout + result.stderr
    out = run(project, "-c", THROTTLE_FLOW)
    assert out.stdout.strip() == "OK", out.stdout + out.stderr
```

Au-dessus d'`AUTH_FLOW` : `# 5 POST /api/login exactement : la route est limitée à 5 par minute (throttle:5,1).`

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_cli.py -k throttled -v`
Expected: FAIL (6ᵉ réponse 401).

- [ ] **Step 3: Modify the skeleton** comme listé ci-dessus.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/test_cli.py -q`
Expected: PASS (dont `test_generated_api_auth_flow` et `route:list`).

- [ ] **Step 5: Documentation**

README, section « Limitation de débit et verrous », avec ces sous-parties :
- `throttle` : syntaxe, ce que fait le squelette, en-têtes et corps du 429, compteurs partagés par limite ;
- identité : par IP, ou par utilisateur si `auth` passe avant (exemple `Route.middleware("auth:api", "throttle:60,1")`), et pourquoi le groupe `api` limite par IP ;
- `RateLimiter` : toutes les méthodes, exemple « 5 échecs par e-mail » ;
- `Cache.lock` : `get`, callback, `block`, `with`, `release` / `force_release`, `restore_lock` (exemple : verrou pris dans une requête, libéré par un job) ;
- derrière un proxy : `TRUSTED_PROXIES` ;
- stores : `file` sûr entre processus d'une même machine (pas sous Windows), `redis` pour plusieurs machines, `array` par processus, `cache.limiter` ;
- tester : `CACHE_STORE=array`.

Feuille de route : ligne ✅. CLAUDE.md : puce « Limitation de débit et verrous ». CHANGELOG : `## [Non publié]` avec `### Ajouté` et `### Modifié` (squelette).

- [ ] **Step 6: Full suite, lint**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: tout PASS, aucune erreur ruff.

- [ ] **Step 7: Commit**

```bash
git add src/flask_artisan/skeleton tests/test_cli.py README.md CLAUDE.md CHANGELOG.md
git commit -m "feat: squelette protégé par throttle, documentation (#36)"
```
