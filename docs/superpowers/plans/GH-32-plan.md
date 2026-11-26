# Cache (GH-32) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `Cache` façon Laravel (`get`, `put`, `add`, `forever`, `remember`, `remember_forever`, `has`, `missing`, `pull`, `forget`, `increment`, `decrement`, `flush`, `store(name)`) avec pilotes `array`, `file`, `redis`, valeurs JSON, `flask cache:clear`, doc complète.

**Architecture:** un module `src/flask_artisan/cache.py` :
- `Store` (base) : clés, TTL, sérialisation (`dump`/`load` des queues + `json`), lecture tolérante (valeur illisible = absente), `remember`, `pull`, `has`… ; chaque pilote ne fait que du stockage brut de texte JSON ;
- `ArrayStore`, `FileStore`, `RedisStore` ;
- `CacheManager` (`"cache"`, façade `Cache`) : config relue à chaque `store()`, stores `array` gardés.
`Application.__init__` crée le manager à côté du `QueueManager`. La commande `cache:clear` est ajoutée à `COMMANDS` de `console.py`.

**Tech Stack:** Flask ≥ 3, redis-py (extra `redis`), fakeredis (tests), click, pytest, ruff.

**Spec:** `docs/superpowers/specs/GH-32-spec.md`

## Global Constraints

- Aucune dépendance obligatoire nouvelle ; extra `redis = ["redis>=5"]` ; redis-py importé seulement par `RedisStore`. Sans redis-py → `RuntimeError` contenant `pip install "flask-artisan[redis]"`.
- Jamais de `pickle`. Valeurs : `flask_artisan.queue.serialization.dump(value, f"clé {key!r}")` puis `json.dumps` ; lecture `json.loads` puis `load`.
- `put(k, None)`, `forever(k, None)` et TTL ≤ 0 dans `put` → suppression. TTL : `int`/`float` arrondi au-dessus, `timedelta`, `None` = sans expiration.
- Lecture : `ModelNotFound`, `TypeError`, `ValueError` (dont JSON invalide) pendant le décodage → clé supprimée, `logger.warning` (logger `flask_artisan.cache`), valeur absente.
- Horloge : toujours `time.time()` appelé via le module `time` (les tests remplacent `time.time`).
- `increment`/`decrement` : absente = 0 ; expiration conservée ; valeur non entière → `ValueError`.
- `redis` : clés `prefix + key` ; `flush` = `SCAN MATCH <prefix échappé>*` + `DEL` (jamais `FLUSHDB`) ; `pull` = `GET`+`DEL` en `MULTI` ; client mis en cache par URL.
- `file` : un fichier par clé, nom = SHA-256 de `prefix + key`, écriture atomique (`tempfile` dans le dossier + `os.replace`), `path` relatif à la base du projet.
- Préfixe par défaut : `re.sub(r"\W+", "_", app_name.lower()).strip("_") + "_cache:"`.
- Exports : `Cache` dans `flask_artisan.__all__` ; `CacheManager`, `ArrayStore`, `FileStore`, `RedisStore` dans `flask_artisan.cache.__all__`. Commits `… (#32)`, ruff propre, aucun réseau dans les tests.

## Review Focus

1. Le préfixe contient un caractère spécial de motif (`*`, `?`, `[`) : `flush` Redis ne supprime que les clés du préfixe — test Task 3.
2. Deux écritures concurrentes de la même clé en `file` : jamais de fichier tronqué lu (fichier temporaire + `os.replace`), aucun `.tmp` restant après une écriture qui échoue — test Task 2.
3. `remember` dont le callback lève : rien n'est stocké, l'exception remonte — test Task 1 (contrat commun).
4. `increment` sur une clé avec TTL : le TTL reste (les trois pilotes) — test Task 1/2/3.
5. Valeur modèle supprimée depuis : `get` rend le défaut et `remember` recalcule, sans 404 — test Task 1.

---

### Task 1: `Store`, `ArrayStore`, `CacheManager`, façade `Cache`

**Files:**
- Create: `src/flask_artisan/cache.py`, `tests/cache/__init__.py`, `tests/cache/conftest.py`, `tests/cache/models.py`, `tests/cache/test_store_contract.py`, `tests/cache/test_manager.py`
- Modify: `src/flask_artisan/application.py`, `facades.py` (`class Cache(Facade): accessor = "cache"`), `__init__.py`

**Interfaces:**
- Produces:
  - `class Store` : `__init__(self, prefix: str)` ; publiques : `get(key, default=None)`, `put(key, value, ttl=None) -> bool`, `add(key, value, ttl=None) -> bool`, `forever(key, value) -> bool`, `remember(key, ttl, callback)`, `remember_forever(key, callback)`, `has(key) -> bool`, `missing(key) -> bool`, `pull(key, default=None)`, `forget(key) -> bool`, `increment(key, by=1) -> int`, `decrement(key, by=1) -> int`, `flush() -> None`.
  - Méthodes brutes que chaque pilote implémente (texte JSON, clé déjà préfixée, `seconds: int | None`) : `_get(k) -> str | None`, `_put(k, text, seconds) -> None`, `_add(k, text, seconds) -> bool`, `_delete(k) -> bool`, `_pull(k) -> str | None`, `_increment(k, by) -> int`, `_flush() -> None`.
  - `class ArrayStore(Store)` : `{k: (expires_at | None, text)}`.
  - `class CacheManager` : `__init__(app)`, `store(name=None) -> Store`, et `get`…`flush` délégués au store par défaut (via `__getattr__` limité à la liste publique, ou méthodes explicites).

- [ ] **Step 1: Tests.** `tests/cache/models.py` : `CPost(Model)` (`title: Mapped[str]`, `fillable`). `conftest.py` :
  - fixture `clock(monkeypatch)` : horloge mutable, `monkeypatch.setattr(time, "time", lambda: clock.now)`, `clock.advance(s)` ;
  - fixture `cache_app(db_app)` : app avec base (tables créées, `CPost` importé), `config/cache.py` absent, dans un `app_context` ;
  - fixture paramétrée `store(request, cache_app, tmp_path, …)` : `params=["array"]` pour l'instant (Tasks 2 et 3 ajoutent `"file"` et `"redis"`), renvoie `cache_app.make("cache").store(name)` après avoir écrit la config du store.

  `test_store_contract.py` (tous via `store`) :

```python
def test_get_put_and_default(store): assert store.get("k", "d") == "d"; assert store.put("k", {"a": [1]}) is True; assert store.get("k") == {"a": [1]}
def test_callable_default(store): assert store.get("k", lambda: 5) == 5
def test_ttl_seconds_and_timedelta_expire(store, clock): ...      # put("a", 1, 10) et put("b", 1, timedelta(seconds=10)) ; advance(9) présents ; advance(2) absents
def test_ttl_rounded_up(store, clock): ...                        # put("k", 1, 0.2) ; advance(0.1) présent
def test_non_positive_ttl_and_none_delete(store): ...             # put(k, 1) puis put(k, 2, 0) → absent ; put(k, 1) puis put(k, None) → absent ; forever(k, None) → absent
def test_forever(store, clock): ...                               # advance(10**6) présent
def test_add(store, clock): ...                                   # add absente → True ; présente → False (valeur inchangée) ; expirée → True ; add après put(k, None) → True
def test_remember_computes_once_and_skips_none(store): ...        # compteur d'appels ; callback renvoyant None appelé deux fois, rien stocké
def test_remember_callback_error_stores_nothing(store): ...       # RuntimeError remonte, missing(k)
def test_remember_forever(store, clock): ...
def test_has_missing_pull_forget(store): ...                      # pull rend la valeur puis absente ; forget → True puis False
def test_increment_decrement(store): ...                          # absente → 1 ; increment(k, 5) → 6 ; decrement → 5
def test_increment_keeps_ttl(store, clock): ...                   # put(k, 1, 10) ; increment ; advance(11) → absente
def test_increment_non_integer(store): ...                        # put(k, "x") → ValueError
def test_flush(store): ...
def test_rich_values(store): ...                                  # datetime, Decimal round-trip
def test_unsupported_value_names_key(store): ...                  # TypeError match "k" (object())
@pytest.mark.parametrize("key", ["", 1, None])
def test_invalid_key(store, key): ...                             # TypeError ou ValueError
def test_model_reloaded(store, cache_app): ...                    # put CPost ; titre changé en base ; expire_all ; get → titre à jour
def test_deleted_model_counts_as_missing(store, cache_app, caplog): ...  # put CPost ; delete ; get → défaut ; warning loggé ; missing ; remember recalcule
```

  `test_manager.py` :

```python
def test_registered(cache_app): assert cache_app.make("cache") is cache_app.make(CacheManager)
def test_facade_uses_default_store(cache_app): ...               # config default "array" → Cache.put/get
def test_store_by_name_and_unknown(cache_app): ...               # store("nope") → ValueError match "nope" ; pilote "carrier" → ValueError
def test_array_store_kept(cache_app): ...                        # store("array") is store("array") (même objet ou mêmes données)
def test_defaults_without_config(make_project): ...              # Application sans config/cache.py → store par défaut FileStore sous <base>/storage/cache, préfixe "blog_cache:" pour APP name "Blog"
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/cache -q` — Expected: erreur d'import.
- [ ] **Step 3: Implement** `Store`, `ArrayStore`, `CacheManager` (avec le pilote `file` déclaré comme inconnu pour l'instant : `test_defaults_without_config` reste rouge jusqu'à la Task 2 → le marquer `xfail(strict=True)` ici et retirer le marqueur en Task 2, ruling ledger). Câblage `Application`, façade, export.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS (le test `xfail` attendu).
- [ ] **Step 5: Commit** `feat: Cache, store array et contrat commun des stores (#32)`

---

### Task 2: `FileStore`

**Files:**
- Modify: `src/flask_artisan/cache.py`, `tests/cache/conftest.py` (param `"file"`, `path` sous `tmp_path`), `tests/cache/test_manager.py` (retirer `xfail`)
- Create: `tests/cache/test_file_store.py`

**Interfaces:**
- Produces: `FileStore(prefix, directory: Path)` ; le manager construit `directory = app.base_path(options.get("path", "storage/cache"))`.

- [ ] **Step 1: Tests.** Le contrat entier tourne maintenant aussi en `file`. En plus :

```python
def test_directory_created_on_first_write(tmp_path): ...       # dossier absent → put le crée
def test_one_file_per_key_named_by_hash(tmp_path): ...         # put("a") → un fichier, nom = sha256(prefix+"a"), pas la clé en clair
def test_corrupt_file_counts_as_missing(tmp_path, caplog): ...  # contenu "{" → get défaut, fichier supprimé, warning
def test_no_temp_file_left_when_write_fails(tmp_path, monkeypatch): ...  # os.replace lève OSError → l'erreur remonte, aucun fichier restant dans le dossier
def test_expired_file_removed_on_read(tmp_path, clock): ...
```

- [ ] **Step 2: Run** — Expected: FAIL (pilote `file` inconnu).
- [ ] **Step 3: Implement** ; `_add` = lecture + écriture (non atomique entre processus : commentaire `shortcut:`), `_increment` idem.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: store file (un fichier JSON par clé, écriture atomique) (#32)`

---

### Task 3: `RedisStore`

**Files:**
- Modify: `src/flask_artisan/cache.py`, `pyproject.toml` (extra `redis`), `tests/cache/conftest.py` (param `"redis"` avec `fakeredis`, `pytest.importorskip`)
- Create: `tests/cache/test_redis_store.py`

**Interfaces:**
- Produces: `RedisStore(prefix, client)` ; `cache._redis(url)` (fonction module, `lru_cache`, `Redis.from_url`) — point de remplacement des tests ; le manager construit `RedisStore(prefix, _redis(options["url"]))`.

- [ ] **Step 1: Tests.** Le contrat tourne aussi en `redis` (fixture : `monkeypatch.setattr("flask_artisan.cache._redis", lambda url: fake)`). En plus :

```python
def test_keys_are_prefixed(redis_store, fake): ...                 # put("a") → fake.exists("app_cache:a")
def test_flush_only_touches_prefix(redis_store, fake): ...         # fake.set("rq:queue:x", "1") ; fake.set("other", "1") ; flush → les deux restent
def test_flush_with_glob_chars_in_prefix(fake): ...                # préfixe "a*b[1]:" ; clé "a_b1:x" hors préfixe gardée
def test_add_is_native(redis_store, fake): ...                     # add → TTL posé (fake.pttl > 0)
def test_increment_native_keeps_ttl(redis_store, fake): ...        # INCRBY : pttl inchangé (> 0)
def test_missing_redis_message(cache_app, monkeypatch): ...        # sys.modules["redis"] = None et _redis non remplacé → RuntimeError match 'flask-artisan\[redis\]'
```

- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** `_put` : `set(k, text, px=seconds*1000)` ou sans expiration ; `_add` : `set(k, text, nx=True, px=…)` ; `_increment` : `incrby` (une `ResponseError` « not an integer » → `ValueError`) ; `_pull` : pipeline `MULTI` `get` + `delete` ; `_flush` : `scan_iter(match=_escape(prefix) + "*", count=500)` puis `delete(*lot)` par lots de 500. Échapper `*`, `?`, `[`, `]`, `\` du préfixe.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: store redis (préfixe, SET NX, INCRBY, flush limité au préfixe) (#32)`

---

### Task 4: `flask cache:clear`, squelette, bout en bout

**Files:**
- Create: `src/flask_artisan/skeleton/config/cache.py`
- Modify: `src/flask_artisan/cache.py` (commande `cache_clear`), `src/flask_artisan/console.py` (`COMMANDS`), `src/flask_artisan/skeleton/.env.example`, `src/flask_artisan/skeleton/.gitignore` (`storage/`)
- Test: `tests/cache/test_command.py`, `tests/test_cli.py`

- [ ] **Step 1: Tests.** `cache:clear` vide le store par défaut et affiche son nom ; `cache:clear array` vide ce store-là ; store inconnu → code ≠ 0 qui le nomme. `test_cli.py` : `config/cache.py` dans `test_new_creates_project` ; `.env` contient `CACHE_STORE=file` ; `.gitignore` contient `storage/` ; e2e `test_generated_project_cache_flow` : script `Cache.remember("k", 60, lambda: 41) + 1` imprime `42`, un fichier existe sous `storage/cache/`, puis `flask cache:clear` le supprime.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; `config/cache.py` : texte de la spec, avec le préfixe calculé depuis `APP_NAME` dans le fichier (`env("CACHE_PREFIX", <calcul>)`).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` et `ruff check . && ruff format --check .` — Expected: vert.
- [ ] **Step 5: Commit** `feat: cache:clear, config/cache.py et storage/ du squelette (#32)`

---

### Task 5: Documentation

**Files:** `README.md`, `CLAUDE.md`, `CHANGELOG.md`

- [ ] **Step 1: README, section « Cache »** (après « Queues ») couvrant la section « Documentation » de la spec, avec : tableau des méthodes, TTL, `put(k, None)` qui supprime, valeurs acceptées, modèles relus en base (une requête par modèle ; mettre `to_dict()` en cache pour éviter la base), valeur illisible = absente, `remember` non atomique, `increment` non atomique en `file`, Redis partagé avec les queues (préfixe, `flush` limité), tests avec `array` et `Cache.flush()` dans une fixture, `flask cache:clear`. « Console » : `cache:clear`. « Après la v0.1 » : ✅ Cache.
- [ ] **Step 2: CLAUDE.md** : puce « Cache ».
- [ ] **Step 3: CHANGELOG** « Non publié ».
- [ ] **Step 4: Vérifier** les symboles cités ; suite verte.
- [ ] **Step 5: Commit** `docs: cache dans le README, CLAUDE.md et le CHANGELOG (#32)`
