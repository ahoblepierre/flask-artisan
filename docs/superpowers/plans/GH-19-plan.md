# Vues HTML : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** un échec de validation sur une requête HTML redirige en arrière, avec `errors` et `old()` flashés ; ajouter `csrf_field()` et le middleware `VerifyCsrfToken` ; le squelette reçoit une page de connexion.

**Architecture :**
- Le `Router` choisit entre JSON et redirection à l'endroit où il intercepte déjà `ValidationError` et `AuthorizationError`. Une route de `routes/api.py` (marquée `json`) répond toujours en JSON.
- `Application` enregistre un `before_request`, qui fait passer les données flashées de la session vers `request.environ`, et un `context_processor`, qui expose `errors`, `old`, `csrf_token` et `csrf_field`.
- Le CSRF est un middleware maison, placé dans le groupe `web` du squelette.

**Stack :** Flask 3.1 (session en cookie signé, `context_processor`, `before_request`), Jinja2 et `markupsafe.Markup`, Werkzeug (`Forbidden`).

**Spec :** [docs/superpowers/specs/GH-19-spec.md](../specs/GH-19-spec.md)

## Contraintes globales

- Noms des clés de session : `_flash_errors`, `_flash_old` et `_token`. Clé d'environ : `flask_artisan.flash`.
- Champs jamais flashés : `password`, `password_confirmation`, `current_password` et `_token`. Une saisie de plus de 1 000 caractères n'est pas flashée non plus.
- Les noms CSRF suivent Laravel : champ `_token`, en-tête `X-CSRF-TOKEN`, statut 419, et le message JSON `{"message": "CSRF token mismatch."}`.
- `routing.py`, `views.py` et `csrf.py` n'importent jamais `flask_artisan.auth`.
- `auth/` ne change pas, sauf pour réimporter `expects_json`.
- Commits et PR : `(#19)`.

## Points à surveiller

1. **API inchangée.** Un `POST` de formulaire sur une route d'API, sans `Accept: application/json`, reçoit le 422 JSON et aucun `Set-Cookie`. Couvert par `test_api_route_always_json` (tâche 1).
2. **Redirection ouverte.** Un `Referer: https://evil.example/x` redirige vers `/`. Couvert par `test_foreign_referer_redirects_home` (tâche 1).
3. **Les données flashées ne durent qu'une requête.** La deuxième requête après l'erreur n'a plus ni `errors` ni `old`. Couvert par `test_flash_lasts_one_request` (tâche 2).
4. **Un formulaire posté sans session** (cookie expiré, première visite) reçoit un 419, pas un 500, même si le jeton du formulaire est vide. Couvert par `test_csrf_missing_session_token` (tâche 3).
5. **Les tests du squelette relancés plusieurs fois** restent verts (cache `array`, base en mémoire, `app.testing`). Vérifié à la tâche 4.

---

### Task 1: JSON or redirect in the Router

**Fichiers :**
- Modifier : `src/flask_artisan/middleware.py` (ajouter `expects_json`), `src/flask_artisan/auth/middleware.py` (le réimporter depuis `flask_artisan.middleware`), `src/flask_artisan/routing.py`, `src/flask_artisan/route_provider.py`
- Créer : `tests/test_html_errors.py`

**Interfaces :**
- Produit :
  - `flask_artisan.middleware.expects_json(request) -> bool` ;
  - `Router.load(path, prefix="", middleware=(), json=False)`, `RouteGroup(..., json=False)` et `PendingRoute.json: bool` ;
  - dans `routing.py`, la constante `DONT_FLASH = {"password", "password_confirmation", "current_password", "_token"}` et `MAX_OLD_LENGTH = 1000`.
- Écrit en session : `_flash_errors` (dict) et `_flash_old` (dict).

- [ ] **Étape 1 : écrire les tests** dans `tests/test_html_errors.py`, avec `routed_app`. La vue `store` appelle `validate(request.form.to_dict(), {"email": "required|email"})`, et la vue `deny` lève `AuthorizationError()`.
  - `test_html_validation_redirects_back` : `POST /form`, avec `data={"email": "x", "name": "Ada", "password": "s"}` et `headers={"Referer": "http://localhost/form"}`, renvoie `assert_redirect("http://localhost/form")`. La session (`client.session_transaction()`) contient `_flash_errors` avec `email`, et `_flash_old == {"email": "x", "name": "Ada"}`.
  - `test_json_request_keeps_422` : le même `POST`, avec `json=...`, renvoie `assert_status(422).assert_json_validation_errors(["email"])`.
  - `test_api_route_always_json` : une route déclarée dans un groupe `json=True` (par `router.load` d'un fichier temporaire avec `json=True`, ou `RouteGroup(router, json=True)`) répond à un `POST` de formulaire par un 422 JSON, sans en-tête `Set-Cookie`.
  - `test_foreign_referer_redirects_home` : avec `Referer: https://evil.example/x`, `assert_redirect("/")`. Sans `Referer`, `assert_redirect("/")` aussi.
  - `test_long_input_not_flashed` : avec `bio` de 1 001 caractères, `bio` est absent de `_flash_old`.
  - `test_html_authorization_is_html_403` : `deny` renvoie 403 avec `text/html` ; la même requête avec `Accept: application/json` renvoie le JSON `{"message": "This action is unauthorized."}`.
  - `test_api_provider_marks_json` : dans `tests/test_route_provider.py`, une route de `routes/api.py` a `json is True` dans `router.registered`, et une route de `web.py` a `json is False`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_html_errors.py tests/test_route_provider.py -q`.
  Attendu : les nouveaux tests ÉCHOUENT (302 attendu, 422 reçu ; `json` absent).
- [ ] **Étape 3 : implémenter.**
  - Dans `_view`, le `except` fait :
    - `if route.json or expects_json(request): return exc.get_response()` ;
    - sinon, `ValidationError` passe par `_redirect_back(exc.errors)`, et `AuthorizationError` renvoie `Forbidden().get_response()`.
  - `_redirect_back` :
    - écrit les deux clés en session ;
    - prend le `request.referrer` seulement s'il commence par `request.host_url` ;
    - renvoie `redirect(target, 302)`.
  - Le `PendingRoute` reçoit `json=any(g._json for g in self._groups)` dans `_add`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/test_html_errors.py tests/test_route_provider.py tests/auth tests/validation -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: erreurs de validation HTML redirigées en arrière, routes d'API toujours en JSON (#19)`.

### Task 2: errors, old() and the template context

**Fichiers :**
- Créer : `src/flask_artisan/views.py`, `tests/test_views.py`
- Modifier : `src/flask_artisan/application.py` (enregistrer le `before_request` et le `context_processor` dans `__init__`)

**Interfaces :**
- Consomme : les clés de session `_flash_errors` et `_flash_old` de la tâche 1.
- Produit, dans `flask_artisan.views` :
  - `class ErrorBag` : `has(field) -> bool`, `first(field) -> str`, `get(field) -> list[str]`, `all() -> list[str]`, `any() -> bool` et `__bool__` ;
  - `errors() -> ErrorBag` et `old(key, default="")` ;
  - `csrf_token() -> str` et `csrf_field() -> Markup` ;
  - `age_flash() -> None`, le `before_request`.
- La tâche 3 consomme `csrf_token`.

- [ ] **Étape 1 : écrire les tests** dans `tests/test_views.py`. On crée un dossier `resources/views/form.html` dans le projet de `make_project`, et une route `GET /form` qui fait `render_template("form.html")`. Le template affiche `{{ errors.first('email') }}|{{ old('email') }}|{{ errors.any() }}|{{ csrf_field() }}`. Les tests :
  - `test_errors_and_old_in_template` : après un `POST` invalide (route de la tâche 1), puis `GET /form`, la page contient le message d'erreur de l'email, `x` et `True` ;
  - `test_flash_lasts_one_request` : un deuxième `GET /form` contient `||False|`, sans erreur ni saisie ;
  - `test_no_session_cookie_without_flash` : un `GET` d'une route JSON sans données flashées n'a pas de `Set-Cookie` ;
  - `test_error_bag` : avec `ErrorBag({"email": ["a", "b"], "name": ["c"]})`, `first("email") == "a"`, `get("x") == []`, `first("x") == ""`, `all() == ["a", "b", "c"]`, `has("name")`, et `bool(ErrorBag({})) is False` ;
  - `test_csrf_field_escapes_and_reuses_token` : dans un `test_request_context`, deux appels à `csrf_token()` renvoient la même chaîne, d'au moins 40 caractères, et `csrf_field()` contient `name="_token"` et ce jeton.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_views.py -q`.
  Attendu : ÉCHEC à l'import de `flask_artisan.views`.
- [ ] **Étape 3 : implémenter `views.py`** comme le dit la spec, section « Fonctions des templates ».
  - `age_flash` fait `session.pop` de chaque clé seulement si elle est présente, et range le résultat dans `request.environ["flask_artisan.flash"]`.
  - Dans `Application.__init__`, `self.before_request(age_flash)` et `self.context_processor(lambda: {"errors": errors(), "old": old, "csrf_token": csrf_token, "csrf_field": csrf_field})`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/test_views.py tests/test_html_errors.py tests/test_application.py -q`.
  Attendu : tout passe, y compris `test_no_flask_attribute_shadowed`.
- [ ] **Étape 5 : commit** `feat: errors, old() et csrf_field() dans les templates (#19)`.

### Task 3: VerifyCsrfToken

**Fichiers :**
- Créer : `src/flask_artisan/csrf.py`, `tests/test_csrf.py`
- Modifier : `src/flask_artisan/__init__.py` (exporter `VerifyCsrfToken`)

**Interfaces :**
- Consomme : `csrf_token()` de la tâche 2 et `expects_json` de la tâche 1.
- Produit : `class VerifyCsrfToken(Middleware)`, `handle(self, request, next)`.

- [ ] **Étape 1 : écrire les tests** dans `tests/test_csrf.py`, avec un kernel `{"csrf": VerifyCsrfToken}`, une route `GET /form` qui renvoie `{"token": csrf_token()}` et une route `POST /submit` (middleware `csrf`) qui renvoie `{"ok": True}`. `app.testing` reste à `False`. Les tests :
  - `test_csrf_get_passes` ;
  - `test_csrf_form_token_passes` : on récupère le jeton par `GET /form`, puis `POST /submit` avec `data={"_token": token}` passe en 200 ;
  - `test_csrf_header_token_passes` : avec l'en-tête `X-CSRF-TOKEN` ;
  - `test_csrf_wrong_token_419` : la réponse HTML est un 419 qui contient « expir » ; avec `Accept: application/json`, la réponse est un 419 et `assert_json({"message": "CSRF token mismatch."})` ;
  - `test_csrf_missing_session_token` : un nouveau client, `POST` avec `data={"_token": ""}`, puis sans champ : 419 dans les deux cas ;
  - `test_csrf_skipped_when_testing` : `app.testing = True`, et un `POST` sans jeton passe en 200.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_csrf.py -q`.
  Attendu : ÉCHEC à l'import.
- [ ] **Étape 3 : implémenter `csrf.py`.**
  - `hmac.compare_digest` sur deux chaînes, seulement quand les deux sont non vides.
  - La réponse 419 se construit avec `Response(..., status=419)`.
  - Le jeton de session se lit par `session.get("_token")`, jamais par `csrf_token()`, qui en créerait un.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/test_csrf.py -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: middleware VerifyCsrfToken (#19)`.

### Task 4: skeleton login page, docs

**Fichiers :**
- Créer, dans le squelette :
  - `resources/views/layouts/app.html`, `resources/views/auth/login.html` et `resources/views/dashboard.html` ;
  - `app/http/controllers/session_controller.py` et `app/http/controllers/dashboard_controller.py` ;
  - `tests/test_web_auth.py`.
- Créer : `docs/vues.md`.
- Modifier :
  - dans le squelette : `routes/web.py`, `app/http/kernel.py` (`"web": [VerifyCsrfToken]`), `config/flask.py` (`"SESSION_COOKIE_SAMESITE": "Lax"`) et `tests/conftest.py` (`app.testing = True` après l'import de `wsgi`) ;
  - `mkdocs.yml` (`- Vues et formulaires: vues.md` après Routage) ;
  - `docs/validation.md`, `docs/authentification.md`, `README.md`, `CLAUDE.md` et `CHANGELOG.md`.
- Vérifier : `package-data` dans `pyproject.toml` couvre bien les `.html` des nouveaux sous-dossiers de `resources/views/`. Sinon, l'ajouter.

**Interfaces :**
- Consomme : `ValidationError` (levée par `SessionController.store`), `VerifyCsrfToken`, ainsi que `csrf_field`, `errors` et `old` dans les templates.

- [ ] **Étape 1 : écrire `tests/test_web_auth.py` du squelette**, avec la fixture `client` de la conftest. Un utilisateur `ada@example.org` / `secret` est créé dans un `app.app_context()`. Les tests :
  - `test_dashboard_requires_login` : `client.get("/dashboard").assert_redirect("/login")` ;
  - `test_login_page` : `GET /login` est OK et contient `name="_token"` ;
  - `test_bad_login_redirects_back_with_errors` : un `POST /login` avec `data={"email": "ada@example.org", "password": "bad"}` et `headers={"Referer": "http://localhost/login"}` renvoie `assert_redirect("http://localhost/login")` ; le `GET /login` suivant contient « Ces identifiants » et `value="ada@example.org"` ;
  - `test_login_then_logout` : le bon mot de passe renvoie `assert_redirect("/dashboard")` ; `GET /dashboard` est OK et contient `Ada` ; `POST /logout` redirige vers `/`, et `/dashboard` redirige ensuite vers `/login`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_cli.py::test_generated_project_tests_pass -q`.
  Attendu : ÉCHEC, car les routes n'existent pas.
- [ ] **Étape 3 : écrire le squelette** comme le dit la spec, section « Squelette ». Les controllers rendent les vues avec `flask.render_template` et redirigent avec `flask.redirect(url_for(...))`. Le message « Connecté. » passe par `flask.flash`.
- [ ] **Étape 4 : GREEN.**
  - Lancer `.venv/bin/pytest tests/test_cli.py -q`. Attendu : tout passe, y compris `test_generated_api_auth_flow` et `test_generated_login_is_throttled`.
  - Générer un projet dans le scratchpad et y lancer `pytest` trois fois. Attendu : vert les trois fois (point à surveiller n° 5).
- [ ] **Étape 5 : écrire `docs/vues.md`** :
  - les templates et le layout ;
  - `errors` et `old()` ;
  - JSON ou redirection (et les routes d'API, toujours en JSON) ;
  - le CSRF (`csrf_field()`, l'en-tête `X-CSRF-TOKEN`, le 419, le contrôle sauté quand `app.testing`) ;
  - les messages flash ;
  - la limite des 1 000 caractères ;
  - le throttle partagé avec `/api/login`.

  Mettre aussi à jour le nav, `validation.md`, `authentification.md` (la page de connexion du squelette), le README, CLAUDE.md (une puce « Vues HTML ») et le CHANGELOG.
- [ ] **Étape 6 : vérification complète.** Lancer `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` et `.venv/bin/mkdocs build --strict`.
  Attendu : tout passe.
- [ ] **Étape 7 : commit** `feat: page de connexion du squelette, page Vues et formulaires (#19)`.
