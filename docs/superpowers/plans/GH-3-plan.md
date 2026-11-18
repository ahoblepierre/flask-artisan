# Routage & middlewares — plan d'implémentation

> **Pour les agents :** sous-skill requis : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**But :** fichiers `routes/*.py`, façade `Route` (verbes, groupes `with`, `resource`), controllers en classes injectés, middlewares en oignon déclarés dans un kernel, le tout enregistré dans Flask par `add_url_rule`.

**Architecture :**
- Un `Router` vit dans le conteneur (`"router"` et `Router`) et accumule des routes en attente pendant une fenêtre de collecte. `Application.boot()` ouvre cette fenêtre autour des `boot()` des providers, puis la ferme en poussant les routes dans Flask (`flush`).
- Chaque route devient une vue Flask qui exécute le pipeline de middlewares puis le handler, via `app.make` et le nouveau `app.call`.
- Un `RouteServiceProvider` du framework branche le kernel dans `register()` et charge les fichiers de routes dans `boot()`.

**Stack :** Python ≥ 3.10, Flask ≥ 3, pytest, ruff. Aucune nouvelle dépendance.

**Spec :** [docs/superpowers/specs/GH-3-spec.md](../specs/GH-3-spec.md)

## Contraintes globales

- Aucune dépendance ajoutée au cœur.
- Tout attribut ajouté à `Application` ou `Container` doit passer `test_no_flask_attribute_shadowed` et `test_application_does_not_override_flask`. L'état interne de `Application` est préfixé `_` et ne doit pas exister sur `Flask`.
- Messages d'erreur en français et nommant la route, le fichier ou l'alias fautif.
- Les valeurs d'URL ne sont jamais converties (décision de Pierre) : `/photos/<id>` donne une chaîne.
- Une valeur d'URL non déclarée par le handler est ignorée, sauf si le handler a `**kwargs`.
- Les routes `@app.route` natives ne passent jamais par les middlewares du kernel.
- Commits : `feat: … (#3)`, `docs: … (#3)`. Lancer `.venv/bin/ruff check . && .venv/bin/ruff format --check .` avant chaque commit.

## Review Focus

1. **Méthode héritée sous la forme `Enfant.methode`.** On ne peut pas la distinguer de `Parent.methode`, donc la doc doit pousser vers la forme tuple. Ajouter un test qui fige le comportement de la forme tuple avec une méthode héritée (tâche 3).
2. **Middleware qui court-circuite avec un dict ou un tuple.** Le résultat doit être converti en `Response`, y compris pour les middlewares externes qui lisent `response.headers` (tâche 5).
3. **`/photos/create` contre `/photos/<id>`.** La route statique doit gagner (tâche 4).
4. **Deux apps dans un même processus.** Les routes de l'une ne doivent pas fuir dans l'autre, et les façades doivent viser l'app de la requête (tâches 2 et 3).
5. **Exception levée dans le controller.** Elle traverse les middlewares (qui peuvent l'attraper), puis tombe dans l'error handler Flask si personne ne l'a attrapée (tâche 5).

## Fichiers

| Fichier | Rôle |
|---|---|
| `src/flask_artisan/container.py` | + `call()` ; la résolution des paramètres est factorisée pour servir `make` et `call` |
| `src/flask_artisan/application.py` | `get_instance` préfère `current_app` ; enregistre le `Router` ; fenêtre de collecte dans `boot`/`register` |
| `src/flask_artisan/routing.py` (nouveau) | `Router`, `PendingRoute`, `RouteGroup`, `RouteError`, résolution des handlers, `resource`, `load` |
| `src/flask_artisan/middleware.py` (nouveau) | `Middleware`, `HttpKernel`, résolution des alias, pipeline |
| `src/flask_artisan/route_provider.py` (nouveau) | `RouteServiceProvider` |
| `src/flask_artisan/facades.py` | + façade `Route` (accessor `"router"`) |
| `src/flask_artisan/__init__.py` | exports `Route, Router, RouteError, Middleware, HttpKernel, RouteServiceProvider` |
| `src/flask_artisan/skeleton/…` | kernel, controllers, routes, `RouteServiceProvider` |
| `tests/conftest.py` | + fixture `routed_app` |
| `tests/test_container.py`, `tests/test_application.py` | tests de `call` et de `get_instance` |
| `tests/test_routing.py`, `tests/test_middleware.py`, `tests/test_route_provider.py` (nouveaux) | — |
| `README.md`, `CLAUDE.md` | section routage, architecture |

---

### Tâche 1 : `Container.call`

**Fichiers :**
- Modifier : `src/flask_artisan/container.py`
- Test : `tests/test_container.py`

**Interfaces :**
- Produit : `Container.call(self, fn: Callable, **params) -> Any`.

- [ ] **Étape 1 : écrire les tests qui échouent** (dans `tests/test_container.py`, avec les classes de service déjà présentes ou de nouvelles classes au niveau du module) :
  - `test_call_injects_by_type` : `c.call(lambda svc: svc, ...)` ne marche pas sans annotation, donc définir `def f(svc: Service): return svc`. `isinstance(c.call(f), Service)`.
  - `test_call_explicit_params_win` : `def f(id, svc: Service): return id, svc`, puis `c.call(f, id="5")[0] == "5"`. La valeur est la chaîne, sans conversion, même si `id: int` est annoté.
  - `test_call_ignores_unknown_params` : `def f(): return 1`, puis `c.call(f, team_id="3") == 1`.
  - `test_call_passes_unknown_to_kwargs` : `def f(**kw): return kw`, puis `c.call(f, a="1") == {"a": "1"}`.
  - `test_call_uses_default_and_binding_order` : un paramètre `path: Path = Path("x")` garde sa valeur par défaut. Un paramètre lié par `c.instance(Service, s)` reçoit `s`.
  - `test_call_bound_method` : `c.call(Obj().m)`, où `m(self, svc: Service)`, résout `svc` et n'essaie pas de résoudre `self`.
  - `test_call_unresolvable_names_function` : `def f(x): ...`, `pytest.raises(BindingResolutionError, match="'x'.*f")`.
- [ ] **Étape 2 :** `.venv/bin/pytest tests/test_container.py -q`. Attendu : les 7 nouveaux tests échouent avec `AttributeError: ... 'call'`.
- [ ] **Étape 3 : implémenter.** Remplacer `_container_arguments(cls, params)` par `_container_arguments(fn, owner: str, params, *, keep_unknown: bool)` :
  - `fn` est la fonction dont on lit `inspect.signature` et `typing.get_type_hints` ;
  - `owner` est le nom utilisé dans les messages.
  - `_container_autowire` appelle `fn=cls.__init__`, `owner=cls.__name__` et saute le premier paramètre (`self`). Garder le cas `object.__init__` et `keep_unknown=False` : `make` ne change pas de comportement.

  `call(fn, **params)` :
  - prend `inspect.signature(fn)`, qui exclut déjà `self` pour une méthode liée ;
  - résout dans le même ordre que `make` (params explicites, binding, défaut, autowiring) ;
  - ignore les params inconnus, sauf si la signature a un `VAR_KEYWORD`, auquel cas ils lui sont passés ;
  - renvoie `fn(**args)`. `owner` vaut `getattr(fn, "__qualname__", repr(fn))`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : tout vert, y compris `test_no_flask_attribute_shadowed` (Flask n'a pas d'attribut `call`).
- [ ] **Étape 5 :** commit `feat: app.call() injecte les dépendances dans une fonction (#3)`.

### Tâche 2 : `get_instance` préfère `current_app`

**Fichiers :**
- Modifier : `src/flask_artisan/application.py`
- Test : `tests/test_application.py`

**Interfaces :**
- Produit : `Application.get_instance()` renvoie `flask.current_app` si `has_app_context()` et que l'objet courant (`current_app._get_current_object()`) est une `Application`. Sinon, il renvoie `Application._current` comme avant.

- [ ] **Étape 1 : test** `test_get_instance_prefers_current_app`. Créer `a = Application(make_project(name="'A'"))`, puis `b` dans un autre dossier (`tmp_path_factory` ou un sous-dossier). Vérifier :
  - `with a.app_context(): assert Application.get_instance() is a` ;
  - hors contexte, `Application.get_instance() is b`.

  Utiliser deux dossiers. `make_project` écrit toujours dans `tmp_path` : passer par un sous-dossier copié, ou ajouter un paramètre `base` à la fixture si c'est plus simple.
- [ ] **Étape 2 :** lancer le test. Attendu : FAIL, car `get_instance` renvoie `b`.
- [ ] **Étape 3 :** implémenter avec `from flask import current_app, has_app_context`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: les façades visent l'app de la requête courante (#3)`.

### Tâche 3 : `Router`, verbes, controllers et enregistrement dans Flask

**Fichiers :**
- Créer : `src/flask_artisan/routing.py`
- Modifier : `src/flask_artisan/application.py`, `src/flask_artisan/facades.py`, `src/flask_artisan/__init__.py`, `tests/conftest.py`
- Test : `tests/test_routing.py`

**Interfaces :**
- Consomme : `Container.call` (tâche 1).
- Produit :
  - `class RouteError(Exception)`.
  - `class Router`, avec :
    - `__init__(self, app: Application)` ;
    - `get/post/put/patch/delete(self, rule: str, handler) -> PendingRoute` ;
    - `collecting(self)`, un gestionnaire de contexte qui ouvre la fenêtre et appelle `flush()` à la sortie sans exception ;
    - `flush(self) -> None`.
  - `PendingRoute` : `.name(str) -> PendingRoute`, `.middleware(*items) -> PendingRoute` (stocké ici, appliqué en tâche 5), attributs `rule`, `methods`, `handler`.
  - Point d'extension pour la tâche 5 : à chaque route, `flush` construit sa vue avec `self._view(route)`. Dans cette tâche, `_view` appelle seulement le handler puis `app.make_response`.
  - `Route` (façade, accessor `"router"`).
  - `Application` enregistre `Router(self)` sous `"router"` et `Router` avant les providers.
  - `Application.boot()` exécute les `boot()` des providers dans `with router.collecting():`. `register()` après boot fait de même autour du `provider.boot()`.
  - Fixture `routed_app(declare, kernel=None) -> Application` dans `tests/conftest.py` :
    1. crée l'app sans providers ;
    2. si `kernel` est fourni, appelle `app.make(Router).use_kernel(kernel)`. Cette méthode est produite en tâche 5 : avant elle, n'appeler la fixture que sans kernel ;
    3. enregistre un provider créé à la volée dont `boot()` appelle `declare()` ;
    4. renvoie l'app.

- [ ] **Étape 1 : tests** (`tests/test_routing.py`). Les controllers sont définis au niveau du module, car la résolution par `__qualname__` l'exige.
  - `test_get_with_controller_method` : `UserController.index` renvoie `{"users": []}`, puis `GET /users` → 200 et ce JSON.
  - `test_url_values_and_injection` : `show(self, id, svc: Service)` sur `/users/<int:id>` renvoie `{"id": id, "svc": type(svc).__name__}`, puis `GET /users/5` → `{"id": 5, "svc": "Service"}`.
  - `test_resource_id_stays_string` : `/x/<id>` passe `"5"`.
  - `test_controller_constructor_injection` : `__init__(self, svc: Service)`, et le handler renvoie `type(self.svc).__name__`.
  - `test_controller_built_per_request` : compteur de classe incrémenté dans `__init__`. Deux GET donnent un compteur de 2.
  - `test_tuple_handler_with_inherited_method` : `(Child, "index")`, où `index` est défini sur `Base` et renvoie `type(self).__name__`. Résultat attendu : `"Child"`.
  - `test_plain_function_handler` : `def ping(svc: Service): return "pong"`.
  - `test_local_class_method_requires_tuple` : une classe définie dans le test et `Local.index` lèvent `RouteError`, avec un message qui contient `"(Local, \"index\")"` ou `tuple`.
  - `test_name_is_endpoint` : `.name("users.index")`, puis `url_for("users.index")` dans `test_request_context` → `/users`.
  - `test_unnamed_routes_get_unique_endpoints` : la même méthode sur deux URL donne deux endpoints distincts, sans point.
  - `test_duplicate_name_raises` : `RouteError` qui nomme le nom.
  - `test_name_clashing_with_blueprint_raises` : un `Blueprint("admin", ...)` est enregistré avant, puis la route est nommée `admin.dashboard`. Attendu : `RouteError`.
  - `test_methods` : `post/put/patch/delete` répondent à leur verbe. `GET` sur une route `post` → 405.
  - `test_route_after_boot_raises` : `Route.get(...)` hors fenêtre lève `RouteError`, dont le message mentionne `boot()`.
  - `test_native_route_still_works` : `@app.route("/n")` → 200.
  - `test_routes_do_not_leak_between_apps` : deux apps, chacune avec sa route. L'autre app répond 404.
  - `test_appears_in_url_map` : `"/users" in [r.rule for r in app.url_map.iter_rules()]`.
- [ ] **Étape 2 :** `.venv/bin/pytest tests/test_routing.py -q`. Attendu : erreur d'import de `Router` et `Route`.
- [ ] **Étape 3 : implémenter.**

  Résolution d'un handler en `(cls | None, attr | fn)` :
  - un tuple `(cls, "m")` donne la classe et la méthode ;
  - une fonction dont le `__qualname__` a un seul segment est une fonction simple ;
  - une fonction dont l'avant-dernier segment est `<locals>` est une fonction locale simple ;
  - si `<locals>` apparaît ailleurs dans le `__qualname__`, lever `RouteError` qui suggère la forme tuple ;
  - sinon, retrouver la classe en descendant le `__qualname__` depuis `sys.modules[fn.__module__]` ;
  - tout autre handler lève `RouteError`.

  Endpoint automatique : `"{Classe}@{methode}"` (ou `__name__` pour une fonction), suffixé `_2`, `_3`… s'il est déjà pris dans `app.view_functions`.

  `flush()` enregistre chaque route avec `app.add_url_rule(rule, endpoint, view, methods=...)`, puis vide la liste. Il vérifie avant :
  - nom déjà pris dans `app.view_functions` → `RouteError` ;
  - `name.split(".")[0] in app.blueprints` → `RouteError`.

  Un ajout hors fenêtre de collecte lève `RouteError("… déclarez vos routes dans routes/*.py ou dans boot() d'un provider")`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert, y compris les deux tests « aucun attribut Flask masqué ».
- [ ] **Étape 5 :** commit `feat: Router, façade Route et controllers injectés (#3)`.

### Tâche 4 : groupes et `resource`

**Fichiers :**
- Modifier : `src/flask_artisan/routing.py`
- Test : `tests/test_routing.py`

**Interfaces :**
- Consomme : `Router` et `PendingRoute` (tâche 3).
- Produit :
  - `Router.prefix(str)`, `Router.middleware(*items)` et `Router.name(str)`, qui renvoient chacun un `RouteGroup`. Ce groupe a les mêmes trois méthodes, chaînables, et `__enter__`/`__exit__`.
  - `Router.group(prefix="", middleware=(), name="") -> RouteGroup`, utilisé par `load` en tâche 6.
  - `Router.resource(name: str, controller: type) -> None`.
  - Chaque `PendingRoute` porte à sa création les attributs cumulés de la pile de groupes : préfixe d'URL, préfixe de nom (appliqué aussi à un `.name()` posé ensuite) et middlewares, ceux du groupe externe d'abord.

- [ ] **Étape 1 : tests.**
  - `test_prefix_group` : `with Route.prefix("/admin"): Route.get("/users", …)`, puis `GET /admin/users` → 200.
  - `test_nested_groups_concatenate` : `prefix("/a")` contenant `prefix("/b").name("b.")`, avec une route `.name("x")`. Attendu : `/a/b/…`, et `url_for("b.x")` fonctionne.
  - `test_group_name_prefix_nests` : `name("admin.")` contenant `name("users.")`, puis `.name("index")`. Attendu : endpoint `admin.users.index`.
  - `test_group_middleware_recorded_outer_first` : un groupe `middleware("a")` contenant `middleware("b")`, puis `.middleware("c")` sur la route. Attendu : `route.middleware_stack == ["a", "b", "c"]`. Nommer l'attribut ainsi et l'exposer sur `PendingRoute`. L'exécution est testée en tâche 5.
  - `test_group_exits_cleanly_on_exception` : une exception dans le `with` dépile le groupe. Une route déclarée ensuite n'a pas le préfixe.
  - `test_resource_full` : un controller avec les 7 méthodes donne les URL, verbes et noms du tableau de la spec. `PUT` et `PATCH` mènent tous deux à `update`.
  - `test_resource_only_defined_methods` : un controller avec seulement `index` et `show` n'enregistre pas `photos.create`, et `GET /photos/create` est servi par `show` avec `id == "create"`. Cela documente le comportement : un controller d'API n'a pas de route `create`.
  - `test_resource_create_beats_show` : avec les 7 méthodes, `GET /photos/create` est servi par `create`.
  - `test_resource_inside_prefix_group` : sous `prefix("/admin").name("admin.")`, on obtient `/admin/photos` et `admin.photos.index`.
- [ ] **Étape 2 :** lancer les tests. Attendu : FAIL (`AttributeError: prefix`).
- [ ] **Étape 3 :** implémenter. `resource` déclare dans l'ordre du tableau, pour chaque méthode présente sur la classe (`hasattr`), des routes au handler `(controller, methode)`. Le préfixe de nom est `f"{name}."`, et le slash initial est ajouté si `name` n'en a pas.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: groupes de routes et Route.resource (#3)`.

### Tâche 5 : middlewares, kernel et pipeline

**Fichiers :**
- Créer : `src/flask_artisan/middleware.py`
- Modifier : `src/flask_artisan/routing.py`, `src/flask_artisan/__init__.py`
- Test : `tests/test_middleware.py`

**Interfaces :**
- Consomme : `PendingRoute.middleware_stack` (tâche 4) et `Router._view` (tâche 3).
- Produit :
  - `class Middleware` : `handle(self, request, next)` renvoie `next(request)` par défaut.
  - `class HttpKernel` : attributs de classe `global_middleware: list = []`, `middleware: dict = {}`, `groups: dict = {"web": [], "api": []}`.
  - `Router.use_kernel(kernel: type[HttpKernel]) -> None`. Le kernel par défaut du routeur est `HttpKernel`.
  - `resolve(kernel, items) -> list[tuple[type, tuple[str, ...]]]` dans `middleware.py`. Elle convertit chaque entrée en couples (classe, paramètres) :
    - un nom de groupe est déplié (les groupes passent avant les alias, comme dans Laravel) ;
    - un alias, avec ou sans paramètres `"alias:p1,p2"`, devient sa classe et ses paramètres ;
    - une classe est prise telle quelle, sans paramètres ;
    - un alias ou un groupe inconnu lève `RouteError`, qui nomme l'alias et la route ;
    - un doublon (même classe, mêmes paramètres) n'est gardé qu'à sa première position.

    L'ordre final est `global_middleware`, puis la pile de la route. La résolution se fait au `flush`.

- [ ] **Étape 1 : tests** (`tests/test_middleware.py`, middlewares au niveau du module). Chaque middleware ajoute son nom dans une liste globale `trace` vidée par une fixture autouse.
  - `test_onion_order` : un global `G`, un groupe `with middleware("a")` et une route `.middleware("b")`. `trace == ["G>", "a>", "b>", "handler", "<b", "<a", "<G"]`.
  - `test_short_circuit_dict` : un middleware qui renvoie `{"error": "x"}, 415` sans appeler `next` donne une réponse 415. Le handler n'est pas appelé, et un middleware externe peut lire `response.headers`.
  - `test_after_can_modify_response` : le middleware ajoute `X-Api: 1` à la réponse.
  - `test_params` : `"tag:60,1"` reçoit `("60", "1")`.
  - `test_group_alias_expands` : `groups = {"api": ["tag:x"]}`, puis `.middleware("api")`.
  - `test_class_in_group_and_route` : une classe directement, sans alias.
  - `test_duplicate_runs_once` : le même alias dans le groupe et sur la route ne s'exécute qu'une fois.
  - `test_unknown_alias_raises_at_registration` : `RouteError` qui nomme `"nope"`, levée par le boot.
  - `test_middleware_injected_by_container` : `__init__(self, svc: Service)`.
  - `test_built_per_request` : compteur.
  - `test_exception_traverses_middleware` : un middleware fait `try/except ValueError` et renvoie une 400 ; le controller lève `ValueError`. Sans ce middleware, l'error handler Flask `@app.errorhandler(ValueError)` → 418 s'applique.
  - `test_global_not_applied_to_native_routes` : `@app.route("/n")` n'apparaît pas dans `trace`.
- [ ] **Étape 2 :** lancer les tests. Attendu : erreur d'import.
- [ ] **Étape 3 : implémenter.**
  - `_view(route)` capture la liste résolue et le handler. Par requête, il :
    1. prend `req = flask.request._get_current_object()` ;
    2. exécute `run(i, req)` récursivement : à chaque étape, `app.make(cls).handle(req, lambda r: run(i + 1, r), *params)`, dont le résultat passe dans `app.make_response`. Au bout de la liste, il appelle le handler via `app.call(...)`, dont le résultat passe aussi dans `app.make_response`.
  - Exporter `Middleware`, `HttpKernel` et `RouteError`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: middlewares en oignon et kernel HTTP (#3)`.

### Tâche 6 : `RouteServiceProvider` et chargement des fichiers

**Fichiers :**
- Créer : `src/flask_artisan/route_provider.py`
- Modifier : `src/flask_artisan/routing.py` (`load`), `src/flask_artisan/__init__.py`
- Test : `tests/test_route_provider.py`

**Interfaces :**
- Consomme : `Router.group`, `Router.use_kernel`.
- Produit :
  - `Router.load(path: Path, prefix: str = "", middleware=()) -> None`. Elle ignore un fichier absent, exécute le fichier dans `self.group(...)` (module `flask_artisan_routes_{stem}`, chargé par `importlib.util.spec_from_file_location`, sans l'ajouter à `sys.modules`), et lève `RouteError(f"Erreur dans {path} : {exc}")` à l'import.
  - `class RouteServiceProvider(ServiceProvider)`, avec :
    - `kernel: type[HttpKernel] = HttpKernel` ;
    - `api_prefix = "/api"` ;
    - `register()`, qui appelle `use_kernel(self.kernel)` ;
    - `boot()`, qui charge `base_path("routes/web.py")` avec le middleware `("web",)`, puis `routes/api.py` avec `prefix=self.api_prefix` et le middleware `("api",)`.

- [ ] **Étape 1 : tests.** Chacun écrit `routes/*.py` dans le projet de `make_project`, avec des handlers sous forme de fonctions définies dans le fichier, et un provider de test au niveau du module.
  - `test_web_routes_loaded` : `GET /` → 200.
  - `test_api_prefix_and_group` : la route `/ping` dans `api.py` répond sur `/api/ping`. Le groupe `api` du kernel du provider de test est appliqué : vérifier un en-tête posé par un middleware.
  - `test_missing_files_ignored` : sans dossier `routes`, le boot passe.
  - `test_import_error_names_file` : `RouteError` qui contient `api.py`.
  - `test_kernel_known_before_other_providers_boot` : un autre provider, enregistré **avant** le `RouteServiceProvider`, déclare dans son `boot()` une route avec l'alias du kernel. Attendu : aucune erreur.
  - `test_custom_api_prefix` : une sous-classe avec `api_prefix = "/v1"`.
- [ ] **Étape 2 :** lancer les tests. Attendu : erreur d'import.
- [ ] **Étape 3 :** implémenter et exporter `RouteServiceProvider`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: RouteServiceProvider charge routes/web.py et routes/api.py (#3)`.

### Tâche 7 : squelette, documentation et bout en bout

**Fichiers :**
- Créer dans `src/flask_artisan/skeleton/` :
  - `app/http/__init__.py`, `app/http/controllers/__init__.py`, `app/http/middleware/__init__.py` ;
  - `app/http/kernel.py` ;
  - `app/http/controllers/home_controller.py` ;
  - `app/providers/route_service_provider.py` ;
  - `routes/web.py`, `routes/api.py`.
- Modifier :
  - `skeleton/app/providers/app_service_provider.py` : `boot()` devient vide, avec un commentaire ;
  - `skeleton/config/app.py` : ajouter `RouteServiceProvider` aux providers ;
  - `README.md`, `CLAUDE.md`.
- Test : `tests/test_cli.py`.

**Interfaces :**
- Consomme : tout ce qui précède.
- Contenu du squelette :
  - `Kernel(HttpKernel)`, avec `global_middleware = []`, `middleware = {}` et `groups = {"web": [], "api": []}`. Un commentaire montre un alias.
  - `HomeController.index` renvoie `{"app": config("app.name")}`.
  - `routes/web.py` contient `Route.get("/", HomeController.index).name("home")`.
  - `routes/api.py` contient un exemple commenté.
  - `RouteServiceProvider` (le squelette, sous-classe du framework) déclare `kernel = Kernel`.

- [ ] **Étape 1 : tests** dans `tests/test_cli.py`.
  - `test_generated_project_has_routes` : `routes/web.py`, `routes/api.py` et `app/http/kernel.py` existent.
  - `test_generated_home_is_named_route` : en sous-processus, `from wsgi import app` puis `url_for('home')` dans un `test_request_context` affiche `/`.

  Les tests existants `test_generated_app_responds` et `test_generated_project_tests_pass` doivent rester verts.
- [ ] **Étape 2 :** `.venv/bin/pytest tests/test_cli.py -q`. Attendu : les deux nouveaux tests échouent.
- [ ] **Étape 3 :** écrire le squelette, puis vérifier que `pyproject` embarque bien les nouveaux fichiers. Le glob `skeleton/**/*` les couvre. Le contrôler en construisant le wheel : `.venv/bin/pip wheel . -w /tmp/... --no-deps` puis `unzip -l | grep routes/web.py`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`. Attendu : tout vert.
- [ ] **Étape 5 : documentation.**
  - README : section « Routage » avec les exemples de la spec (routes, groupes, `resource`, controller, middleware, kernel), plus :
    - la forme tuple pour les méthodes héritées ;
    - l'absence de conversion des valeurs d'URL (`<int:id>`) ;
    - la mise en garde « nom de route et blueprint ».
  - CLAUDE.md :
    - statut : chantier 2 mergé à la livraison, sinon « en cours » ;
    - architecture : Router dans le conteneur, fenêtre de collecte dans `boot()`, vue = pipeline puis `app.call`, et `get_instance` qui préfère `current_app`.
- [ ] **Étape 6 :** commit `feat: le squelette utilise routes/, controllers et kernel (#3)`, puis `docs: routage dans README et CLAUDE.md (#3)`.

---

## Vérification finale

- `.venv/bin/pytest -q` est entièrement vert, et ruff est propre.
- À la main : `flask-artisan new /tmp/demo3 && cd /tmp/demo3 && flask routes` liste `home` sur `/`, et `flask run` répond `{"app": "demo3"}` sur `/`.
