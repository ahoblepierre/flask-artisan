# Assertions de test HTTP et `acting_as` : plan d'implémentation

> **Pour les agents :** sous-skill requise : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Objectif :** `app.test_client()` renvoie un client du framework. Ses réponses portent des assertions chaînables, et `acting_as(user, guard=None)` authentifie par le vrai guard.

**Architecture :**
- Nouveau module `src/flask_artisan/testing.py`, qui définit `TestResponse` et `TestClient`.
- `Application.__init__` fixe `self.test_client_class = TestClient` sur l'instance, comme `jinja_loader`.
- `TestClient.__init__` combine notre `TestResponse` et `app.response_class`, ce qui garde la réponse Flask.
- `acting_as` écrit la session (guard session) ou crée un vrai token (guard token).

**Stack :** Flask 3.1, Werkzeug 3.1 (`werkzeug.test.TestResponse`, `flask.testing.FlaskClient`), pytest.

**Spec :** [docs/superpowers/specs/GH-46-spec.md](../specs/GH-46-spec.md)

## Contraintes globales

- `auth/` ne change pas. `acting_as` importe `SESSION_KEY`, `SESSION_HASH_KEY`, `_fingerprint`, `AuthManager`, `SessionGuard` et `TokenGuard` depuis `flask_artisan.auth.manager`, et l'import se fait dans la méthode : un projet sans auth n'importe pas `flask_artisan.auth`, qui déclare la table des tokens.
- `TestResponse` et `TestClient` sont exportés par `flask_artisan.testing`, pas par `flask_artisan`.
- Chaque assertion renvoie `self`. En cas d'échec, elle lève une `AssertionError` dont le message contient l'attendu, la valeur reçue et un extrait du corps (500 caractères au plus).
- Le token d'`acting_as` s'appelle `"test"`.
- Commits et PR : `(#46)`.

## Points à surveiller

1. **Une réponse personnalisée par le projet** (`app.response_class = MaReponse`) : la réponse de test doit en rester une instance. Couvert par `test_response_keeps_app_response_class` (tâche 1).
2. **`assert_json` sur un corps qui n'est pas du JSON** (HTML, 204 vide) : il doit lever une `AssertionError` « pas du JSON », pas une `TypeError` ni un `None` comparé. Couvert par `test_assert_json_not_json` (tâche 1).
3. **`assert_json_path` qui traverse une liste avec un index hors limites, ou une clé dans une valeur qui n'est pas un dict** : il doit lever une `AssertionError` qui nomme le segment, pas une `IndexError` ni une `TypeError`. Couvert par `test_assert_json_path_missing` (tâche 1).
4. **Un deuxième `acting_as` sur le même client** : c'est le dernier utilisateur qui est vu. Couvert par `test_acting_as_replaces_user` (tâche 2).
5. **Les tests du squelette lancés plusieurs fois de suite** : ils ne doivent pas recevoir de 429 du throttle ni laisser de base sur le disque. Le squelette force `CACHE_STORE=array` et une base SQLite en mémoire (tâche 3).

---

### Task 1: TestResponse, TestClient and the Application hook

**Fichiers :**
- Créer : `src/flask_artisan/testing.py`, `tests/test_testing.py`
- Modifier : `src/flask_artisan/application.py`, en ajoutant une ligne dans `__init__` juste après `self.jinja_loader = ...`

**Interfaces :**
- Produit :
  - `class TestResponse(werkzeug.test.TestResponse)` avec `assert_status(code: int)`, `assert_ok()`, `assert_json(data)`, `assert_json_path(path: str, value)`, `assert_json_validation_errors(fields: str | list[str])`, `assert_header(name: str, value: str | None = None)` et `assert_redirect(location: str | None = None)`, qui renvoient toutes `self` ;
  - `class TestClient(flask.testing.FlaskClient)`.
- `TestClient.__init__(self, application, response_wrapper=None, *args, **kwargs)` appelle `super().__init__(application, type("TestResponse", (TestResponse, response_wrapper or application.response_class), {}), *args, **kwargs)`. C'est la même combinaison que fait Werkzeug, avec notre classe en tête.

- [ ] **Étape 1 : écrire les tests** dans `tests/test_testing.py`. Une fixture `app` est construite avec `Application(make_project())` (fixture `make_project` de `tests/conftest.py`), et ses routes sont ajoutées par `app.add_url_rule`, en Flask pur. Les tests :
  - `test_test_client_is_artisan` : `isinstance(app.test_client(), TestClient)` et `isinstance(app.test_client().get("/json"), TestResponse)` ;
  - `test_response_keeps_app_response_class` : avec `class MyResponse(flask.Response): def hello(self): return "hi"` et `app.response_class = MyResponse`, la réponse est une instance de `MyResponse`, `.hello() == "hi"`, et `.assert_ok()` marche ;
  - `test_assert_status_and_ok` : passe sur 200 ; `assert_status(201)` sur un 200 lève une `AssertionError` qui contient `201` et `200` ;
  - `test_assertions_chain` : `r.assert_ok().assert_json({...}) is r` ;
  - `test_assert_json_subset` : avec le corps `{"user": {"id": 1, "email": "a@x"}, "tags": ["a", "b"]}`, `assert_json({"user": {"id": 1}})` passe ; `assert_json({"user": {"id": 2}})`, `assert_json({"tags": ["a"]})` et `assert_json({"absent": 1})` lèvent une `AssertionError` ;
  - `test_assert_json_not_json` : sur une route qui renvoie `"<p>hi</p>"`, une `AssertionError` qui contient « JSON » ;
  - `test_assert_json_path` : `assert_json_path("user.email", "a@x")` et `assert_json_path("tags.1", "b")` passent ; une valeur différente lève une erreur ;
  - `test_assert_json_path_missing` : `"user.phone"`, `"tags.5"` et `"tags.x"` lèvent une `AssertionError` qui contient le segment fautif (`phone`, `5`, `x`) ;
  - `test_assert_json_validation_errors` : sur une route qui renvoie `({"message": "…", "errors": {"email": ["…"]}}, 422)`, `"email"` et `["email"]` passent ; `["name"]` lève une erreur ; un 200 avec ce corps lève une erreur qui contient `422` ;
  - `test_assert_header` : présence seule, puis valeur égale ; un en-tête absent ou une valeur différente lève une erreur ;
  - `test_assert_redirect` : une route qui renvoie `redirect("/login")` passe `assert_redirect()` et `assert_redirect("/login")` ; `assert_redirect("/home")` lève une erreur ; un 200 lève une erreur.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_testing.py -q`.
  Attendu : ÉCHEC à l'import (`flask_artisan.testing` n'existe pas).
- [ ] **Étape 3 : écrire `testing.py`**, puis ajouter `self.test_client_class = TestClient` dans `Application.__init__`.
  - Un chemin manquant se signale en nommant le segment.
  - Le corps JSON se lit par `self.get_json(silent=True)`. Un `None` sur un corps non vide, ou un `is_json` faux, fait échouer avec « pas du JSON ».
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/test_testing.py tests/test_application.py -q`.
  Attendu : tout passe, y compris `test_no_flask_attribute_shadowed`.
- [ ] **Étape 5 : commit** `feat: assertions de réponse sur le client de test (#46)`.

### Task 2: acting_as

**Fichiers :**
- Modifier : `src/flask_artisan/testing.py`
- Créer : `tests/auth/test_acting_as.py`

**Interfaces :**
- Consomme : `TestClient` de la tâche 1.
- Produit : `TestClient.acting_as(self, user, guard: str | None = None) -> TestClient`.

- [ ] **Étape 1 : écrire les tests** dans `tests/auth/test_acting_as.py`.
  - Ils réutilisent `auth_app` de `tests/auth/conftest.py` et `AMember` de `.models`, avec un kernel `{"auth": Authenticate}` comme dans `test_middleware.py`.
  - Routes : `/me` → `Auth.user()` avec `auth` ; `/api/me` → `Auth.user()` avec `auth:api` ; `/api/token` avec `auth:api` → `{"name": Auth.user().current_access_token().name}`.
  - La config du `auth_app` doit avoir un guard `web` (session, par défaut) et un guard `api` (token). À vérifier dans la conftest, et à ajouter dans la déclaration du test s'il manque.

  Les tests :
  - `test_acting_as_session_guard` : `client.acting_as(member).get("/me").assert_ok().assert_json({"email": "m@x"})` ;
  - `test_acting_as_token_guard` : `client.acting_as(member, "api").get("/api/me").assert_ok()` ; `/api/token` renvoie `{"name": "test"}` ;
  - `test_acting_as_default_guard_is_not_api` : `client.acting_as(member).get("/api/me").assert_status(401)` (choix A de la spec) ;
  - `test_acting_as_replaces_user` : deux membres, `acting_as(a)` puis `acting_as(b)` ; `/me` renvoie l'email de b. Même vérification avec `"api"` ;
  - `test_acting_as_unknown_guard` : `pytest.raises(AuthenticationError)` sur `acting_as(member, "nope")` ;
  - `test_acting_as_returns_client` : `client.acting_as(member) is client`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/auth/test_acting_as.py -q`.
  Attendu : ÉCHEC, `AttributeError: acting_as`.
- [ ] **Étape 3 : écrire `acting_as`** comme le dit la spec, section « `acting_as` ».
  - La résolution du guard et `create_token` s'exécutent dans `with self.application.app_context():`.
  - Guard session : `with self.session_transaction() as session:` écrit les deux clés.
  - Guard token : `self.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {token}"`.
- [ ] **Étape 4 : GREEN.** Lancer `.venv/bin/pytest tests/auth tests/test_testing.py -q`.
  Attendu : tout passe.
- [ ] **Étape 5 : commit** `feat: acting_as sur le client de test (#46)`.

### Task 3: skeleton example, docs

**Fichiers :**
- Créer : `src/flask_artisan/skeleton/tests/conftest.py`, `src/flask_artisan/skeleton/tests/test_auth.py` et `docs/tests-http.md`.
- Modifier : `mkdocs.yml` (nav HTTP : `- Tests HTTP: tests-http.md` après Limitation de débit), `README.md` (une ligne dans la liste des sujets, lien absolu `https://ahoblepierre.github.io/flask-artisan/tests-http/`), `CLAUDE.md` (une puce d'architecture « Tests HTTP »), `CHANGELOG.md` (une entrée sous `[Non publié]`, section `### Ajouté`).
- Vérifier : `src/flask_artisan/skeleton/tests/test_app.py`. Il importe `wsgi` au chargement, et la conftest doit donc fixer l'environnement avant.

- [ ] **Étape 1 : écrire `tests/test_auth.py` du squelette.**
  - `test_user_endpoint` : un `User` est créé avec `User.create(name="Ada", email="ada@example.org", password="secret")` dans un `app.app_context()`, puis `client.acting_as(user, "api").get("/api/user").assert_ok().assert_json({"email": "ada@example.org"})` ;
  - `test_login_requires_email` : `client.post("/api/login", json={}).assert_status(422).assert_json_validation_errors(["email", "password"])`.
- [ ] **Étape 2 : RED.** Lancer `.venv/bin/pytest tests/test_cli.py::test_generated_project_tests_pass -q`.
  Attendu : ÉCHEC, car la fixture `client` n'existe pas et la table `users` est absente.
- [ ] **Étape 3 : écrire `tests/conftest.py` du squelette.**
  - Avant tout import de `wsgi`, la conftest force les variables d'environnement suivantes, sans `setdefault` (un `.env` ne les écrase pas, et `load_env_file` ne fait pas d'`override`) :
    - `os.environ["DB_CONNECTION"] = "sqlite"` ;
    - `os.environ["DB_DATABASE"] = ":memory:"` ;
    - `os.environ["DB_URL"] = ""` ;
    - `os.environ["CACHE_STORE"] = "array"`.
  - Un commentaire d'une ligne dit pourquoi : la base en mémoire, et le throttle de `/api/login`.
  - La fixture `client` ouvre un `app.app_context()`, appelle `DB.create_all()`, fait `yield app.test_client()`, puis `DB.drop_all()` et `Cache.flush()`.
  - Vérifier que `DB_URL=""` est traité comme absent par `connection_url`. Sinon, ne pas le fixer, et le noter en ruling.
- [ ] **Étape 4 : GREEN.**
  - Lancer `.venv/bin/pytest tests/test_cli.py -q`. Attendu : tout passe. `test_generated_project_tests_pass` lance les tests du squelette, et `test_generated_api_auth_flow` et `test_generated_login_is_throttled` restent verts.
  - Relancer le test deux fois pour vérifier le point à surveiller n° 5.
- [ ] **Étape 5 : écrire `docs/tests-http.md`.**
  - Le client du framework, sans rien à configurer.
  - Le tableau des assertions de la spec.
  - `acting_as` : le guard par défaut, `"api"` pour l'API, un vrai token, l'effet sur les requêtes suivantes, et comment redevenir invité (un nouveau client).
  - La conftest du squelette (base en mémoire, cache `array`).
  - Les liens vers `authentification.md` et `validation.md`.

  Mettre ensuite à jour le nav, le README, CLAUDE.md et le CHANGELOG.
- [ ] **Étape 6 : vérification complète.** Lancer `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` et `.venv/bin/mkdocs build --strict`.
  Attendu : tout passe, et la suite compte 883 tests plus les nouveaux.
- [ ] **Étape 7 : commit** `feat: exemple de test dans le squelette, page Tests HTTP (#46)`.
