# CLI — plan d'implémentation

> **Pour les agents :** sous-skill requis : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**But :** générateurs `flask make:controller|model|middleware|provider|command`, découverte des commandes Click de `app/console/commands/` (seulement côté CLI) et `flask route:list`.

**Architecture :**
- Un module `flask_artisan/console.py` contient les commandes du framework et le groupe `ArtisanGroup(AppGroup)`.
- `Application.__init__` remplace `self.cli` par un `ArtisanGroup` et y ajoute les commandes du framework.
- `ArtisanGroup` importe les commandes du projet à la première demande `list_commands` ou `get_command`. Le serveur web ne les importe donc jamais.
- Les modèles de fichiers sont dans `flask_artisan/stubs/*.stub` (`string.Template`).
- Le `Router` garde, au `flush`, la liste de ce qu'il a enregistré (`self.registered`) pour `route:list`.

**Stack :** Python ≥ 3.10, Flask ≥ 3 (`flask.cli.AppGroup`, `with_appcontext`), click, pytest, ruff. Aucune nouvelle dépendance.

**Spec :** [docs/superpowers/specs/GH-9-spec.md](../specs/GH-9-spec.md)

## Contraintes globales

- Aucun fichier n'est écrasé sans `--force`. Message : `Le fichier <chemin relatif> existe déjà (--force pour l'écraser).`
- Pas d'édition automatique de `config/app.py` ni du kernel : on affiche seulement la ligne à ajouter.
- `make:model` et `make:command` refusent un nom qui contient `/`.
- La découverte ne tourne que côté CLI. Un fichier cassé dans `app/console/commands/` n'empêche pas `Application(...)` de se construire.
- Un fichier généré passe `ruff check` et `ruff format --check` avec `pyproject.toml` du repo.
- Messages en français.
- Tout attribut ajouté à `Application` passe les tests « aucun attribut Flask masqué ». Remplacer `self.cli` est voulu : c'est un attribut de Flask qu'on réassigne, pas un nom nouveau.
- Commits : `feat: … (#9)`, `docs: … (#9)`. Lancer `.venv/bin/ruff check . && .venv/bin/ruff format --check .` avant chaque commit.

## Review Focus

1. **Nom en sigles ou avec suffixe.** `HTTPClient` → `http_client.py` ; `make:command SendEmails` → `app:send-emails` ; `HTTPPing` → `app:http-ping` (tâches 1 et 2).
2. **Nom invalide.** `""`, `"1Foo"`, `"Foo-Bar"`, `"Admin/"`, `"../Evil"` → erreur Click, rien n'est écrit hors du dossier cible (tâche 1).
3. **Commande du projet qui utilise un modèle.** Elle doit tourner dans l'app context (`User.all()` marche) (tâche 3).
4. **Fichier cassé dans `app/console/commands/`.** `Application(...)` et le client de test marchent ; `flask --help` échoue avec le nom du fichier (tâche 3).
5. **`route:list` sur des routes en groupe avec `auth:api` et des routes `Route.resource`.** Le nom, l'action et `Authenticate:api` sont exacts (tâche 4).

## Fichiers

| Fichier | Rôle |
|---|---|
| `src/flask_artisan/console.py` | `ArtisanGroup`, `class_to_file(name) -> str`, `split_name`, `write_stub`, commandes `make:*`, `route:list`, `COMMANDS` |
| `src/flask_artisan/stubs/*.stub` | `controller`, `controller.resource`, `model`, `middleware`, `provider`, `command` |
| `src/flask_artisan/application.py` | `self.cli = ArtisanGroup()` + `add_command` |
| `src/flask_artisan/routing.py` | `Router.registered` |
| `pyproject.toml` | `"stubs/*"` dans `package-data` |
| `src/flask_artisan/skeleton/app/console/__init__.py`, `…/commands/__init__.py` | dossiers du squelette |
| `tests/test_console.py`, `tests/test_route_list.py` | tests |
| `tests/test_cli.py` | bout en bout |
| `README.md`, `CLAUDE.md` | doc |

## Fixture de test (tâche 1)

Dans `tests/test_console.py`, `artisan(make_project)` crée `Application(make_project())` et renvoie `(app, run)`, où `run(*args)` vaut `app.test_cli_runner().invoke(args=list(args))`. Le projet est un dossier temporaire : les fichiers générés y sont écrits.

---

### Task 1: noms, écriture des stubs, `make:controller`, branchement dans `Application`

**Files:**
- Create: `src/flask_artisan/console.py`, `src/flask_artisan/stubs/controller.stub`, `src/flask_artisan/stubs/controller.resource.stub`, `tests/test_console.py`
- Modify: `src/flask_artisan/application.py`, `pyproject.toml`

**Interfaces:**
- Produces :
  - `class_to_file(name: str) -> str` : CamelCase → snake_case, sigles compris (`UserController` → `user_controller`, `HTTPClient` → `http_client`, `EnsureJSONBody` → `ensure_json_body`) ;
  - `split_name(name: str, allow_dirs: bool) -> tuple[list[str], str]` : `"Admin/UserController"` → `(["admin"], "UserController")`. Lève `click.BadParameter` si une partie n'est pas un identifiant Python ou commence par une minuscule pour la classe, si une partie est vide, ou si `/` est présent alors que `allow_dirs=False` ;
  - `write_stub(app, folder: str, name: str, stub: str, *, force: bool, allow_dirs: bool = True, **values) -> Path` : crée les sous-dossiers avec leur `__init__.py`, refuse un fichier existant sans `force`, remplit le stub avec `class_name` plus `values`, affiche `Créé : <chemin relatif>` et renvoie le chemin ;
  - commande `make:controller NAME [--resource] [--force]` ;
  - `COMMANDS: list[click.Command]` ;
  - `class ArtisanGroup(AppGroup)` (la découverte arrive en tâche 3).

- [ ] **Step 1: Write the failing tests** in `tests/test_console.py` :
  - `test_class_to_file`, paramétré sur les trois exemples ci-dessus ;
  - `test_make_controller_creates_importable_class` : le fichier `app/http/controllers/photo_controller.py` existe ; chargé avec `importlib.util.spec_from_file_location`, il a `PhotoController().index` ; la sortie contient `Créé : app/http/controllers/photo_controller.py` ;
  - `test_make_controller_resource_has_seven_methods` : `index`, `create`, `store`, `show`, `edit`, `update`, `destroy`, et `show` accepte `id` ;
  - `test_make_controller_subfolder` : `Admin/UserController` → `app/http/controllers/admin/__init__.py` et `admin/user_controller.py` ;
  - `test_existing_file_needs_force` : le second appel donne exit ≠ 0 avec `existe déjà` et le fichier n'est pas modifié ; avec `--force`, il est réécrit ;
  - `test_invalid_names_rejected`, paramétré sur `""`, `"1Foo"`, `"Foo-Bar"`, `"Admin/"`, `"../Evil"`, `"photo"` : exit ≠ 0, et aucun fichier n'est créé sous le projet en dehors de `config/` ;
  - `test_generated_controller_passes_ruff` : `subprocess.run([sys.executable, "-m", "ruff", "check", "--config", REPO/"pyproject.toml", path])` puis la même chose avec `format --check` → code 0, pour les deux variantes.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console.py -q`. Attendu : ImportError ou `No such command 'make:controller'`.
- [ ] **Step 3: Implement.**
  - Écrire `console.py` et les deux stubs.
  - Dans `Application.__init__`, juste avant le bloc des providers : `self.cli = ArtisanGroup(self.name)` (ou équivalent), puis `for cmd in COMMANDS: self.cli.add_command(cmd)`. Les commandes ajoutées par les providers, comme celles de migration, arrivent après et ne sont pas perdues.
  - Ajouter `"stubs/*"` à `package-data`.
  - Le dossier cible est relatif à `app.base_path()`. Comme `split_name` n'accepte que des identifiants, `..` est impossible.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Attendu : vert. Les commandes de migration sont toujours là (`test_migrations`).
- [ ] **Step 5: Commit**, avec la spec, le plan et CLAUDE.md : `feat: flask make:controller et socle des générateurs (#9)`.

### Task 2: `make:model`, `make:middleware`, `make:provider`, `make:command`

**Files:**
- Create: `src/flask_artisan/stubs/model.stub`, `middleware.stub`, `provider.stub`, `command.stub`
- Modify: `src/flask_artisan/console.py`, `tests/test_console.py`

**Interfaces:**
- Consumes : `write_stub`, `split_name`, `class_to_file`, `_table_name` (from `flask_artisan.database.model`).
- Produces :
  - `make:model NAME [--force]` → `app/models/`, sans sous-dossier. Ensuite, affiche `Ajoutez vos colonnes, puis : flask make:migration "create <table>"`, où `<table>` est `_table_name(NAME)`.
  - `make:middleware NAME [--force]` → `app/http/middleware/`. Ensuite, affiche `Déclarez-le dans app/http/kernel.py : "<alias>": <Classe>`, avec l'alias = `class_to_file(NAME)`.
  - `make:provider NAME [--force]` → `app/providers/`. Ensuite, affiche `Ajoutez-le à "providers" dans config/app.py : <Classe>`, avec la ligne d'import.
  - `make:command NAME [--command TEXT] [--force]` → `app/console/commands/`, sans sous-dossier. Le nom par défaut est `"app:" + class_to_file(NAME).replace("_", "-")`. La fonction générée s'appelle `class_to_file(NAME)` et affiche un message d'exemple avec `click.echo`.

- [ ] **Step 1: Write the failing tests** :
  - `test_make_model` : le fichier `app/models/blog_post.py` existe ; chargé dans un module unique (`project_modules`), la classe `BlogPost` est un `Model` ; la sortie contient `create blog_posts` ; aucun fichier de migration n'est créé ;
  - `test_make_middleware` : la classe a `handle(self, request, next)`, `BeforeMiddleware().handle(req, lambda r: "ok")` renvoie `"ok"`, et l'alias est affiché ;
  - `test_make_provider` : la classe hérite de `ServiceProvider` ; la ligne pour `config/app.py` est affichée ;
  - `test_make_command_default_name` : `SendEmails` → `send_emails.py` ; dans le module, l'objet `send_emails` est un `click.Command` nommé `app:send-emails` ; pour `HTTPPing` → `app:http-ping` ;
  - `test_make_command_custom_name` : `--command mail:send` ;
  - `test_model_and_command_refuse_subfolders`, paramétré : exit ≠ 0, avec un message qui mentionne le sous-dossier ;
  - `test_generated_files_pass_ruff` : les quatre stubs passent ruff.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console.py -q`. Attendu : les nouveaux tests échouent avec `No such command`.
- [ ] **Step 3: Implement** les quatre commandes et les quatre stubs.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Step 5: Commit** `feat: flask make:model, make:middleware, make:provider, make:command (#9)`.

### Task 3: découverte des commandes du projet

**Files:**
- Modify: `src/flask_artisan/console.py`
- Create: `tests/test_console_discovery.py`

**Interfaces:**
- Consumes : `Application.base_path()` ; `project_modules` (tests).
- Produces : `ArtisanGroup.list_commands(ctx)` et `get_command(ctx, name)` appellent d'abord `self._discover()`, une seule fois par groupe.
  - `_discover()` met la racine du projet dans `sys.path` s'il le faut, comme `import_models`.
  - Il importe `app.console.commands.<stem>` pour chaque `*.py` sauf `__init__`, en ordre alphabétique.
  - Pour chaque valeur du module qui est un `click.Command`, il appelle `self.add_command(with_appcontext(cmd))`, ou enveloppe le callback pour l'exécuter dans `app.app_context()`.
  - Une exception à l'import devient `click.ClickException(f"Erreur dans app/console/commands/{stem}.py : {exc}")`, chaînée à l'exception d'origine.
  - Le groupe connaît son app : passer `app` au constructeur ou le lire via `current_app` dans le contexte de `flask`. Le choix revient au constructeur, mais la découverte doit marcher depuis `app.test_cli_runner()`.

- [ ] **Step 1: Write the failing tests**, dans un projet `make_project()` qui contient `app/__init__.py`, `app/console/__init__.py` et `app/console/commands/__init__.py`, sous `project_modules(root)` :
  - `test_project_command_runs` : le fichier `hello.py` contient `@click.command("app:hello")`, qui affiche `config("app.name")`. `run("app:hello")` → exit 0 et `Blog` dans la sortie ;
  - `test_project_command_has_app_context` : la commande fait `click.echo(current_app.name)` sans contexte poussé à la main → exit 0 ;
  - `test_listed_in_help` : `run("--help")` contient `app:hello` ;
  - `test_broken_command_file_does_not_break_app` : avec `broken.py` = `raise RuntimeError("boom")`, `Application(root)` se construit et `app.test_client().get("/")` ne lève pas d'erreur (un 404 est accepté) ; `run("--help")` donne exit ≠ 0, et la sortie contient `app/console/commands/broken.py` et `boom` ;
  - `test_missing_folder_is_fine` : sans `app/console/commands/`, `run("--help")` → exit 0 ;
  - `test_non_command_values_ignored` : un module qui définit aussi une fonction et une constante n'ajoute que la commande.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console_discovery.py -q`. Attendu : FAIL (`No such command 'app:hello'`).
- [ ] **Step 3: Implement** `_discover`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Step 5: Commit** `feat: commandes du projet découvertes dans app/console/commands (#9)`.

### Task 4: `flask route:list`

**Files:**
- Modify: `src/flask_artisan/routing.py`, `src/flask_artisan/console.py`
- Create: `tests/test_route_list.py`

**Interfaces:**
- Produces :
  - `Router.registered: list[tuple[PendingRoute, str, list[tuple[type, tuple[str, ...]]]]]`, sous la forme `(route, endpoint, stack)` : rempli dans `flush()` juste après `add_url_rule`, et initialisé à `[]` dans `__init__` ;
  - la commande `route:list`, qui affiche un tableau aux colonnes `Méthodes`, `URI`, `Nom`, `Action`, `Middlewares`, dont les largeurs suivent la cellule la plus longue. Les lignes sont triées par `(rule, méthodes)`. La colonne Nom contient l'endpoint si la route a été nommée avec `.name()` (`route.endpoint_name`), sinon elle est vide. L'action vaut `Classe@methode` ou `fonction.__name__`. Les middlewares sont écrits `Classe` ou `Classe:p1,p2` et séparés par `, `. Sans route : `Aucune route déclarée.`

- [ ] **Step 1: Write the failing tests** with `routed_app` and a kernel that has `middleware = {"auth": Authenticate-like dummy class}` and `groups = {"api": [...]}`, invoked with `app.test_cli_runner()` :
  - `test_route_list_controller_and_function` : `Route.get("/", HomeCtl.index).name("home")` and `Route.post("/ping", ping)` → the lines contain `GET`, `/`, `home`, `HomeCtl@index`, then `POST`, `/ping` and `ping` with an empty name ;
  - `test_route_list_middlewares_with_params` : a group `with Route.prefix("/api").middleware("auth:api")` → `Dummy:api` on the route line ;
  - `test_route_list_resource` : `Route.resource("photos", PhotoCtl)` → `photos.index`, `PUT|PATCH` on `/photos/<id>` ;
  - `test_route_list_sorted_and_no_head_options` : no `HEAD` or `OPTIONS` ; URIs in ascending order ;
  - `test_route_list_empty` → `Aucune route déclarée.`
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_route_list.py -q`. Attendu : `No such command 'route:list'`.
- [ ] **Step 3: Implement** `Router.registered` and the `route:list` command.
- [ ] **Step 4: Run** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Step 5: Commit** `feat: flask route:list (#9)`.

### Task 5: squelette, bout en bout, documentation

**Files:**
- Create: `src/flask_artisan/skeleton/app/console/__init__.py`, `src/flask_artisan/skeleton/app/console/commands/__init__.py` (vides)
- Modify: `tests/test_cli.py`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: Write the failing test** `test_generated_project_console` in `tests/test_cli.py`, in a generated project (subprocess `python -m flask`) :
  - `make:controller PhotoController --resource` → exit 0 ;
  - `make:command SendEmails` → exit 0, then `app:send-emails` → exit 0 with the stub's message ;
  - `route:list` → contains `api.login`, `AuthController@login` and `Authenticate:api` ;
  - the generated files pass `ruff check` and `ruff format --check` (repo config).
  Also add `app/console/commands/__init__.py` to `test_generated_project_has_database_files`, or create an equivalent test.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_cli.py -q`. Attendu : FAIL, because `app/console/commands` is missing from the skeleton.
- [ ] **Step 3: Implement.** Add the skeleton folders.
- [ ] **Step 4: Run** `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`. Attendu : vert.
- [ ] **Step 5: Docs.**
  - README : une section « Console » avec les générateurs, une commande du projet en exemple, `route:list` et la note « pas de `-m` » ; cocher le point 5 de la feuille de route.
  - CLAUDE.md : l'architecture (`ArtisanGroup` dans `console.py`, découverte paresseuse côté CLI seulement, `Router.registered`) et la ligne de statut, qui devient « chantiers 1 à 5 terminés ».
- [ ] **Step 6: Commit** `feat: dossier app/console dans le squelette et documentation de la console (#9)`.
