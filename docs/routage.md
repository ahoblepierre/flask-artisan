# Routage

Les routes vivent dans `routes/web.py` et `routes/api.py` (préfixe `/api`). Elles sont enregistrées dans Flask : `url_for`, `flask routes` et les error handlers marchent comme d'habitude.

```python
# routes/api.py
from flask_artisan import Route
from app.http.controllers.user_controller import UserController
from app.http.controllers.photo_controller import PhotoController

Route.get("/users", UserController.index).name("users.index")
Route.get("/users/<int:id>", UserController.show)

with Route.prefix("/admin").name("admin.").middleware("auth"):
    Route.post("/users", UserController.store)

Route.resource("photos", PhotoController)  # index, create, store, show, edit, update, destroy
```

- Verbes : `get`, `post`, `put`, `patch`, `delete`. Les groupes `with` s'imbriquent.
- `Route.resource` ne crée que les routes des méthodes que le controller définit. Le paramètre s'appelle `id`.
- Les valeurs d'URL arrivent telles que Flask les donne : écrivez `<int:id>` pour recevoir un entier. Une annotation `id: int` ne convertit rien.
- Une méthode héritée d'une classe parente se déclare sous la forme `(AdminController, "index")`. Avec `AdminController.index`, Python ne peut pas savoir quelle classe construire.
- Flask lit ce qui précède un point dans un nom de route comme un nom de blueprint. Un nom comme `admin.dashboard` est donc refusé si un blueprint `admin` est enregistré.
- On peut aussi déclarer des routes dans le `boot()` d'un provider. Après le boot, c'est trop tard.

## Controllers

Le conteneur construit le controller à chaque requête. Les méthodes reçoivent les valeurs d'URL, plus tout service annoncé par son type :

```python
class UserController:
    def __init__(self, users: UserRepository):
        self.users = users

    def show(self, id: int, logger: Logger):
        return {"id": id}  # dict → JSON, str → HTML, tuple → (corps, statut)
```

La même injection est disponible partout avec `app.call(fonction, **valeurs)`.

## Middlewares

```python
from flask_artisan import Middleware


class EnsureJson(Middleware):
    def handle(self, request, next):
        if not request.is_json:
            return {"error": "JSON attendu"}, 415
        response = next(request)
        response.headers["X-Api"] = "1"
        return response
```

Déclarez-les dans `app/http/kernel.py` :

```python
class Kernel(HttpKernel):
    global_middleware = []                 # toutes les routes déclarées avec Route
    middleware = {"json": EnsureJson}      # alias : .middleware("json")
    groups = {"web": [], "api": ["json"]}  # appliqués à routes/web.py et routes/api.py
```

Des paramètres peuvent suivre l'alias : `.middleware("throttle:60,1")` appelle `handle(request, next, "60", "1")`. Les routes `@app.route` natives ne passent pas par le kernel.
