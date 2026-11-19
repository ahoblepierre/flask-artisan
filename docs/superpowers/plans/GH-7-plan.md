# Auth — plan d'implémentation

> **Pour les agents :** sous-skill requis : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**But :** façade `Auth`, guards session et token (tokens en base façon Sanctum), hash automatique du mot de passe, middleware `auth`, et un `AuthController` API dans le squelette.

**Architecture :**
- Nouveau sous-paquet `flask_artisan.auth`.
- `Authenticatable` hache `password` via `@validates("password")` de SQLAlchemy : le validateur est appelé à chaque affectation, mais pas au chargement depuis la base.
- `PersonalAccessToken` est un `Model` du framework. Il entre dans `Model.metadata` dès l'import de `flask_artisan.auth`.
- `AuthManager`, singleton du conteneur sous `"auth"`, construit les guards (`SessionGuard`, `TokenGuard`) depuis `config/auth.py`. Il garde dans `flask.g` le guard par défaut et l'utilisateur résolu pour la requête.
- `Authenticate` est un `Middleware` du routeur existant (`handle(request, next, *guards)`).

**Stack :** Python ≥ 3.10, Flask ≥ 3, Werkzeug (`generate_password_hash`, `check_password_hash`), SQLAlchemy ≥ 2.0, stdlib `secrets`, `hashlib`, `hmac`. Aucune nouvelle dépendance.

**Spec :** [docs/superpowers/specs/GH-7-spec.md](../specs/GH-7-spec.md)

## Contraintes globales

- Aucune dépendance ajoutée.
- Jamais de token ni de mot de passe en clair en base. Les empreintes de tokens sont comparées avec `hmac.compare_digest`.
- `validate` vérifie un hash factice quand l'utilisateur n'existe pas (temps constant). Le hash factice est calculé une seule fois.
- `login` vide la session avant d'écrire l'id.
- La façade `Auth` (dans `facades.py`) n'importe pas `flask_artisan.auth`.
- Messages d'erreur en français. Réponses HTTP du middleware et du controller : `{"message": "Unauthenticated."}`, `{"message": "Invalid credentials."}`.
- Les modèles de test portent des noms uniques dans toute la suite, préfixés `A` (`AUser`, `AMember`…).
- Commits : `feat: … (#7)`, `docs: … (#7)`. Lancer `.venv/bin/ruff check . && .venv/bin/ruff format --check .` avant chaque commit.

## Review Focus

1. **Pas de double hash.** Recharger un utilisateur depuis la base, ou lui affecter une valeur déjà hachée, ne change pas le hash : `check_password` marche toujours (tâche 1).
2. **Tokens malformés.** `"abc"`, `"1|"`, `"x|y"`, `"999|secret"`, un en-tête sans `Bearer` ou avec un autre schéma : `user()` renvoie `None`, sans exception ni 500 (tâches 2 et 3).
3. **Utilisateur disparu.** Un token dont l'utilisateur a été supprimé, ou une session qui pointe vers un utilisateur soft-deleted : non authentifié (tâche 3).
4. **Navigateur sur une route web protégée.** Avec `Accept: text/html,*/*`, on est redirigé vers `login` si cette route existe, sinon on reçoit un 401 JSON. `Accept: */*` seul ne force pas le JSON (tâche 4).
5. **Le guard d'une requête ne fuit pas dans la suivante.** Après une requête `auth:api`, une requête sans middleware utilise de nouveau `web` (tâche 4).

## Fichiers

| Fichier | Rôle |
|---|---|
| `pyproject.toml` | `flask_artisan.auth` dans `packages.find include` |
| `src/flask_artisan/auth/__init__.py` | exports |
| `src/flask_artisan/auth/authenticatable.py` | `Authenticatable`, `HasApiTokens`, `AuthenticationError` |
| `src/flask_artisan/auth/tokens.py` | `PersonalAccessToken`, `find_token(plain) -> PersonalAccessToken \| None` |
| `src/flask_artisan/auth/manager.py` | `AuthManager`, `SessionGuard`, `TokenGuard` |
| `src/flask_artisan/auth/middleware.py` | `Authenticate` |
| `src/flask_artisan/auth/provider.py` | `AuthServiceProvider` |
| `src/flask_artisan/facades.py`, `src/flask_artisan/__init__.py` | façade `Auth` |
| `src/flask_artisan/skeleton/…` | `User`, `config/auth.py`, kernel, `AuthController`, `routes/api.py`, `config/app.py` |
| `tests/auth/__init__.py`, `tests/auth/conftest.py`, `tests/auth/test_*.py` | tests |
| `tests/test_cli.py` | bout en bout |
| `README.md`, `CLAUDE.md` | doc |

---

### Task 1: paquet `flask_artisan.auth` et hash automatique

**Files:**
- Modify: `pyproject.toml` (`include = ["flask_artisan", "flask_artisan.database", "flask_artisan.auth"]`)
- Create: `src/flask_artisan/auth/__init__.py`, `src/flask_artisan/auth/authenticatable.py`
- Create: `tests/auth/__init__.py`, `tests/auth/test_hashing.py`

**Interfaces:**
- Produces : `class Authenticatable` (mixin à placer avant `Model`), avec `check_password(plain: str) -> bool` et un validateur `@validates("password")` qui renvoie `generate_password_hash(value)`, sauf pour `None` et pour une valeur qui commence par `scrypt:` ou `pbkdf2:` ; `class AuthenticationError(Exception)`.

- [ ] **Step 1: Write the failing tests** in `tests/auth/test_hashing.py`, with `class AUser(Authenticatable, Model)` (`email: Mapped[str]`, `password: Mapped[str | None]`) and the `db_app` fixture:
  - `test_create_hashes_password` : `AUser.create(email="a@x", password="secret").password` commence par `"scrypt:"` et `check_password("secret")` est vrai, `check_password("nope")` faux ;
  - `test_assignment_update_and_fill_hash` : `u.password = "p1"` puis `u.update(password="p2")` puis `u.fill(password="p3")` : chaque fois, la valeur stockée est un hash qui vérifie le bon mot de passe ;
  - `test_already_hashed_value_is_kept` : `u.password = other.password` (déjà haché) → les deux hashes sont égaux ;
  - `test_reload_does_not_rehash` : après `save()`, `AUser.find(u.id).password == u.password` (avec `DB.remove()` entre les deux pour forcer la relecture) ;
  - `test_none_stays_none` : `AUser(email="b@x", password=None).password is None`, et `check_password("x")` vaut `False`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/auth/test_hashing.py -q`. Expected : erreur d'import (`flask_artisan.auth` n'existe pas).
- [ ] **Step 3: Implement** `Authenticatable` and `AuthenticationError` in `authenticatable.py`. Export them from `auth/__init__.py`, and add the subpackage to `pyproject.toml`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/auth -q`. Expected : 5 passed. Then run `.venv/bin/pytest -q`. Expected : the whole suite is green.
- [ ] **Step 5: Commit**, with the spec, the plan and the CLAUDE.md status line: `feat: hash automatique du mot de passe avec Authenticatable (#7)`.

### Task 2: tokens d'API

**Files:**
- Create: `src/flask_artisan/auth/tokens.py`
- Modify: `src/flask_artisan/auth/authenticatable.py`, `src/flask_artisan/auth/__init__.py`
- Create: `tests/auth/test_tokens.py`

**Interfaces:**
- Consumes : `Model`, `Builder` (ORM), `_db()` / `DB` for the direct `UPDATE`.
- Produces :
  - `class PersonalAccessToken(Model)` : table `personal_access_tokens` ; `user_id: Mapped[int] = column(index=True)` (no FK) ; `name: Mapped[str]` ; `token: Mapped[str] = column(String(64), unique=True)` ; `last_used_at: Mapped[datetime | None]` ; timestamps ; `fillable = ["user_id", "name", "token"]`, `hidden = ["token"]`.
  - `find_token(plain: str) -> PersonalAccessToken | None` : splits on the first `|`, the id must be an integer, looks up by id, compares `sha256(secret).hexdigest()` with `hmac.compare_digest`. On success, sets `last_used_at` with a direct `UPDATE` (no `save()`).
  - `class HasApiTokens` (mixin) : `create_token(name: str) -> str` (returns `f"{token.id}|{secret}"`, with `secret = secrets.token_urlsafe(40)`), `tokens() -> Builder`, `current_access_token() -> PersonalAccessToken | None` (reads `self._access_token`, set by `TokenGuard` ; `None` by default via `getattr`).

- [ ] **Step 1: Write the failing tests** in `tests/auth/test_tokens.py`, with `class ATokenUser(Authenticatable, HasApiTokens, Model)` :
  - `test_create_token_stores_only_hash` : the returned token matches `^\d+\|.{40,}$` ; the database row holds `sha256(secret)` and never the secret ;
  - `test_find_token_returns_row_and_touches_last_used` : `find_token(plain).user_id == u.id`, and `last_used_at` is no longer `None` ;
  - `test_find_token_rejects_malformed` : parametrized on `"abc"`, `"1|"`, `"x|y"`, `"999|secret"`, `f"{id}|wrong"`, `""` → `None` ;
  - `test_revoked_token_is_rejected` : `PersonalAccessToken.find(id).delete()`, then `find_token(plain) is None` ;
  - `test_tokens_lists_user_tokens` : two tokens for `u`, one for another user → `len(u.tokens().get()) == 2`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/auth/test_tokens.py -q`. Expected : ImportError.
- [ ] **Step 3: Implement** `tokens.py` and `HasApiTokens`, then export them.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/auth -q`, then `.venv/bin/pytest -q`. Expected : the whole suite is green, with no SAWarning.
- [ ] **Step 5: Commit** `feat: tokens d'API en base façon Sanctum (#7)`.

### Task 3: `AuthManager`, guards, provider et façade `Auth`

**Files:**
- Create: `src/flask_artisan/auth/manager.py`, `src/flask_artisan/auth/provider.py`, `tests/auth/conftest.py`, `tests/auth/test_guards.py`
- Modify: `src/flask_artisan/facades.py` (`class Auth(Facade): accessor = "auth"`), `src/flask_artisan/__init__.py` (export `Auth`), `src/flask_artisan/auth/__init__.py`

**Interfaces:**
- Consumes : `find_token`, `Authenticatable.check_password`, `config("auth.*")`.
- Produces :
  - `AuthServiceProvider.register()` : raises `AuthenticationError` if the config has no `auth` key ; registers `AuthManager(app)` under `"auth"` and under `AuthManager`.
  - `AuthManager.guard(name: str | None = None)` : `name or g.get("_auth_guard") or config("auth.defaults.guard")` ; unknown guard or driver → `AuthenticationError` that lists the configured guards. Guards are built per call (they are stateless ; the per-request cache lives in `g`).
  - `AuthManager.should_use(name: str) -> None` : `g._auth_guard = name`.
  - `AuthManager.__getattr__` relays `user`, `id`, `check`, `guest`, `validate`, `attempt`, `login`, `logout` to `self.guard()`.
  - Common to both guards : `user()`, `id()`, `check()`, `guest()`, `validate(**credentials) -> user | None` (dummy hash if not found ; `None` without `password` or when any credential is `None`, since `where(col, None)` would become `IS NULL`). The user is cached in `g` under a key per guard, and `user()` returns `None` outside a request context.
  - `SessionGuard` : session key `"_auth_user_id"` ; `user()` = `model.find(id)` ; `attempt(**c) -> bool` ; `login(user)` = `session.clear()` then write the id, and refresh the cache ; `logout()` = `session.clear()` and empty the cache.
  - `TokenGuard` : reads `request.authorization` (scheme `bearer`, case-insensitive) or the `Authorization: Bearer ` header ; `find_token`, then `model.find(token.user_id)`, then `user._access_token = token`. `attempt`, `login` and `logout` raise `AuthenticationError` with a message that points to `validate` + `create_token` / `current_access_token().delete()`.
- Fixture `auth_app(declare=None, kernel=None)` in `tests/auth/conftest.py` : `db_app("flask_artisan.auth.AuthServiceProvider")` with a `config/auth.py` written without a model, then `app.make("config").set("auth.model", AMember)`. `AMember(Authenticatable, HasApiTokens, Model)` is defined in that conftest. Then `use_kernel` and the routes provider, as in `routed_app`.

- [ ] **Step 1: Write the failing tests** in `tests/auth/test_guards.py` (within `app.test_request_context()` or through routes) :
  - `test_attempt_logs_in_and_user_returns_member` : `Auth.attempt(email=..., password="secret") is True`, then `Auth.user() == m`, `Auth.id() == m.id`, `Auth.check()` ;
  - `test_attempt_wrong_password_unknown_email_missing_password` : the three cases → `False`, with no exception ;
  - `test_validate_none_credential_is_rejected` : a member stored with `email=None` ; `Auth.validate(email=None, password="secret") is None` ;
  - `test_validate_unknown_email_checks_dummy_hash` : monkeypatch `check_password_hash` to count its calls → called once even when the email is unknown ;
  - `test_login_clears_session_first` : `session["foo"] = 1` ; `Auth.login(m)` → `"foo" not in session` ;
  - `test_logout_forgets_user` ;
  - `test_session_user_soft_deleted_or_missing_is_none` (model with `SoftDeletes` : `AMemberSD`) ;
  - `test_token_guard_reads_bearer` : `Auth.guard("api").user() == m` and `current_access_token()` is the right token ;
  - `test_token_guard_malformed_headers` : parametrized on `"Token abc"`, `"Bearer"`, `"Bearer x|y"`, no header → `None` ;
  - `test_token_of_deleted_user_is_none` ;
  - `test_token_guard_rejects_attempt_login_logout` → `AuthenticationError` ;
  - `test_unknown_guard_lists_configured` : `pytest.raises(AuthenticationError, match="web, api")` ;
  - `test_provider_without_auth_config_fails`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/auth/test_guards.py -q`. Expected : ImportError or AttributeError (`Auth` is missing).
- [ ] **Step 3: Implement** `manager.py`, `provider.py`, the facade and the exports.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected : green. The tests that check that no Flask attribute is shadowed still pass.
- [ ] **Step 5: Commit** `feat: façade Auth, guards session et token (#7)`.

### Task 4: middleware `auth`

**Files:**
- Create: `src/flask_artisan/auth/middleware.py`, `tests/auth/test_middleware.py`
- Modify: `src/flask_artisan/auth/__init__.py`

**Interfaces:**
- Consumes : `AuthManager.guard`, `AuthManager.should_use`.
- Produces : `class Authenticate(Middleware)` with `handle(self, request, next, *guards)`. No guards means the default guard. For each guard, if `guard(name).user()` returns someone, it calls `should_use(name)` and returns `next(request)`. Otherwise, it returns the unauthenticated response :
  - `expects_json(request)` = `request.is_json` or `"json" in (request.accept_mimetypes.best or "")` (best type only, `*/*` alone does not count) → `({"message": "Unauthenticated."}, 401)` ;
  - otherwise, if `"login" in current_app.view_functions` → `redirect(url_for("login"))` ;
  - otherwise → the 401 JSON response.

- [ ] **Step 1: Write the failing tests** in `tests/auth/test_middleware.py`, with a kernel `middleware = {"auth": Authenticate}` and the `auth_app` fixture :
  - `test_auth_lets_logged_in_session_through` : a `/login-as` route without middleware that calls `Auth.login(m)`, then `/me` with `auth` → 200 and the JSON of `m` without `password` ;
  - `test_auth_api_with_bearer` : `/api/me` with `auth:api` and `Auth.user()` in the handler (with no `guard("api")`) → the token's user (checks `should_use`) ;
  - `test_auth_multiple_guards` : `auth:web,api` with only a bearer → 200 ;
  - `test_unauthenticated_json_when_client_wants_json` : `Accept: application/json` → 401 `{"message": "Unauthenticated."}` ;
  - `test_browser_redirected_to_login_when_route_exists` : `Accept: text/html,*/*`, a route named `login` → 302 to its URL ;
  - `test_browser_gets_401_without_login_route` ;
  - `test_star_accept_alone_is_not_json` : `Accept: */*` with a `login` route → 302 ;
  - `test_guard_does_not_leak_between_requests` : request `auth:api`, then a route without middleware that returns `Auth.guard().__class__.__name__` → `"SessionGuard"` ;
  - `test_unknown_guard_param_raises_on_request` : `auth:nope` → `AuthenticationError` at request time (with `app.testing = True`, the client propagates it).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/auth/test_middleware.py -q`. Expected : ImportError.
- [ ] **Step 3: Implement** `Authenticate`, then export it.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Expected : green.
- [ ] **Step 5: Commit** `feat: middleware auth (#7)`.

### Task 5: squelette, bout en bout, documentation

**Files:**
- Modify: `skeleton/app/models/user.py` (`class User(Authenticatable, HasApiTokens, Model)`), `skeleton/config/app.py` (`AuthServiceProvider` after `DatabaseServiceProvider`), `skeleton/app/http/kernel.py` (`middleware = {"auth": Authenticate}`), `skeleton/routes/api.py`
- Create: `skeleton/config/auth.py` (the spec's content), `skeleton/app/http/controllers/auth_controller.py`
- Modify: `tests/test_cli.py`, `README.md`, `CLAUDE.md`

**Interfaces:**
- `AuthController` :
  - `login()` : `data = request.get_json(silent=True) or {}` ; `user = Auth.validate(email=data.get("email"), password=data.get("password"))` ; if there is no user → `({"message": "Invalid credentials."}, 401)` ; otherwise `{"token": user.create_token(data.get("device_name") or "api")}`.
  - `logout()` : `Auth.user().current_access_token().delete()` ; `("", 204)`.
  - `user()` : returns `Auth.user()`.
- `routes/api.py` : `Route.post("/login", AuthController.login).name("api.login")` ; `with Route.middleware("auth:api"):` `POST /logout` (`api.logout`) and `GET /user` (`api.user`). Keep the commented examples.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py` :
  - extend `test_generated_project_migrates` : `personal_access_tokens` is also in the tables ;
  - `test_generated_api_auth_flow` : `make:migration` + `migrate`, then a `python -c` script with `wsgi.app.test_client()` that creates `User.create(name="A", email="a@x", password="secret")`, then : `POST /api/login` with a bad password → 401 ; with no body → 401 ; with the right password → 200 and a token ; `GET /api/user` with the bearer → 200, `email == "a@x"`, no `password` ; `POST /api/logout` → 204 ; `GET /api/user` with the same token → 401. It prints `OK` at the end.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_cli.py -q`. Expected : the two tests fail (missing table, 404 on `/api/login`).
- [ ] **Step 3: Implement** the skeleton files.
- [ ] **Step 4: Run** `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`. Expected : green.
- [ ] **Step 5: Docs.**
  - README : an « Authentification » section (`Authenticatable`/`HasApiTokens`, `Auth.attempt`/`user`/`login`/`logout`, `Auth.validate` + `create_token`, middleware `auth`/`auth:api`, curl example for `/api/login` then `/api/user`, note « session signée : APP_KEY obligatoire »). Tick item 4 of the roadmap.
  - CLAUDE.md : an « Auth » architecture paragraph (hash through `@validates`, `PersonalAccessToken` in the metadata when `flask_artisan.auth` is imported, guard per request in `g`, the façade does not import the subpackage).
- [ ] **Step 6: Commit** `feat: auth dans le squelette (AuthController API) et documentation (#7)`.
