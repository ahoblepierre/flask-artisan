# GH-3 — Routage : fichiers de routes, controllers en classes, middlewares

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/3
Statut : brouillon, en attente d'approbation

## Intention

Dans le chantier 1, une route se déclare avec `@self.app.route(...)` dans un provider : c'est du Flask brut. Ce chantier apporte la façon Laravel d'organiser le HTTP :

- les routes vivent dans `routes/web.py` et `routes/api.py` ;
- elles pointent vers des **controllers en classes** dont les dépendances sont injectées ;
- des **middlewares nommés** sont déclarés dans un kernel et appliqués par route ou par groupe.

Flask reste le moteur. Chaque route est enregistrée avec `add_url_rule`, donc `url_for`, `flask routes`, les error handlers et les extensions Flask continuent de marcher.

## Objectifs

1. Un développeur Laravel lit `routes/api.py` et comprend sans doc :
   ```python
   from flask_artisan import Route
   from app.http.controllers.user_controller import UserController

   Route.get("/users", UserController.index).name("users.index")
   Route.get("/users/<int:id>", UserController.show)
   with Route.prefix("/admin").middleware("auth"):
       Route.post("/users", UserController.store)
   Route.resource("photos", PhotoController)
   ```
2. Un controller reçoit ses services par le constructeur et ses méthodes reçoivent les paramètres d'URL, plus tout service annoncé par son type :
   ```python
   class UserController:
       def __init__(self, users: UserRepository):
           self.users = users

       def show(self, id: int, logger: Logger):
           return {"id": id}
   ```
3. Un middleware s'écrit en oignon et se branche par son alias :
   ```python
   class EnsureJson(Middleware):
       def __init__(self, logger: Logger):
           self.logger = logger

       def handle(self, request, next):
           if not request.is_json:
               return {"error": "JSON attendu"}, 415
           response = next(request)
           response.headers["X-Api"] = "1"
           return response
   ```
   Dans `app/http/kernel.py` :
   ```python
   class Kernel(HttpKernel):
       global_middleware = []
       middleware = {"json": EnsureJson}
       groups = {"web": [], "api": ["json"]}
   ```
4. Le projet généré par `flask-artisan new` utilise tout ça dès le départ, et sa route `/` passe par `routes/web.py`.

## Non-objectifs

- Validation des requêtes (Form Requests) : après v0.1.
- Liaison automatique d'un modèle depuis l'URL : avec l'ORM (chantier 3).
- Sous-domaines, `Route.redirect`, `Route.view`, `Route.any/match`, options `only`/`except` de `resource`.
- Commandes `flask make:controller`, `flask make:middleware`, `flask route:list` : chantier 5.
- Middlewares concrets fournis par le framework : aucun dans ce chantier. `auth` arrive au chantier 4, et un vrai CSRF demanderait une dépendance de plus.
- Vues asynchrones (`async def`).

## Anti-objectifs

- Contourner Flask : pas de routeur parallèle ni de dispatcher maison. Une route déclarée avec `Route` doit apparaître dans `app.url_map` comme n'importe quelle route Flask.
- Casser `@app.route` : les routes Flask natives continuent de marcher, sans passer par les middlewares du kernel.
- Ajouter une dépendance au cœur.

## Approches considérées

**Syntaxe des routes**

| | Approche | Verdict |
|---|---|---|
| A | Pythonique : `Route.get("/users", UserController.index)`, groupes en `with` | **Choisie par Pierre** : lisible, se reconnaît depuis Laravel, autocomplétion et renommage par l'IDE fonctionnent sur `UserController.index`. |
| B | Copie Laravel : `Route.get("/users", [UserController, "index"])`, groupes en `Route.group(..., lambda: ...)` | Écartée : les lambdas multi-lignes n'existent pas en Python, et le nom de méthode en chaîne échappe à l'IDE. |
| C | Décorateurs sur les méthodes du controller | Écartée : disperse les routes, ce qui est l'inverse de ce que Laravel apporte. |

**Middlewares**

| | Approche | Verdict |
|---|---|---|
| A | Oignon : `handle(self, request, next)` | **Choisie par Pierre** : identique à Laravel, permet d'agir avant et après, et de court-circuiter. |
| B | `before`/`after` séparés, accrochés à `before_request`/`after_request` de Flask | Écartée : ne s'applique pas par route, et ne peut pas entourer la requête (try/except, chronométrage). |

## Décisions

### Routes

- Une façade `Route` résout un `Router` enregistré dans le conteneur sous `"router"` (et sous la classe `Router`) par `Application`, avant les providers.
- Verbes : `get`, `post`, `put`, `patch`, `delete`. Chacun renvoie un objet route dont `.name(str)` et `.middleware(*alias)` sont chaînables.
- Les URL utilisent la syntaxe Flask (`<int:id>`), pas `{id}`.
- Groupes : `Route.prefix("/admin")`, `Route.middleware("auth")` et `Route.name("admin.")` renvoient un groupe chaînable, utilisable comme gestionnaire de contexte (`with`). Les groupes s'imbriquent : les préfixes et préfixes de nom se concatènent, les middlewares s'additionnent (ceux du groupe externe d'abord).
- `Route.resource("photos", PhotoController)` déclare les routes CRUD **pour les méthodes que le controller définit** (un controller d'API sans `create`/`edit` n'en a donc pas), avec ces URL et ces noms :

  | Méthode | Verbe(s) | URL | Nom |
  |---|---|---|---|
  | index | GET | /photos | photos.index |
  | create | GET | /photos/create | photos.create |
  | store | POST | /photos | photos.store |
  | show | GET | /photos/&lt;id&gt; | photos.show |
  | edit | GET | /photos/&lt;id&gt;/edit | photos.edit |
  | update | PUT, PATCH | /photos/&lt;id&gt; | photos.update |
  | destroy | DELETE | /photos/&lt;id&gt; | photos.destroy |

  Le paramètre s'appelle `id`, sans convertisseur : pas de singularisation de l'anglais en Python. `/photos/create` doit gagner sur `/photos/<id>` (le routeur de Werkzeug préfère déjà les segments statiques).
- Le nom d'une route devient son **endpoint Flask** : `url_for("users.index")` marche. Une route sans nom reçoit un endpoint automatique et unique.
- *Choix de Claude :* Flask lit ce qui précède le dernier point d'un endpoint comme un nom de blueprint (`request.blueprint`, hooks `before_request`, error handlers). Les points restent autorisés pour tenir la promesse `url_for("users.index")`. En revanche, l'enregistrement échoue si le premier segment du nom correspond à un blueprint déjà enregistré, et la doc le signale.
- *Choix de Claude :* `Route` s'utilise dans les fichiers de routes **et** dans le `boot()` de n'importe quel provider. Les routes en attente sont envoyées à Flask à la fin de `Application.boot()`, ce qui laisse `.name()` s'appliquer après `Route.get(...)`. Déclarer une route après le boot lève une erreur claire.
- Un handler peut être :
  - `UserController.index`, la forme principale ;
  - `(UserController, "index")`, la forme explicite, nécessaire quand la méthode est héritée d'une classe parente (voir « Pièges ») ;
  - une simple fonction, appelée avec injection comme une méthode.
- Erreurs à l'enregistrement, avec un message qui nomme la route : alias de middleware inconnu, handler qui n'est ni l'une ni l'autre de ces formes, nom de route déjà pris.

### Chargement des fichiers de routes

- Le framework fournit une classe `RouteServiceProvider`. Dans `boot()`, elle charge :
  - `routes/web.py` avec le groupe de middlewares `web` ;
  - `routes/api.py` avec le préfixe `/api` et le groupe `api`.
- Un fichier absent est ignoré.
- Les fichiers sont chargés comme `config/*.py`, par chemin. Une erreur à l'import remonte avec le nom du fichier.
- Le squelette contient `app/providers/route_service_provider.py`. Cette sous-classe déclare `kernel = Kernel` et est ajoutée à `config/app.py` → `providers`. Elle peut surcharger le préfixe d'API ou la liste des fichiers.

### Controllers

- La classe du controller est construite **par le conteneur à chaque requête**, avec ses dépendances injectées. Aucune classe de base n'est exigée.
- La méthode est appelée par `app.call()`. Ce nouveau service du conteneur appelle une fonction en résolvant ses paramètres :
  1. les valeurs passées explicitement (ici les paramètres d'URL) ;
  2. puis le même ordre que `make` : binding explicite, valeur par défaut, autowiring.

  **Aucune conversion de type** (décision de Pierre) : une valeur d'URL arrive telle que Flask la donne. `/photos/<id>` donne donc une chaîne, même si la méthode déclare `id: int`. Pour un entier, on écrit `<int:id>` dans la route.

  *Choix de Claude :* une valeur d'URL que la méthode ne déclare pas est ignorée, sauf si la méthode accepte `**kwargs`. C'est le comportement de Laravel.

  `app.call(fn, **params)` est public. Il passe les tests « aucun attribut Flask masqué » (Flask n'a pas d'attribut `call`).
- Ce que la méthode renvoie suit les règles de Flask : un dict devient du JSON, une chaîne du HTML, un tuple porte le statut et les en-têtes. Le résultat est converti en `Response` (`make_response`) avant de remonter dans les middlewares, pour qu'ils puissent toujours lire et modifier `response.headers`.

### Middlewares

- Une classe de base `Middleware` déclare `handle(self, request, next)`. Le middleware est construit par le conteneur **à chaque requête**.
- `request` est la requête Flask courante. `next(request)` renvoie une `Response`. Un middleware qui renvoie sans appeler `next` court-circuite la suite, et ce qu'il renvoie est converti par `make_response`.
- Paramètres façon Laravel : `"throttle:60,1"` appelle `handle(request, next, "60", "1")`, en chaînes.
- Ordre d'exécution : `global_middleware` du kernel, puis le groupe du fichier (`web`/`api`), puis les groupes `with` du plus externe au plus interne, puis les middlewares de la route. Un même middleware déclaré deux fois (même alias et mêmes paramètres) ne s'exécute qu'une fois, à sa première position.
- Dans le kernel, une entrée de groupe peut être un alias (avec paramètres) ou une classe. Un groupe ne peut pas contenir un autre groupe dans ce chantier.
- `global_middleware` ne s'applique qu'aux routes déclarées avec `Route`, pas aux `@app.route` natives.
- Une exception levée par le controller traverse les middlewares, qui peuvent donc l'attraper. Si personne ne l'attrape, les error handlers de Flask la traitent comme d'habitude.
- Le kernel du projet est une classe `Kernel(HttpKernel)` avec trois attributs de classe, `global_middleware`, `middleware` et `groups`. Le `RouteServiceProvider` le fournit au routeur. Il le fait dans `register()`, pour que les alias soient connus avant le `boot()` de tout provider. Sans kernel, le routeur fonctionne avec des listes vides.

### Façades dans une requête

- Correction d'un défaut reporté du chantier 1 : `Application.get_instance()` renvoie `flask.current_app` quand un contexte d'application est actif et que c'est une `Application`. Sinon, il renvoie la dernière application créée.
- Ainsi, avec deux apps dans un même processus (cas des tests), une façade appelée pendant une requête vise la bonne.

### Squelette

```
app/http/__init__.py
app/http/kernel.py                       Kernel(HttpKernel), groupes web et api vides
app/http/controllers/__init__.py
app/http/controllers/home_controller.py  HomeController.index → {"app": config("app.name")}
app/http/middleware/__init__.py
app/providers/route_service_provider.py
routes/web.py                            Route.get("/", HomeController.index).name("home")
routes/api.py                            un exemple commenté
```

- La route `/` quitte `AppServiceProvider`, qui redevient vide.
- Le test du projet généré (`GET /` → 200) reste vert.

### Exports publics

`from flask_artisan import Route, Router, Middleware, HttpKernel, RouteServiceProvider`, en plus des exports existants.

## Pièges connus

- **Méthode héritée.** `AdminController.index`, quand `index` est défini dans `BaseController`, est le même objet Python que `BaseController.index`. Le framework retrouve la classe par le `__qualname__` de la fonction, donc il construirait `BaseController`. Pour ce cas, la doc indique la forme `(AdminController, "index")`. `Route.resource` reçoit la classe et n'est pas concerné.
- **Classe définie dans une fonction** (`<locals>` dans le `__qualname__`) : on ne peut pas la retrouver depuis la méthode. C'est fréquent dans les tests. Il faut alors utiliser la forme tuple, et le message d'erreur doit le dire.
- **`flask run` et rechargement** : les fichiers de routes sont chargés au boot, donc le reloader de `flask run --debug` les voit comme tout autre fichier Python.

## Laissé au constructeur

- Découpage en modules (par exemple `routing.py`, `middleware.py`, `http.py`) et nom des classes internes (route en attente, groupe, pipeline).
- Format des endpoints automatiques, du moment qu'ils sont uniques et lisibles dans `flask routes`.
- Moment où les routes en attente sont poussées dans Flask (à la fin de chaque fichier, ou à la fin du boot), du moment que `.name()` posé après `Route.get(...)` est pris en compte.
- Contenu exact des exemples du squelette.

## Livraison

- Tests pytest pour le routeur, les groupes, `resource`, `app.call`, le pipeline de middlewares et le chargement des fichiers ; test de bout en bout du projet généré.
- README (section routage) et CLAUDE.md (architecture) mis à jour.
- Une PR `feat/3-routage`, titre avec `(#3)`, corps avec `Closes #3`. CI verte sur 3.10 à 3.13.
