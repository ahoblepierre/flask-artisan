# Flask-Artisan

**Les conventions de Laravel, mais c'est du Flask.**

Flask-Artisan donne une structure prête à l'emploi aux applications Flask : conteneur de services,
service providers, configuration par fichiers, façades et helpers. L'application reste un vrai
objet `Flask` : `flask run`, les extensions Flask et leur documentation fonctionnent tels quels.

> Version 0.1 (alpha) : l'API peut encore changer avant la 1.0. Voir le [changelog](https://github.com/ahoblepierre/flask-artisan/blob/main/CHANGELOG.md).

## Démarrer un projet

Prérequis : Python 3.10 ou plus (`python3 --version`). Sur macOS, le `python3` livré avec Xcode est un 3.9 : installez une version récente (python.org ou Homebrew).

```bash
python3 -m venv .venv && source .venv/bin/activate   # environnement virtuel
pip install flask-artisan
flask-artisan new blog
cd blog
pip install -r requirements.txt
flask run
```

Le projet généré :

```
blog/
├── app/http/controllers/  # controllers
├── app/http/kernel.py    # middlewares : globaux, alias, groupes web et api
├── app/providers/        # AppServiceProvider, RouteServiceProvider
├── routes/web.py         # routes web
├── routes/api.py         # routes préfixées par /api
├── bootstrap/app.py      # crée l'Application
├── app/models/            # modèles (User fourni)
├── config/app.py         # nom, environnement, debug, clé, providers
├── config/database.py    # connexions sqlite, mysql, mariadb, pgsql
├── database/migrations/  # migrations générées
├── config/flask.py       # clés copiées dans app.config (extensions Flask)
├── tests/
├── wsgi.py               # détecté par `flask run`
└── .env                  # APP_KEY générée automatiquement
```

## Conteneur de services

```python
from flask_artisan import app

app().bind(Mailer, SmtpMailer)                        # nouvelle instance à chaque make
app().singleton(Cache, lambda app: RedisCache("..."))  # une seule instance
app().make(ReportService)  # dépendances du constructeur injectées d'après leurs annotations
```

## Routage

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

### Controllers

Le conteneur construit le controller à chaque requête. Les méthodes reçoivent les valeurs d'URL, plus tout service annoncé par son type :

```python
class UserController:
    def __init__(self, users: UserRepository):
        self.users = users

    def show(self, id: int, logger: Logger):
        return {"id": id}  # dict → JSON, str → HTML, tuple → (corps, statut)
```

La même injection est disponible partout avec `app.call(fonction, **valeurs)`.

### Middlewares

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

## Base de données

L'API est façon Eloquent. Le SQL de chaque base est délégué à SQLAlchemy 2, et les migrations à Alembic. On choisit la base dans `.env` :

```
DB_CONNECTION=sqlite      # sqlite (par défaut, rien à installer), mysql, mariadb, pgsql
DB_HOST=127.0.0.1
DB_DATABASE=blog
```

Pilotes : `pip install "flask-artisan[pgsql]"` (PostgreSQL) ou `"flask-artisan[mysql]"` (MySQL et MariaDB).

### Modèles

```python
from flask_artisan.database import (
    Mapped, Model, SoftDeletes, belongs_to, belongs_to_many, column, foreign_id, has_many,
)


class User(Model, SoftDeletes):           # table "users", id, created_at, updated_at, deleted_at
    name: Mapped[str]
    email: Mapped[str] = column(unique=True)
    password: Mapped[str]
    posts = has_many("Post")              # cherche Post.user_id
    fillable = ["name", "email", "password"]
    hidden = ["password"]


class Post(Model):
    title: Mapped[str]
    user_id: Mapped[int] = foreign_id("users")
    user = belongs_to("User")             # utilise user_id (nom de l'attribut + _id)
    tags = belongs_to_many("Tag")         # table pivot post_tag
```

### Requêtes

```python
User.create(name="Ana", email="ana@x.io", password=hashed)
User.find(1)
User.find_or_fail(1)                      # 404 pendant une requête
User.where("name", "like", "A%").or_where("email", "like", "%@x.io").order_by("name").get()
User.where_in("id", [1, 2]).count()
User.with_("posts.tags").latest().first() # chargement immédiat des relations
user.update(name="Bob")
user.delete()                             # avec SoftDeletes : deleted_at rempli
User.with_trashed().get()
User.only_trashed().first().restore()
```

- Un controller peut renvoyer un modèle ou une liste de modèles : la réponse est du JSON, sans les champs de `hidden`.
- Avec `fillable`, toute autre clé est ignorée : `User.create(**request.form)` ne prend pas `is_admin` ni `csrf_token`. `id` et les dates ne sont jamais assignables en masse.
- **`save()` valide toute la session.** Si vous modifiez `a` puis appelez `b.save()`, `a` est aussi enregistré. Pour grouper plusieurs écritures :

```python
from flask_artisan import DB

with DB.transaction():      # validé à la sortie, annulé sur exception
    order.save()
    stock.update(quantity=stock.quantity - 1)
```

`DB.session` donne la session SQLAlchemy, pour tout ce que l'API ne couvre pas.

La session est fermée automatiquement à la fin de chaque requête. Un script ou une commande qui tourne longtemps doit appeler `DB.remove()` quand il a fini, sinon sa connexion reste ouverte.

### Migrations

```bash
flask make:migration "create users"   # compare les modèles à la base, écrit database/migrations/…
flask migrate                         # applique
flask migrate:rollback --step 1       # annule
flask migrate:status                  # [x] appliquée, [ ] en attente
```

Relisez chaque migration générée. Alembic ne voit pas les renommages : il les écrit comme une suppression suivie d'un ajout.

Dans les tests, `DB.create_all()` crée les tables sans passer par les migrations. C'est pratique avec `DB_DATABASE=:memory:`.

## Authentification

Le `User` du squelette hache son mot de passe tout seul, à chaque affectation (`create`, `update`, `fill`, `user.password = ...`) :

```python
from flask_artisan.auth import Authenticatable, HasApiTokens
from flask_artisan.database import Mapped, Model


class User(Authenticatable, HasApiTokens, Model):
    email: Mapped[str]
    password: Mapped[str]


user = User.create(email="a@x", password="secret")   # stocké haché (scrypt)
user.check_password("secret")                        # True
```

Deux guards sont déclarés dans `config/auth.py` : `web` (session Flask) et `api` (token Bearer en base).

```python
from flask_artisan import Auth

Auth.attempt(email=email, password=password)   # session : True/False
Auth.user(); Auth.id(); Auth.check()
Auth.login(user); Auth.logout()

user = Auth.validate(email=email, password=password)   # l'utilisateur ou None, sans connexion
token = user.create_token("mobile")                     # "<id>|<secret>", visible une seule fois
Auth.guard("api").user()                                # depuis "Authorization: Bearer <token>"
Auth.user().current_access_token().delete()             # révoque le token
```

Protégez une route avec le middleware `auth` (guard par défaut) ou `auth:api`. Dans une route `auth:api`, `Auth.user()` renvoie l'utilisateur du token. Sans utilisateur, `auth:api` répond toujours 401 JSON. Avec un guard session, un client qui attend du JSON reçoit un 401 ; un navigateur est redirigé vers la route nommée `login` si elle existe. `last_used_at` d'un token est mis à jour au plus une fois par minute.

Le projet généré expose `/api/login`, `/api/user` et `/api/logout` :

```bash
flask make:migration init && flask migrate     # tables users et personal_access_tokens
curl -X POST localhost:5000/api/login -H 'Content-Type: application/json' \
     -d '{"email": "a@x", "password": "secret"}'          # {"token": "1|..."}
curl localhost:5000/api/user -H 'Authorization: Bearer 1|...'
```

La session est un cookie signé avec `APP_KEY` : cette clé est obligatoire. Changer le mot de passe d'un utilisateur ferme ses sessions ; un `logout` ne fait que vider le cookie du navigateur courant (un cookie copié reste valide jusqu'à `PERMANENT_SESSION_LIFETIME`, 31 jours par défaut, réglable dans `config/flask.py`). Seul le hash SHA-256 de chaque token est stocké.

## Console

Les générateurs écrivent le fichier au bon endroit, avec un squelette prêt à l'emploi :

```bash
flask make:controller PhotoController            # app/http/controllers/photo_controller.py
flask make:controller PhotoController --resource # les 7 méthodes de Route.resource
flask make:controller Admin/UserController       # sous-dossier admin/
flask make:model Post                            # app/models/post.py
flask make:middleware EnsureJson                 # app/http/middleware/ensure_json.py
flask make:provider PaymentServiceProvider       # app/providers/payment_service_provider.py
flask make:command SendEmails                    # app/console/commands/send_emails.py → flask app:send-emails
```

Un fichier existant n'est jamais écrasé sans `--force`. `make:middleware` et `make:provider` affichent la ligne à ajouter au kernel ou à `config/app.py`.

Pas de `make:model -m` : les migrations sont générées depuis les colonnes du modèle. Ajoutez-les, puis lancez `flask make:migration`.

Vos commandes sont des commandes [Click](https://click.palletsprojects.com) dans `app/console/commands/`. Elles sont découvertes toutes seules et s'exécutent dans le contexte de l'application. Un fichier qui ne s'importe pas fait échouer les commandes du projet avec son nom (sur `flask --help`, Flask affiche l'erreur mais rend la main normalement). Les commandes du framework (`make:*`, `migrate`, `route:list`) et l'app web ne sont pas touchées :

```python
# app/console/commands/send_emails.py
import click

from app.models.user import User


@click.command("app:send-emails")
@click.argument("user_id", type=int)
def send_emails(user_id):
    """Envoie les emails en attente d'un utilisateur."""
    click.echo(User.find_or_fail(user_id).email)
```

`flask route:list` affiche les routes déclarées avec `Route` :

```
Méthodes   URI          Nom         Action                 Middlewares
POST       /api/login   api.login   AuthController@login
GET        /api/user    api.user    AuthController@user    Authenticate:api
```

## Service providers

```python
from flask_artisan import ServiceProvider


class MailServiceProvider(ServiceProvider):
    def register(self):
        self.app.singleton(Mailer, SmtpMailer)

    def boot(self):
        mail_extension.init_app(self.app)  # n'importe quelle extension Flask
```

Ajoutez la classe à `providers` dans `config/app.py`.

## Configuration

```python
# config/app.py
from flask_artisan import env

config = {"name": env("APP_NAME", "Blog"), "debug": env("APP_DEBUG", False)}
```

```python
from flask_artisan import config

config("app.name")
config("app.timezone", "UTC")  # valeur par défaut
```

## Façades

```python
from flask_artisan import Config, Facade

Config.get("app.name")


class Mail(Facade):
    accessor = Mailer  # n'importe quelle clé du conteneur


Mail.send(...)
```

## Feuille de route v0.1 (publiée)

1. ✅ Socle : package, Application, conteneur, providers, config, façades
2. ✅ Routage et middlewares (`routes/web.py`, controllers en classes)
3. ✅ ORM façon Eloquent sur SQLAlchemy, migrations
4. ✅ Authentification (façade `Auth`, guards session et token)
5. ✅ Commandes `flask make:*`, `flask migrate`, `flask route:list`

## Contribuer

Voir [CONTRIBUTING.md](https://github.com/ahoblepierre/flask-artisan/blob/main/CONTRIBUTING.md).

## Licence

MIT
