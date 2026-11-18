# GH-1 Socle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer l'ébauche par un package pip `flask-artisan` (Application = Flask + conteneur, providers, config, env, façades, helpers) et une commande `artisan new` qui génère un projet prêt à `flask run`.

**Architecture:** `Application` hérite de `Flask` et de `Container`. Au constructeur : `.env` → `Repository` de config → pont vers `app.config` → enregistrement dans le conteneur → providers (register puis boot). Façades et helpers résolvent via `Application.get_instance()`. Le squelette de projet vit dans `src/flask_artisan/skeleton/` et est copié par `artisan new`.

**Tech Stack:** Python ≥ 3.10, Flask ≥ 3, python-dotenv, click (fourni par Flask), pytest, ruff, setuptools (pyproject), GitHub Actions.

**Spec:** `docs/superpowers/specs/GH-1-spec.md` — à lire avant chaque tâche.

## Global Constraints

- Branche `feat/1-socle` ; chaque message de commit se termine par `(#1)`.
- `requires-python = ">=3.10"` ; dépendances runtime : `flask>=3.0`, `python-dotenv>=1.0` — **rien d'autre**.
- Extra `dev` : `pytest>=8`, `ruff>=0.6`.
- Version `0.1.0.dev0`, nom de distribution `flask-artisan`, package d'import `flask_artisan`, entry point `artisan = flask_artisan.cli:main`.
- Noms d'API repris de Laravel : `bind`, `singleton`, `instance`, `make`, `bound`, `register`, `boot`, `config()`, `env()`, `app()`, `base_path()`.
- Pas de publication PyPI ; le `requirements.txt` du squelette contient `flask-artisan @ git+https://github.com/ahoblepierre/flask-artisan`.
- Messages d'erreur destinés aux utilisateurs en français.
- `ruff check .` et `ruff format --check .` passent à la fin de chaque tâche.

## Review Focus

1. **Deux `Application` créées dans le même process** (tests, usines d'app) : façades et helpers doivent suivre la plus récente → test dans Task 5.
2. **Projet sans fichier `.env`** : l'app démarre, `env()` renvoie les défauts (seule l'absence d'`APP_KEY` est bloquante) → test dans Task 4.
3. **Fichier `config/x.py` cassé ou sans dict `config`** : erreur qui nomme le fichier, pas un `AttributeError` brut → test dans Task 2.
4. **Même provider listé deux fois** : enregistré et booté une seule fois → test dans Task 4.
5. **Variables `FLASK_*` / `APP_*` déjà présentes dans l'environnement du développeur** : elles priment sur `.env` (python-dotenv sans override), et les tests du projet généré doivent s'en isoler → env nettoyé dans les tests de Task 6.

---

### Task 1: Nettoyage du repo et ossature du package

**Files:**
- Delete: `app/`, `app.py`, `setup.py`, `requirements.txt`, `MANIFEST.in`, `migrations/`, `instance/`, `build/`, `dist/`, `flask_lara_app.egg-info/`, `__pycache__/`, tous les `.DS_Store` (`git rm -r`)
- Create: `pyproject.toml`, `src/flask_artisan/__init__.py`, `tests/test_package.py`, `.github/workflows/ci.yml`
- Modify: `.gitignore`, `.env.example` (supprimer : il sera dans le squelette)

**Interfaces:**
- Produces: package importable `flask_artisan` avec `__version__ = "0.1.0.dev0"`.

- [ ] **Step 1: Supprimer l'ébauche** avec `git rm -r` sur la liste ci-dessus. `.gitignore` devient : `.env`, `venv/`, `.venv/`, `__pycache__/`, `*.egg-info/`, `build/`, `dist/`, `.DS_Store`, `.pytest_cache/`, `.ruff_cache/`, `instance/`.

- [ ] **Step 2: Écrire `pyproject.toml`**
  - `[build-system]` setuptools>=69 ; `[project]` selon Global Constraints, `readme = "README.md"`, `license = {text = "MIT"}`.
  - `[tool.setuptools.packages.find] where = ["src"], include = ["flask_artisan"]` (le squelette ne doit **pas** devenir un sous-package).
  - `[tool.setuptools.package-data] flask_artisan = ["skeleton/**/*", "skeleton/.env.example", "skeleton/.gitignore"]` (les globs n'attrapent pas les dotfiles).
  - `[tool.ruff] line-length = 100, target-version = "py310"` ; `[tool.pytest.ini_options] testpaths = ["tests"]`.

- [ ] **Step 3: Test**

```python
def test_package_importable():
    import flask_artisan
    assert flask_artisan.__version__ == "0.1.0.dev0"
```

- [ ] **Step 4: Installer et lancer** : `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]" && pytest` → 1 passed.

- [ ] **Step 5: CI** `.github/workflows/ci.yml` : sur push et pull_request, matrice Python 3.10/3.11/3.12/3.13, `pip install -e ".[dev]"`, `ruff check .`, `ruff format --check .`, `pytest`.

- [ ] **Step 6: Commit** `chore: remplace l'ébauche par l'ossature du package flask-artisan (#1)`

---

### Task 2: `env()` et `Repository` de configuration

**Files:**
- Create: `src/flask_artisan/env.py`, `src/flask_artisan/config.py`, `tests/test_env.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `env(key: str, default: Any = None) -> Any`
  - `load_env_file(path: Path) -> None` (python-dotenv, `override=False`, silencieux si le fichier n'existe pas)
  - `class Repository: __init__(items: dict | None = None)`, `get(key: str, default=None)`, `set(key: str, value) -> None`, `has(key: str) -> bool`, `all() -> dict`, `@classmethod from_directory(path: Path) -> Repository`
  - `class ConfigError(Exception)`

- [ ] **Step 1: Tests `env`** (avec `monkeypatch.setenv`) :

```python
@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("(true)", True), ("TRUE", True),
    ("false", False), ("(false)", False),
    ("null", None), ("(null)", None),
    ("empty", ""), ("(empty)", ""),
    ('"hello"', "hello"), ("'hello'", "hello"), ("plain", "plain"),
])
def test_env_casts(monkeypatch, raw, expected):
    monkeypatch.setenv("LF_TEST", raw)
    assert env("LF_TEST") == expected

def test_env_default_when_missing(monkeypatch):
    monkeypatch.delenv("LF_TEST", raising=False)
    assert env("LF_TEST", "fallback") == "fallback"

def test_load_env_file_does_not_override(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LF_A=from_file\nLF_B=from_file\n")
    monkeypatch.setenv("LF_A", "from_os")
    monkeypatch.delenv("LF_B", raising=False)
    load_env_file(tmp_path / ".env")
    assert env("LF_A") == "from_os" and env("LF_B") == "from_file"

def test_load_env_file_missing_is_silent(tmp_path):
    load_env_file(tmp_path / ".env")
```

- [ ] **Step 2: Tests `Repository`** :
  - `test_dot_notation` : `Repository({"app": {"db": {"host": "x"}}}).get("app.db.host") == "x"`
  - `test_default` : clé absente → défaut ; `get("app.name.deep")` quand `app.name` est une chaîne → défaut.
  - `test_set_creates_nested` : `set("a.b.c", 1)` puis `get("a.b.c") == 1`.
  - `test_has` vrai/faux.
  - `test_from_directory` : `config/app.py` = `config = {"name": "Blog"}`, `config/flask.py` = `config = {"X": 1}`, `config/_private.py` ignoré → `all() == {"app": {"name": "Blog"}, "flask": {"X": 1}}`.
  - `test_missing_config_dict` : fichier sans `config` → `ConfigError` dont le message contient `"app.py"`.
  - `test_syntax_error` : fichier invalide → `ConfigError` dont le message contient le nom du fichier.
  - `test_from_missing_directory` : dossier absent → `Repository` vide.

- [ ] **Step 3: Vérifier l'échec** : `pytest tests/test_env.py tests/test_config.py` → ImportError.

- [ ] **Step 4: Implémenter.** Chargement des fichiers avec `importlib.util.spec_from_file_location(f"flask_artisan_config_{name}", path)` (jamais par nom de module), ordre alphabétique, fichiers `_*.py` ignorés.

- [ ] **Step 5: Vérifier** : `pytest` → tout passe.

- [ ] **Step 6: Commit** `feat: env() et Repository de configuration (#1)`

---

### Task 3: Conteneur de services

**Files:**
- Create: `src/flask_artisan/container.py`, `tests/test_container.py`

**Interfaces:**
- Produces:
  - `class Container` : `bind(abstract, concrete=None) -> None`, `singleton(abstract, concrete=None) -> None`, `instance(abstract, obj) -> Any`, `make(abstract, **params) -> Any`, `bound(abstract) -> bool`
  - `class BindingResolutionError(Exception)`
  - `abstract : type | str` ; `concrete : type | Callable[[Container], Any] | None`
  - Tout état interne préfixé `_container_` (ex. `_container_bindings`) pour ne jamais entrer en collision avec un attribut de `Flask`.

- [ ] **Step 1: Tests** (classes d'exemple locales au fichier de test) :
  - `test_make_unbound_class_autowires` : `class A: ...`, `class B: def __init__(self, a: A)` → `make(B).a` est un `A`.
  - `test_bind_returns_new_instance_each_time`.
  - `test_singleton_returns_same_instance`.
  - `test_instance_registers_object`.
  - `test_closure_receives_container` : `bind("x", lambda c: c)` → `make("x") is container`.
  - `test_bind_interface_to_implementation` : `bind(Base, Impl)` → `isinstance(make(Base), Impl)`.
  - `test_params_override` : `make(B, a=sentinel).a is sentinel`.
  - `test_default_value_used_for_unresolvable` : `def __init__(self, name: str = "x")` → `make(C).name == "x"`.
  - `test_unresolvable_raises` : `def __init__(self, name: str)` → `BindingResolutionError`, message contient `"C"` et `"name"`.
  - `test_unknown_string_raises` : `make("nope")` → `BindingResolutionError`.
  - `test_circular_dependency_raises` : `X(y: "Y")`, `Y(x: X)` (annotations résolues au niveau module) → `BindingResolutionError` contenant `"circulaire"`, pas `RecursionError`.
  - `test_singleton_thread_safe` : `singleton(Slow)` où `Slow.__init__` fait `time.sleep(0.01)` et incrémente un compteur ; 20 threads appellent `make(Slow)` → compteur == 1.
  - `test_bound`.

- [ ] **Step 2: Vérifier l'échec** : `pytest tests/test_container.py` → ImportError.

- [ ] **Step 3: Implémenter.** Autowiring via `inspect.signature(cls.__init__)` + `typing.get_type_hints(cls.__init__)` ; ignorer `self`, `*args`, `**kwargs`. Pile de résolution pour la détection de cycle ; `threading.RLock` autour de la création des singletons.

- [ ] **Step 4: Vérifier** : `pytest` → tout passe.

- [ ] **Step 5: Commit** `feat: conteneur de services avec autowiring (#1)`

---

### Task 4: `Application`, `ServiceProvider` et helpers

**Files:**
- Create: `src/flask_artisan/application.py`, `src/flask_artisan/providers.py`, `src/flask_artisan/helpers.py`, `tests/test_application.py`, `tests/test_helpers.py`, `tests/conftest.py`
- Modify: `src/flask_artisan/__init__.py` (exports)

**Interfaces:**
- Consumes: `Container` (Task 3), `Repository`, `load_env_file`, `env` (Task 2).
- Produces:
  - `class Application(Flask, Container)` : `__init__(base_path: str | Path)`, `register(provider_class: type[ServiceProvider]) -> ServiceProvider`, `boot() -> None`, `base_path(path="") -> Path`, `config_path(path="") -> Path`, `app_path(path="") -> Path`, `environment() -> str`, `@classmethod get_instance() -> Application`, `@classmethod set_instance(app: Application | None) -> None`
  - `class ServiceProvider` : `__init__(app)`, `register()`, `boot()`
  - Helpers : `app(abstract=None, **params)`, `config(key=None, default=None)`, `base_path(path="") -> Path`
  - `flask_artisan.__init__` exporte : `Application, Container, BindingResolutionError, ServiceProvider, Repository, env, app, config, base_path, __version__` (les façades s'ajoutent en Task 5).
  - Clés conteneur : `"app"` et `Application` → l'app ; `"config"` et `Repository` → le repository.

- [ ] **Step 1: Fixture `make_project(tmp_path)`** dans `conftest.py` : écrit `config/app.py` (`name`, `env="testing"`, `debug=False`, `key="test-key"`, `providers=[]`) avec possibilité de surcharger, et un `.env` optionnel ; fixture autouse qui fait `Application.set_instance(None)` après chaque test.

- [ ] **Step 2: Tests `Application`** :
  - `test_is_a_flask_app` : `isinstance(app, Flask)` et `app.test_client()` fonctionne.
  - `test_no_flask_attribute_shadowed` : `{n for n in dir(Container) if not n.startswith("__")} & set(dir(Flask)) == set()`.
  - `test_bridge` : `app.config["SECRET_KEY"] == "test-key"`, `app.config["DEBUG"] is False`, et `config/flask.py` = `config = {"SQLALCHEMY_DATABASE_URI": "sqlite://"}` → `app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"`.
  - `test_env_file_loaded` : `.env` avec `APP_NAME=FromEnv`, `config/app.py` utilise `env("APP_NAME")` → `config("app.name") == "FromEnv"` (nettoyer `APP_NAME` via monkeypatch).
  - `test_without_env_file` : pas de `.env`, clé en dur dans la config → l'app démarre.
  - `test_missing_key_raises` : `key=""` → `RuntimeError` contenant `"APP_KEY"`.
  - `test_container_keys` : `app.make("app") is app`, `app.make(Repository) is app.make("config")`.
  - `test_register_then_boot_order` : deux providers listés dans `providers` ajoutent leur nom dans une liste partagée → `["register:A", "register:B", "boot:A", "boot:B"]`.
  - `test_register_after_boot_boots_immediately`.
  - `test_duplicate_provider_registered_once` : même classe listée deux fois → un seul `register` et un seul `boot`.
  - `test_paths` : `base_path("x") == tmp_path / "x"`, `config_path() == tmp_path / "config"`, `app_path() == tmp_path / "app"`.
  - `test_environment` : `"testing"`.
  - `test_instance_path_inside_project` : `app.instance_path == str(tmp_path / "instance")`.

- [ ] **Step 3: Tests helpers** : `test_helpers_without_app_raise` (`RuntimeError` contenant `"Aucune application"`), `test_app_helper`, `test_config_helper` (clé, défaut, sans argument → `Repository`), `test_base_path_helper`.

- [ ] **Step 4: Vérifier l'échec** : `pytest tests/test_application.py tests/test_helpers.py`.

- [ ] **Step 5: Implémenter** dans l'ordre exact de la spec (section Application, étapes 1 à 7). `Flask.__init__(import_name=base_path.name, root_path=str(base_path), instance_path=str(base_path / "instance"))` ; appeler `Container.__init__(self)` explicitement avant.

- [ ] **Step 6: Vérifier** : `pytest` → tout passe.

- [ ] **Step 7: Commit** `feat: Application, ServiceProvider et helpers (#1)`

---

### Task 5: Façades

**Files:**
- Create: `src/flask_artisan/facades.py`, `tests/test_facades.py`
- Modify: `src/flask_artisan/__init__.py` (exporter `Facade`, `App`, `Config`)

**Interfaces:**
- Consumes: `Application.get_instance()`, `make` (Task 4).
- Produces: `class Facade(metaclass=FacadeMeta)` avec attribut de classe `accessor: str | type` ; `App` (`accessor = "app"`), `Config` (`accessor = "config"`).

- [ ] **Step 1: Tests** :
  - `test_config_facade` : `Config.get("app.name") == "Blog"`.
  - `test_app_facade` : `App.environment() == "testing"`.
  - `test_custom_facade` : `class Greeter: def hi(self): return "hi"` ; `app.singleton(Greeter)` ; `class G(Facade): accessor = Greeter` → `G.hi() == "hi"`.
  - `test_follows_latest_application` : deux apps créées successivement avec des `name` différents → `Config.get("app.name")` renvoie celui de la seconde.
  - `test_no_cache_after_rebind` : `app.instance(Greeter, autre)` après un premier appel → la façade utilise `autre`.
  - `test_without_app_raises` : `RuntimeError` contenant `"Aucune application"`.

- [ ] **Step 2: Vérifier l'échec**, **Step 3: Implémenter** (`FacadeMeta.__getattr__` → `getattr(Application.get_instance().make(cls.accessor), name)`), **Step 4: Vérifier** : `pytest` → tout passe.

- [ ] **Step 5: Commit** `feat: façades App et Config (#1)`

---

### Task 6: Squelette et `artisan new`

**Files:**
- Create: `src/flask_artisan/cli.py`, `src/flask_artisan/skeleton/` (arborescence de la spec, section « Squelette et `artisan new` »), `tests/test_cli.py`

**Interfaces:**
- Consumes: tout ce qui précède, via le projet généré.
- Produces: `main()` (groupe click `artisan`) avec la commande `new NAME`.

Contenu fixé du squelette :
- `.env.example` : `APP_NAME=`, `APP_ENV=local`, `APP_DEBUG=true`, `APP_KEY=`, `FLASK_DEBUG=${APP_DEBUG}`.
- `config/app.py` : `name=env("APP_NAME", "Flask-Artisan")`, `env=env("APP_ENV", "production")`, `debug=env("APP_DEBUG", False)`, `key=env("APP_KEY", "")`, `providers=[AppServiceProvider]`.
- `config/flask.py` : `config = {}` avec un commentaire d'exemple.
- `app/providers/app_service_provider.py` : `AppServiceProvider.boot()` déclare `GET /` → `{"app": config("app.name")}` avec `@self.app.route`.
- `bootstrap/app.py` : `app = Application(Path(__file__).resolve().parent.parent)`.
- `wsgi.py` : `from bootstrap.app import app  # noqa: F401`.
- `tests/test_app.py` : `GET /` renvoie 200.
- `requirements.txt` : la ligne git des Global Constraints.
- `.gitignore` : `.env`, `venv/`, `.venv/`, `__pycache__/`, `instance/`.

- [ ] **Step 1: Tests** (projet généré via `CliRunner().invoke(main, ["new", str(tmp_path / "blog")])`) ; les vérifications du projet généré passent par `subprocess.run([sys.executable, ...], cwd=projet, env=env_propre)` où `env_propre` est `os.environ` sans aucune clé commençant par `FLASK_` ou `APP_` (isole des modules `app`/`bootstrap` et de l'environnement du développeur) :
  - `test_new_creates_project` : code 0 ; `wsgi.py`, `bootstrap/app.py`, `config/app.py`, `.env`, `.env.example`, `.gitignore` existent.
  - `test_env_has_key_and_name` : `.env` contient `APP_NAME=blog` et une ligne `APP_KEY=` suivie de 64 caractères hexadécimaux ; deux projets générés ont des clés différentes.
  - `test_refuses_non_empty_dir` : dossier existant avec un fichier → code ≠ 0, message contenant `"n'est pas vide"`, fichier intact.
  - `test_accepts_existing_empty_dir`.
  - `test_generated_app_responds` : `python -c "from wsgi import app; r = app.test_client().get('/'); print(r.status_code, r.get_json())"` → sortie contient `200` et `'blog'`.
  - `test_flask_run_path_debug` : `python -m flask shell` avec `input="print('DEBUG=' + str(app.debug))\n"` → sortie contient `DEBUG=True` ; puis en remplaçant `APP_DEBUG=true` par `APP_DEBUG=false` dans `.env` → `DEBUG=False`.
  - `test_generated_project_tests_pass` : `python -m pytest -q` dans le projet → code 0.

- [ ] **Step 2: Vérifier l'échec** : `pytest tests/test_cli.py`.

- [ ] **Step 3: Implémenter `cli.py`** : copie de `importlib.resources.files("flask_artisan") / "skeleton"` avec `shutil.copytree(..., dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))` ; `.env` = `.env.example` avec `APP_NAME=<nom du dossier>` et `APP_KEY=<secrets.token_hex(32)>` ; affiche `cd <nom>` et `flask run`.

- [ ] **Step 4: Vérifier** : `pytest` → tout passe.

- [ ] **Step 5: Vérifier le wheel** : `pip wheel . --no-deps -w /tmp/lf-wheel && unzip -l /tmp/lf-wheel/flask_artisan-*.whl | grep skeleton/` → liste contient `skeleton/.env.example`, `skeleton/.gitignore`, `skeleton/wsgi.py` ; puis dans un venv neuf : `pip install /tmp/lf-wheel/flask_artisan-*.whl && artisan new /tmp/lf-demo && cd /tmp/lf-demo && flask run` → `curl http://127.0.0.1:5000/` répond `{"app": "lf-demo"}`.

- [ ] **Step 6: Commit** `feat: squelette de projet et commande artisan new (#1)`

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`, `CLAUDE.md` (section Commandes et Architecture : remplacer l'état « ébauche » par le nouveau socle ; retirer « Pièges connus de l'ébauche »)
- Create: `CONTRIBUTING.md`

- [ ] **Step 1: README** : pitch « Laravel, mais c'est du Flask », installation (via git tant que PyPI n'est pas publié), `artisan new`, exemples courts conteneur / provider / config / façade (repris des tests), feuille de route v0.1, licence MIT.

- [ ] **Step 2: CONTRIBUTING.md** : `pip install -e ".[dev]"`, `pytest`, `pytest tests/test_container.py::test_bound`, `ruff check . && ruff format .`, conventions issues / branches / PR (copiées du `CLAUDE.md`).

- [ ] **Step 3: Vérifier** que chaque commande citée dans README et CONTRIBUTING tourne telle quelle.

- [ ] **Step 4: Commit** `docs: README, CONTRIBUTING et CLAUDE.md pour le socle (#1)`
