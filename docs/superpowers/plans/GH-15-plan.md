# Validation (GH-15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `FormRequest` injectée et validée avant le controller, `Validator`/`validate()` autonomes, règles en chaîne façon Laravel, 422/403 JSON, `flask make:request`.

**Architecture:** un module `src/flask_artisan/validation.py` : parseur de règles, table de règles (fonction par règle), messages par défaut, `Validator`, `ValidationError`/`AuthorizationError` (sous-classes de `werkzeug.exceptions.HTTPException` qui produisent leur réponse JSON), `FormRequest` dont le `__init__(self)` lit la requête Flask, appelle `authorize()` puis valide — le conteneur l'autowire sans rien changer à `Container`.

**Tech Stack:** Flask ≥ 3, Werkzeug, SQLAlchemy 2 (Core `table()`/`column()`), pytest, ruff.

**Spec:** `docs/superpowers/specs/GH-15-spec.md`

## Global Constraints

- Aucune nouvelle dépendance.
- Erreur de validation : code 422, corps `{"message": ..., "errors": {champ: [messages]}}` ; message = premier message + ` (and N more error)` / ` (and N more errors)`.
- `authorize()` faux : 403, `{"message": "This action is unauthorized."}`.
- Messages par défaut en anglais (Laravel), `:attribute` = nom du champ avec `_` → espace.
- `validated()` : seulement les champs avec règle **et** présents.
- Valeur `None` présente sans `nullable` : chaque règle hors présence échoue ; avec `nullable`, elles sont ignorées.
- Règle inconnue / paramètre manquant → `ValueError` nommant règle et champ.
- `unique`/`exists` via `DB.session` (même transaction), identifiants validés `[A-Za-z_][A-Za-z0-9_]*`, requête paramétrée.
- Modèles de test préfixés `V` (métadonnées globales au processus).
- Commits : `… (#15)`. Code et fichiers générés passent `ruff check` et `ruff format --check`.

## Review Focus

1. Valeur `0`, `False`, `"0"` présentes : ne sont **pas** vides (`required` réussit) — seul `None`, `""`/espaces, `[]`, `{}` sont vides.
2. `bool` passé à `integer`/`numeric`/`min` : rejeté par `integer`/`numeric` ; `boolean` l'accepte.
3. Injection SQL par `unique:users;drop,email` ou une valeur hostile : identifiant refusé (`ValueError`), valeur liée en paramètre.
4. Corps JSON invalide (`Content-Type: application/json` mais texte cassé) ou liste : corps vide, pas de 400/500.
5. Message personnalisé `"email.required"` prioritaire sur `"required"`, et les deux sur le défaut.

---

### Task 1: Moteur `Validator`, présence, types, format, `ValidationError`

**Files:**
- Create: `src/flask_artisan/validation.py`
- Test: `tests/validation/__init__.py` (vide), `tests/validation/test_validator.py`

**Interfaces:**
- Produces:
  - `class ValidationError(HTTPException)` : `code = 422`, `__init__(self, errors: dict[str, list[str]])`, attribut `.errors`, `get_response(environ=None, scope=None)` → réponse JSON du format global.
  - `class Validator` : `__init__(self, data: Mapping, rules: dict[str, str | list[str]], messages: dict | None = None)`, `fails() -> bool`, `passes() -> bool`, `errors() -> dict[str, list[str]]`, `validated() -> dict` (lève `ValidationError`). Évaluation paresseuse une seule fois.
  - `validate(data, rules, messages=None) -> dict`.
  - Registre interne `RULES: dict[str, callable]` où chaque règle reçoit `(value, params: list[str], field: str, validator)` et rend `bool` ; `MESSAGES: dict[str, str | dict[str, str]]` (dict pour les règles de taille : clés `numeric`, `string`, `array`). Les tâches 2 et 3 y ajoutent leurs entrées.

- [ ] **Step 1: Write the failing tests** (`tests/validation/test_validator.py`)

```python
import pytest
from flask_artisan.validation import ValidationError, Validator, validate

def errors(data, rules, messages=None):
    return Validator(data, rules, messages).errors()

@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_required_fails_on_empty(value):
    assert errors({"name": value}, {"name": "required"}) == {"name": ["The name field is required."]}

@pytest.mark.parametrize("value", [0, False, "0", "x", [1]])
def test_required_accepts_falsy_non_empty(value):
    assert errors({"name": value}, {"name": "required"}) == {}

def test_required_missing():
    assert errors({}, {"first_name": "required"}) == {"first_name": ["The first name field is required."]}

def test_absent_or_empty_skips_other_rules():
    assert errors({"a": ""}, {"a": "email", "b": "integer|min:3"}) == {}

def test_none_without_nullable_fails_each_rule():
    assert errors({"a": None}, {"a": "string|email"}) == {"a": ["The a field must be a string.", "The a field must be a valid email address."]}

def test_none_with_nullable_passes():
    v = Validator({"a": None}, {"a": "nullable|string"})
    assert v.passes() and v.validated() == {"a": None}

def test_sometimes_skips_required_when_absent():
    assert errors({}, {"a": "sometimes|required|string"}) == {}
    assert errors({"a": ""}, {"a": "sometimes|required"}) == {"a": ["The a field is required."]}

def test_required_with():
    rules = {"password": "required_with:email"}
    assert errors({"email": "x"}, rules) == {"password": ["The password field is required when email is present."]}
    assert errors({"email": ""}, rules) == {}

@pytest.mark.parametrize(("rule", "good", "bad"), [
    ("string", "x", 1),
    ("integer", "-3", True), ("integer", 42, "4.2"),
    ("numeric", "4.5", "nan"), ("numeric", 3, False),
    ("boolean", "false", "yes"), ("boolean", 0, 2),
    ("array", [1], "x"), ("array", {"k": 1}, 1),
    ("email", "a@b.co", "a@b"), ("email", "a.b@c.org", "a b@c.org"),
    ("url", "https://x.org/p", "ftp://x.org"),
    ("date", "2026-11-26", "26/11/2026"),
])
def test_type_rules(rule, good, bad):
    assert errors({"f": good}, {"f": rule}) == {}
    assert errors({"f": bad}, {"f": rule}) != {}

def test_validated_only_ruled_present_fields():
    assert validate({"a": "x", "b": "y", "is_admin": True}, {"a": "required", "c": "string"}) == {"a": "x"}

def test_list_form_rules():
    assert errors({"a": "x"}, {"a": ["required", "string"]}) == {}

def test_unknown_rule_is_developer_error():
    with pytest.raises(ValueError, match="nope.*a"):
        Validator({"a": 1}, {"a": "nope"}).fails()

def test_validation_error_response():
    with pytest.raises(ValidationError) as info:
        validate({}, {"email": "required|email", "name": "required", "age": "required"})
    resp = info.value.get_response()
    assert resp.status_code == 422
    assert resp.get_json() == {
        "message": "The email field is required. (and 2 more errors)",
        "errors": {"email": ["The email field is required."], "name": ["The name field is required."], "age": ["The age field is required."]},
    }

def test_validation_error_singular():
    with pytest.raises(ValidationError) as info:
        validate({}, {"a": "required", "b": "required"})
    assert info.value.get_response().get_json()["message"].endswith("(and 1 more error)")
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/validation/test_validator.py -q` — Expected: FAIL (`ModuleNotFoundError: flask_artisan.validation`).
- [ ] **Step 3: Implement** in `validation.py`: parsing (`"a|b:1,2"` or list; `name, _, arg = rule.partition(":")`; `params = arg.split(",") if arg else []`), presence semantics from Global Constraints/spec, rules `required`, `required_with`, `nullable`, `sometimes` (markers), `string`, `integer`, `numeric`, `boolean`, `array`, `email`, `url`, `date`, the messages table from spec (Laravel wording), `:attribute` replacement, `ValidationError` JSON response via `flask.json.dumps`-free `Response(json.dumps(...), mimetype="application/json")` so it works outside an app context.
- [ ] **Step 4: Run** same command — Expected: PASS.
- [ ] **Step 5: Commit** `git add src/flask_artisan/validation.py tests/validation && git commit -m "feat: Validator, règles de présence et de type, ValidationError 422 (#15)"`

### Task 2: Taille, valeurs, comparaison, messages personnalisés

**Files:**
- Modify: `src/flask_artisan/validation.py`
- Test: `tests/validation/test_rules.py`

**Interfaces:**
- Consumes: `Validator`, `RULES`, `MESSAGES` (Task 1).
- Produces: règles `min`, `max`, `between`, `in`, `not_in`, `confirmed`, `same`, `regex` ; priorité `messages["champ.règle"]` > `messages["règle"]` > défaut ; remplacements `:attribute :min :max :other :values`.

- [ ] **Step 1: Write the failing tests** (`tests/validation/test_rules.py`)

```python
import pytest
from flask_artisan.validation import Validator

def errors(data, rules, messages=None):
    return Validator(data, rules, messages).errors()

def test_size_depends_on_type():
    assert errors({"n": "10"}, {"n": "numeric|max:9"}) == {"n": ["The n field must not be greater than 9."]}
    assert errors({"s": "abcd"}, {"s": "string|max:3"}) == {"s": ["The s field must not be greater than 3 characters."]}
    assert errors({"l": [1, 2]}, {"l": "array|min:3"}) == {"l": ["The l field must have at least 3 items."]}
    assert errors({"n": 5}, {"n": "integer|between:1,4"}) == {"n": ["The n field must be between 1 and 4."]}
    assert errors({"s": "100"}, {"s": "max:3"}) == {}  # sans numeric : longueur

def test_size_missing_param_is_developer_error():
    with pytest.raises(ValueError, match="max.*s"):
        Validator({"s": "x"}, {"s": "max"}).fails()

def test_in_and_not_in():
    assert errors({"r": "admin"}, {"r": "in:user,editor"}) == {"r": ["The selected r is invalid."]}
    assert errors({"r": 1}, {"r": "in:1,2"}) == {}
    assert errors({"r": "root"}, {"r": "not_in:root"}) == {"r": ["The selected r is invalid."]}

def test_confirmed_and_same():
    assert errors({"password": "a", "password_confirmation": "b"}, {"password": "confirmed"}) == {"password": ["The password field confirmation does not match."]}
    v = Validator({"password": "a", "password_confirmation": "a"}, {"password": "confirmed"})
    assert v.validated() == {"password": "a"}
    assert errors({"a": "x", "b": "y"}, {"a": "same:b"}) == {"a": ["The a field must match b."]}

def test_regex_with_pipe_in_list_form():
    rules = {"c": ["regex:^(red|blue)$"]}
    assert errors({"c": "red"}, rules) == {}
    assert errors({"c": "green"}, rules) == {"c": ["The c field format is invalid."]}

def test_custom_messages_priority():
    msgs = {"required": "Need :attribute.", "email.required": "Email please."}
    assert errors({}, {"email": "required", "first_name": "required"}, msgs) == {"email": ["Email please."], "first_name": ["Need first name."]}

def test_custom_message_placeholders():
    assert errors({"s": "abcd"}, {"s": "max:3"}, {"max": ":attribute > :max"}) == {"s": ["s > 3"]}
```

- [ ] **Step 2: Run** `.venv/bin/pytest tests/validation/test_rules.py -q` — Expected: FAIL (unknown rule `max` → ValueError, etc.).
- [ ] **Step 3: Implement** the eight rules and message resolution; size messages pick `numeric` (field has `numeric`/`integer`), `array` (list/dict), else `string`; non-numeric params for size rules → `ValueError`.
- [ ] **Step 4: Run** `.venv/bin/pytest tests/validation -q` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: règles de taille, de valeurs et messages personnalisés (#15)"` (add the new test file first).

### Task 3: `unique` et `exists`

**Files:**
- Modify: `src/flask_artisan/validation.py`
- Test: `tests/validation/test_database_rules.py`

**Interfaces:**
- Consumes: `RULES`/`MESSAGES` (Task 1), façade `DB` (`DB.session`), fixture `db_app`.
- Produces: `unique:table[,colonne[,id_ignoré[,colonne_id]]]`, `exists:table[,colonne]` ; colonne par défaut = champ ; requête `select(literal(1)).select_from(table(t)).where(column(c) == value).limit(1)` (+ `column(id_col) != ignored`) via `DB.session.execute`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from flask_artisan.database import Mapped, Model
from flask_artisan.validation import Validator

class VUser(Model):
    email: Mapped[str]

@pytest.fixture
def app(db_app):
    app = db_app()
    with app.app_context():
        yield app

def errors(data, rules):
    return Validator(data, rules).errors()

def test_unique(app):
    u = VUser.create(email="a@x")
    assert errors({"email": "a@x"}, {"email": "unique:v_users"}) == {"email": ["The email has already been taken."]}
    assert errors({"email": "b@x"}, {"email": "unique:v_users,email"}) == {}
    assert errors({"email": "a@x"}, {"email": f"unique:v_users,email,{u.id}"}) == {}
    assert errors({"mail": "a@x"}, {"mail": f"unique:v_users,email,{u.id},id"}) == {}

def test_unique_sees_uncommitted_rows(app):
    from flask_artisan import DB
    with DB.transaction():
        VUser.create(email="t@x")
        assert errors({"email": "t@x"}, {"email": "unique:v_users"}) != {}

def test_exists(app):
    VUser.create(email="a@x")
    assert errors({"email": "a@x"}, {"email": "exists:v_users"}) == {}
    assert errors({"owner": "z@x"}, {"owner": "exists:v_users,email"}) == {"owner": ["The selected owner is invalid."]}

@pytest.mark.parametrize("rule", ["unique:v_users;drop,email", "exists:v_users,e mail", "unique"])
def test_bad_identifiers_rejected(app, rule):
    with pytest.raises(ValueError):
        Validator({"email": "a@x"}, {"email": rule}).fails()

def test_none_fails_unique_without_nullable(app):
    assert errors({"email": None}, {"email": "unique:v_users"}) != {}
```

(Le nom de table exact de `VUser` : vérifier `VUser.__tablename__` et l'utiliser dans les tests s'il diffère de `v_users`.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/validation/test_database_rules.py -q` — Expected: FAIL (unknown rule).
- [ ] **Step 3: Implement** the two rules (identifier regex check before building the query).
- [ ] **Step 4: Run** `.venv/bin/pytest tests/validation -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: règles unique et exists sur la session de la requête (#15)`.

### Task 4: `FormRequest` injectée, 403, source des données

**Files:**
- Modify: `src/flask_artisan/validation.py`
- Test: `tests/validation/test_form_request.py`

**Interfaces:**
- Consumes: `Validator`, `ValidationError` ; fixture `routed_app(declare)` ; `Route` façade ; `Container` autowire (`__init__(self)` sans paramètre).
- Produces:
  - `class AuthorizationError(HTTPException)` : `code = 403`, réponse `{"message": "This action is unauthorized."}`.
  - `class FormRequest` : `__init__(self)` (lève `RuntimeError` hors `has_request_context()`), `rules() -> dict` (abstraite au sens : `NotImplementedError` si non surchargée), `authorize() -> bool` (`True`), `messages() -> dict` (`{}`), `validated() -> dict`, `all() -> dict`, `input(key, default=None)`.
  - Données : `request.args.to_dict()` puis mise à jour avec le JSON (`get_json(silent=True)` si `dict`) sinon `request.form.to_dict()`.
  - Exports `__all__ = ["AuthorizationError", "FormRequest", "ValidationError", "Validator", "validate"]`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from flask import request as flask_request
from flask_artisan import Route
from flask_artisan.validation import FormRequest

calls = []

class StoreRequest(FormRequest):
    def rules(self):
        return {"title": "required|string|max:5", "id_echo": f"sometimes|in:{flask_request.view_args.get('id', '')}"}

class DenyRequest(FormRequest):
    def authorize(self):
        return False
    def rules(self):
        return {}

class Ctl:
    def store(self, request: StoreRequest):
        calls.append(request.validated())
        return request.validated(), 201
    def deny(self, request: DenyRequest):
        calls.append("deny")
        return "x"

@pytest.fixture
def client(routed_app):
    calls.clear()
    def routes():
        Route.post("/posts", [Ctl, "store"])
        Route.post("/posts/<id>", [Ctl, "store"])
        Route.post("/deny", [Ctl, "deny"])
    return routed_app(routes).test_client()

def test_valid_request_reaches_controller(client):
    r = client.post("/posts", json={"title": "Hi", "extra": 1})
    assert r.status_code == 201 and r.get_json() == {"title": "Hi"}

def test_invalid_request_is_422_and_controller_not_called(client):
    r = client.post("/posts", json={})
    assert r.status_code == 422
    assert r.get_json()["errors"] == {"title": ["The title field is required."]}
    assert calls == []

def test_unauthorized_is_403(client):
    r = client.post("/deny")
    assert r.status_code == 403 and r.get_json() == {"message": "This action is unauthorized."}
    assert calls == []

def test_form_and_query_sources(client):
    assert client.post("/posts?title=Query").get_json() == {"title": "Query"}
    assert client.post("/posts?title=Query", data={"title": "Form"}).get_json() == {"title": "Form"}

@pytest.mark.parametrize("body", ["[1]", "{broken"])
def test_non_object_json_is_empty_body(client, body):
    r = client.post("/posts", data=body, content_type="application/json")
    assert r.status_code == 422

def test_route_params_usable_in_rules(client):
    assert client.post("/posts/7", json={"title": "a", "id_echo": "7"}).status_code == 201
    assert client.post("/posts/7", json={"title": "a", "id_echo": "8"}).status_code == 422

def test_outside_request_is_an_error():
    with pytest.raises(RuntimeError):
        StoreRequest()
```

(Si la syntaxe de route réelle diffère de `Route.post(uri, [Classe, "méthode"])`, suivre celle de `tests/test_routing.py`.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/validation/test_form_request.py -q` — Expected: FAIL (`ImportError: FormRequest`).
- [ ] **Step 3: Implement** `AuthorizationError` and `FormRequest` per Interfaces.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` (toute la suite) — Expected: PASS.
- [ ] **Step 5: Commit** `feat: FormRequest validée à l'injection, 403 si authorize() est faux (#15)`.

### Task 5: `make:request`, squelette `LoginRequest`, docs

**Files:**
- Create: `src/flask_artisan/stubs/request.stub`, `src/flask_artisan/skeleton/app/http/requests/__init__.py`, `src/flask_artisan/skeleton/app/http/requests/login_request.py`
- Modify: `src/flask_artisan/console.py` (`make_request` + `COMMANDS`), `src/flask_artisan/skeleton/app/http/controllers/auth_controller.py`, `tests/test_console.py`, `tests/test_cli.py` (`AUTH_FLOW`), `README.md`, `CLAUDE.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `write_stub(folder, name, stub, force=...)`, `FormRequest`.
- Produces: `flask make:request Nom [--force]` → `app/http/requests/<snake>.py`, sous-dossiers permis.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_console.py` :
    ```python
    def test_make_request(artisan):
        from flask_artisan.validation import FormRequest
        app, run = artisan
        result = run("make:request", "StorePostRequest")
        assert result.exit_code == 0, result.output
        path = app.base_path("app/http/requests/store_post_request.py")
        assert issubclass(load(path).StorePostRequest, FormRequest)
        assert_ruff_clean(path)
    ```
  - `tests/test_cli.py` `AUTH_FLOW` : remplacer les trois lignes `401` des corps invalides par
    ```python
    r = c.post("/api/login")
    assert r.status_code == 422 and set(r.get_json()["errors"]) == {"email", "password"}, r.data
    assert c.post("/api/login", json=[1]).status_code == 422
    assert c.post("/api/login", json={"email": "a@x", "password": 1}).status_code == 422
    ```
    (garder la ligne `"bad"` → 401).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console.py::test_make_request tests/test_cli.py::test_generated_api_auth_flow -q` — Expected: FAIL (`No such command 'make:request'`, puis 401 ≠ 422).
- [ ] **Step 3: Implement**
  - stub `request.stub` : `class $class_name(FormRequest)` avec `rules()` qui rend `{}` et un exemple commenté `# "title": "required|string|max:255",`, `authorize()` qui rend `True`.
  - `make_request` calqué sur `make_controller` (dossier `app/http/requests`).
  - `LoginRequest` : `email: required|string|email`, `password: required|string`, `device_name: sometimes|string|max:255` ; `AuthController.login(self, request: LoginRequest)` lit `request.validated()`, garde la réponse 401 `Invalid credentials.` et `device_name or "api"`.
  - README : section « Validation » (exemple FormRequest, `validate()`, tableau des règles, format 422/403), `make:request` dans « Console », case validation cochée dans la feuille de route ; CLAUDE.md : puce « Validation » dans Architecture (`FormRequest.__init__` valide → autowiring du conteneur suffit ; `ValidationError`/`AuthorizationError` sont des `HTTPException` qui portent leur réponse JSON ; `unique`/`exists` via `DB.session`) ; CHANGELOG : `## [Non publié]` avec « Ajouté : validation… » et « Modifié : `/api/login` répond 422 aux corps invalides ».
- [ ] **Step 4: Run** `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .` — Expected: tout passe.
- [ ] **Step 5: Commit** `feat: make:request et LoginRequest dans le squelette, docs validation (#15)`.
