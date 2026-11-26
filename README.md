# Flask-Artisan

**Les conventions de Laravel, mais c'est du Flask.**

Flask-Artisan donne une structure prête à l'emploi aux applications Flask : conteneur de services,
service providers, configuration par fichiers, façades et helpers. L'application reste un vrai
objet `Flask` : `flask run`, les extensions Flask et leur documentation fonctionnent tels quels.

> Version 0.6 (alpha) : l'API peut encore changer avant la 1.0. Voir le [changelog](https://github.com/ahoblepierre/flask-artisan/blob/main/CHANGELOG.md).

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

## Validation

Une `FormRequest` déclare ses règles ; annotée dans un controller, elle est construite, autorisée puis validée **avant** l'appel de la méthode :

```python
# app/http/requests/store_post_request.py   (flask make:request StorePostRequest)
from flask_artisan.validation import FormRequest


class StorePostRequest(FormRequest):
    def authorize(self):          # False → 403 {"message": "This action is unauthorized."}
        return True

    def rules(self):
        return {
            "title": "required|string|max:255",
            "email": "required|email|unique:users,email",
            "tags": ["sometimes", "array"],          # forme liste : utile si un paramètre contient « | »
        }

    def messages(self):           # optionnel : "champ.règle" ou "règle"
        return {"email.unique": "Cet email est déjà utilisé."}


class PostController:
    def store(self, request: StorePostRequest):
        return Post.create(**request.validated()), 201   # seulement les champs avec une règle
```

Données lues : paramètres de l'URL fusionnés avec le corps (JSON objet, sinon formulaire). En cas d'échec, réponse **422** :

```json
{"message": "The title field is required. (and 1 more error)",
 "errors": {"title": ["The title field is required."], "email": ["The email field must be a valid email address."]}}
```

Hors controller : `validate(data, rules)` rend les données validées ou lève `ValidationError` (qui devient la même réponse 422 si elle sort d'une vue) ; `Validator(data, rules).fails()` / `.errors()` pour décider soi-même.

| Règles | |
|---|---|
| Présence | `required`, `required_with:a,b`, `nullable`, `sometimes` |
| Types | `string`, `integer`, `numeric`, `boolean`, `array`, `email`, `url`, `date` |
| Taille | `min:n`, `max:n`, `between:a,b` (valeur si `numeric`/`integer`, éléments pour une liste, longueur sinon) |
| Valeurs | `in:a,b`, `not_in:a,b`, `confirmed`, `same:champ`, `regex:motif` |
| Base | `unique:table[,colonne[,id_ignoré[,colonne_id]]]`, `exists:table[,colonne]` |

Un champ absent ou vide n'est soumis qu'aux règles de présence ; `None` échoue toutes les autres règles sauf avec `nullable`. Pour ignorer la ligne courante lors d'une mise à jour : `f"unique:users,email,{request.view_args['id']}"`. Les valeurs ne sont pas converties (`"42"` reste une chaîne).

## Événements

Un événement annonce ce qui s'est passé ; des écouteurs, déclarés ailleurs, y réagissent. Le code qui émet ne connaît pas ceux qui écoutent : ajouter un effet (un mail, un log, une statistique) ne touche pas au code métier.

### Définir un événement

Un événement est un objet ordinaire qui transporte des données, en général une `dataclass` :

```python
# app/events/order_shipped.py   (flask make:event OrderShipped)
from dataclasses import dataclass


@dataclass
class OrderShipped:
    order: Order
```

Aucune classe de base n'est imposée. Un événement est identifié par sa **classe**.

### Écrire un écouteur

La forme habituelle est une classe avec une méthode `handle(self, event)` :

```python
# app/listeners/send_shipment_notification.py   (flask make:listener SendShipmentNotification --event OrderShipped)
from app.events.order_shipped import OrderShipped


class SendShipmentNotification:
    def __init__(self, mailer: Mailer):   # dépendances injectées par le conteneur
        self.mailer = mailer

    def handle(self, event: OrderShipped):
        self.mailer.send(event.order.user, "Votre commande est partie")
```

L'écouteur est construit par le conteneur **à chaque émission** : ses dépendances sont injectées dans `__init__` comme pour un controller.

Deux autres formes sont acceptées :

```python
Event.listen(OrderShipped, (ShipmentListeners, "on_shipped"))   # une autre méthode que handle
Event.listen(OrderShipped, lambda event: print(event.order.id))  # une simple fonction
```

Un écouteur invalide (classe sans `handle`, méthode inexistante, objet non appelable) est refusé immédiatement par une `TypeError`, pas à la première émission.

### Déclarer les écouteurs

Dans `app/providers/event_service_provider.py` (fourni par le squelette et déjà présent dans `config/app.py`) :

```python
from app.events.order_shipped import OrderShipped
from app.listeners.send_shipment_notification import SendShipmentNotification
from app.listeners.update_stock import UpdateStock
from flask_artisan.events import EventServiceProvider as BaseEventServiceProvider


class EventServiceProvider(BaseEventServiceProvider):
    listen = {
        OrderShipped: [SendShipmentNotification, UpdateStock],
    }
```

On peut aussi déclarer un écouteur dans le `boot()` de n'importe quel provider : `Event.listen(OrderShipped, UpdateStock)` (un écouteur ou une liste).

### Émettre

```python
from flask_artisan import Event

Event.dispatch(OrderShipped(order))
```

Le helper `event(OrderShipped(order))` fait la même chose (importé de `flask_artisan` ; attention au conflit de nom si vous importez aussi `sqlalchemy.event`).

- **Synchrone** : les écouteurs s'exécutent tout de suite, dans la requête ou la commande qui émet. Pas besoin de contexte de requête : une commande `flask` ou un script peuvent émettre.
- **Valeur renvoyée** : `dispatch` rend la liste des valeurs renvoyées par les écouteurs appelés, dans l'ordre.
- **Ordre** : d'abord les écouteurs de la classe exacte, puis ceux des classes parentes (un écouteur de `Shipped` reçoit aussi un `ExpressShipped(Shipped)`) ; pour une même classe, l'ordre de déclaration.
- **Arrêt** : un écouteur qui renvoie `False` empêche les suivants d'être appelés.
- **Erreurs** : une exception levée par un écouteur interrompt l'émission et remonte à l'appelant (une erreur dans une route donne donc une 500, comme une erreur du controller).

Autres méthodes : `Event.has_listeners(OrderShipped)`, `Event.forget(OrderShipped)` (retire les écouteurs de cette classe).

### Tester avec `Event.fake()`

`Event.fake()` enregistre les événements émis **sans exécuter leurs écouteurs**, puis permet de vérifier ce qui a été émis. Utilisé comme bloc `with`, il rend au dispatcher son fonctionnement normal à la sortie :

```python
from wsgi import app

from flask_artisan import Event


def test_shipping_announces_the_order():
    with Event.fake() as fake:
        app.test_client().post("/api/orders/1/ship")

    fake.assert_dispatched(OrderShipped)
    fake.assert_dispatched(OrderShipped, lambda e: e.order.id == 1)
    fake.assert_dispatched_times(OrderShipped, 1)
    fake.assert_not_dispatched(OrderCancelled)
```

| Méthode | Vérifie que… |
|---|---|
| `assert_dispatched(Classe, callback=None)` | l'événement a été émis au moins une fois (et que `callback(event)` est vrai pour l'un d'eux) |
| `assert_dispatched_times(Classe, n)` | l'événement a été émis exactement `n` fois |
| `assert_not_dispatched(Classe, callback=None)` | l'événement n'a pas été émis (ou aucun ne satisfait `callback`) |
| `assert_nothing_dispatched()` | aucun événement n'a été émis |
| `dispatched(Classe)` | (pas une assertion) la liste des événements émis de cette classe |

- Un événement simulé n'exécute aucun écouteur : `Event.dispatch` renvoie alors `[]`.
- `Event.fake(OrderShipped, …)` ne simule que ces événements (et leurs sous-classes) ; les autres exécutent normalement leurs écouteurs. **Tous** restent vérifiables par les assertions.
- Le fake est un mode du dispatcher de l'application : un service qui a reçu le dispatcher avant l'appel à `fake()` passe aussi par le fake.
- Rappeler `Event.fake(...)` remplace le précédent et repart de zéro.
- **Restaurer.** Les tests du projet généré partagent une seule application (`from wsgi import app`) : un fake laissé actif bloquerait les écouteurs des tests suivants. Utilisez `with Event.fake() as fake:`, ou appelez `fake.restore()` en fin de test. Les assertions restent utilisables après la restauration.

### Générateurs

```bash
flask make:event OrderShipped                                       # app/events/order_shipped.py
flask make:listener SendShipmentNotification --event OrderShipped   # app/listeners/send_shipment_notification.py
flask make:listener Billing/MarkPaid --event Billing/InvoicePaid    # sous-dossiers permis
```

Avec `--event`, le fichier de l'événement doit déjà exister : sinon rien n'est écrit et la commande indique le chemin attendu. Après création, `make:listener` affiche les imports et l'entrée à ajouter dans `listen`.

Un écouteur qui hérite de `ShouldQueue` est exécuté en arrière-plan par la file d'attente : voir « Queues ».

## Mail

Chaque mail de l'application est une classe, un *mailable*, qui décrit son sujet, ses templates et ses pièces jointes. On l'envoie en une ligne, depuis un controller, un écouteur d'événement ou une commande :

```python
from flask_artisan import Mail

Mail.to(order.user).send(OrderShipped(order))
```

La façon dont le mail part se choisit dans `.env`, sans toucher au code : écrit dans les logs pendant le développement, envoyé par SMTP en production.

### Configurer

Le transport se choisit avec `MAIL_MAILER` dans `.env` :

| Transport | Effet | Usage |
|---|---|---|
| `log` (défaut) | le mail complet est écrit dans les logs de l'application (visible quand `APP_DEBUG=true`) | développement |
| `smtp` | le mail est envoyé à un serveur SMTP | production, ou Mailtrap pour tester |
| `array` | le mail est gardé en mémoire (`Mail.transport("array").messages`) | tests qui vérifient le rendu |

Pour SMTP, renseignez le serveur de votre fournisseur. Tous les fournisseurs courants (Brevo, Mailgun, Amazon SES, SendGrid, Postmark, Mailtrap…) proposent un accès SMTP :

```ini
MAIL_MAILER=smtp
MAIL_HOST=smtp.mailtrap.io
MAIL_PORT=587
MAIL_USERNAME=votre-identifiant
MAIL_PASSWORD=votre-mot-de-passe
MAIL_ENCRYPTION=tls          # tls pour le port 587 (STARTTLS), ssl pour le port 465, vide sinon (certificat vérifié)
MAIL_FROM_ADDRESS=hello@monsite.fr
MAIL_FROM_NAME="Mon site"
```

Ces variables sont lues par `config/mail.py`. On peut y déclarer plusieurs *mailers* (par exemple deux serveurs SMTP) et en choisir un à l'envoi avec `Mail.mailer("nom")`. La configuration est relue à chaque envoi. Un projet sans `config/mail.py` (créé avant la 0.4) fonctionne aussi : il utilise le transport `log` et l'expéditeur `hello@example.com`.

L'expéditeur (`From`) est celui de la config, le même pour tous les mails.

### Écrire un mailable

```bash
flask make:mail OrderShipped
# Créé : app/mail/order_shipped.py
# Créé : resources/views/emails/order_shipped.html
```

```python
# app/mail/order_shipped.py
from flask_artisan.mail import Attachment, Mailable


class OrderShipped(Mailable):
    subject = "Votre commande est expédiée"
    view = "emails/order_shipped.html"     # version HTML
    text = "emails/order_shipped.txt"      # version texte (facultative)
    reply_to = "support@monsite.fr"        # facultatif

    def __init__(self, order):
        self.order = order

    def attachments(self):
        return [
            Attachment.from_path(self.order.invoice_path, name="facture.pdf"),
            Attachment.from_data(self.order.to_csv(), "commande.csv"),
        ]
```

```html
<!-- resources/views/emails/order_shipped.html -->
<p>Bonjour {{ order.user.name }},</p>
<p>Votre commande n° {{ order.id }} est partie.</p>
```

- **Templates.** Ce sont des templates Jinja, ceux de Flask. Ils sont cherchés dans `resources/views/`, puis dans `templates/` (le dossier habituel de Flask, qui continue de fonctionner). Les variables sont échappées dans un `.html`, pas dans un `.txt`.
- **HTML, texte ou les deux.** Avec `view` et `text`, le mail contient les deux versions et la messagerie choisit. Il en faut au moins une.
- **Variables du template.** Les attributs publics du mailable (`self.order`) sont disponibles dans le template, ainsi que `subject`. Les attributs qui commencent par `_` ne le sont pas. Pour choisir soi-même, surchargez `context()` :

  ```python
  def context(self):
      return {"order": self.order, "total": self.order.total_ttc()}
  ```

- **Sujet calculé.** `subject` peut être une propriété :

  ```python
  @property
  def subject(self):
      return f"Commande n° {self.order.id} expédiée"
  ```

- **Pièces jointes.** `Attachment.from_path(chemin, name=None, mime=None)` lit le fichier au moment de l'envoi. `Attachment.from_data(contenu, nom, mime=None)` joint des octets ou du texte. Le type MIME est deviné à partir du nom.

### Envoyer

```python
from flask_artisan import Mail

Mail.to(user).send(Welcome(user))
Mail.to("alice@x.org").cc("compta@x.org").bcc("archive@x.org").send(InvoicePaid(invoice))
Mail.to(["a@x.org", "b@x.org"]).send(Newsletter())
Mail.mailer("smtp").to(user).send(Welcome(user))   # un mailer précis de config/mail.py
```

Un destinataire peut s'écrire :

- `"alice@x.org"` ou `"Alice <alice@x.org>"` ;
- `("alice@x.org", "Alice")` ;
- un objet avec un attribut `email` (et `name`, s'il existe) : le modèle `User` convient tel quel ;
- une liste de ces formes.

Les adresses en copie cachée (`bcc`) reçoivent le mail mais n'apparaissent pas dans ses en-têtes.

**Depuis un écouteur d'événement**, c'est l'usage le plus courant :

```python
# app/listeners/send_shipment_notification.py
from flask_artisan import Mail

from app.events.order_shipped import OrderShipped
from app.mail.order_shipped import OrderShipped as OrderShippedMail


class SendShipmentNotification:
    def handle(self, event: OrderShipped):
        Mail.to(event.order.user).send(OrderShippedMail(event.order))
```

L'envoi marche aussi hors d'une requête (commande `flask`, script) : les templates sont rendus avec l'application. Pour qu'un `url_for(...)` y construise un lien absolu, Flask doit connaître l'adresse du site : déclarez-la dans `config/flask.py`, sinon `url_for` lève une erreur hors requête.

```python
# config/flask.py
config = {
    "SERVER_NAME": "monsite.fr",
    "PREFERRED_URL_SCHEME": "https",
}
```

Dans un template de mail, utilisez `url_for("nom.de.route", _external=True)` pour un lien complet.

**Erreurs.** `send` lève une erreur plutôt que de perdre un mail en silence :

- une erreur du serveur SMTP (connexion, authentification, destinataire refusé) remonte telle quelle (exceptions de `smtplib`) ;
- un destinataire d'une forme inconnue lève `TypeError` ; une adresse invalide (sans `@`, ou plusieurs adresses dans une seule chaîne), aucun destinataire, ou un mailable sans `view` ni `text` lève `ValueError` ;
- un expéditeur (`MAIL_FROM_ADDRESS`) ou un port (`MAIL_PORT`) invalide lève `ValueError` qui nomme le réglage ;
- une option inconnue dans un mailer `smtp` de `config/mail.py` lève `TypeError` : une faute de frappe ne fait pas partir le mail en clair ;
- un saut de ligne dans le sujet, un nom ou une adresse lève `ValueError` : il servirait à injecter des en-têtes.

`send` est synchrone : la requête attend la réponse du serveur SMTP. Pour ne pas la faire attendre, mettez le mail en file : `Mail.to(user).queue(Welcome(user))` (voir « Queues »).

### Tester avec `Mail.fake()`

`Mail.fake()` enregistre les mails envoyés **sans les rendre ni les envoyer**, puis permet de vérifier ce qui est parti et à qui. Utilisé comme bloc `with`, il rend au mailer son fonctionnement normal à la sortie :

```python
from wsgi import app

from flask_artisan import Mail
from app.mail.invoice_paid import InvoicePaid
from app.mail.order_shipped import OrderShipped


def test_shipping_mails_the_customer():
    with Mail.fake() as fake:
        app.test_client().post("/api/orders/1/ship")

    fake.assert_sent(OrderShipped)
    fake.assert_sent(OrderShipped, lambda mail: mail.order.id == 1 and mail.has_to("a@x.org"))
    fake.assert_sent_times(OrderShipped, 1)
    fake.assert_not_sent(InvoicePaid)
```

| Méthode | Vérifie que… |
|---|---|
| `assert_sent(Classe, callback=None)` | le mail a été envoyé au moins une fois (et que `callback(mail)` est vrai pour l'un d'eux) |
| `assert_sent_times(Classe, n)` | le mail a été envoyé exactement `n` fois |
| `assert_not_sent(Classe, callback=None)` | le mail n'a pas été envoyé (ou aucun ne satisfait `callback`) |
| `assert_nothing_sent()` | aucun mail n'a été envoyé |
| `sent(Classe)` | (pas une assertion) la liste des mails envoyés de cette classe |

- Dans le callback, `mail.has_to(x)`, `mail.has_cc(x)` et `mail.has_bcc(x)` vérifient les destinataires. Ils acceptent les mêmes formes qu'un destinataire et ignorent la casse.
- Une sous-classe compte pour sa parente : `assert_sent(Mailable)` vérifie qu'un mail quelconque est parti.
- Un destinataire invalide lève toujours son erreur, même sous fake.
- Le fake est un mode du mailer de l'application : un service qui a reçu le mailer avant l'appel à `fake()` passe aussi par le fake. Rappeler `Mail.fake()` repart de zéro.
- L'objet envoyé connaît ensuite ses destinataires (`mail.has_to(...)`), avec ou sans fake.
- **Mails en file.** `Mail.to(...).queue(...)` et `later(...)` sont enregistrés à part : `assert_queued(Classe, callback=None)`, `assert_not_queued(Classe, callback=None)`, `assert_nothing_queued()` et `queued(Classe)`. `assert_sent` ne compte pas les mails mis en file.
- **Restaurer.** Les tests du projet généré partagent une seule application : utilisez `with Mail.fake() as fake:`, ou appelez `fake.restore()` en fin de test.

**Vérifier le rendu.** Le fake ne rend pas les templates. Pour tester le contenu réel du mail, envoyez-le par le transport `array` :

```python
def test_welcome_mail_content():
    Mail.mailer("array").to("a@x.org").send(Welcome(user))
    message = Mail.transport("array").messages[-1]   # un EmailMessage de la bibliothèque standard
    assert message["Subject"] == "Bienvenue"
    assert "Bonjour" in message.get_body(("html",)).get_content()
    Mail.transport("array").flush()                  # vide les messages gardés
```

### Générateur

```bash
flask make:mail OrderShipped        # app/mail/order_shipped.py + resources/views/emails/order_shipped.html
flask make:mail Billing/Invoice     # app/mail/billing/invoice.py + resources/views/emails/billing/invoice.html
```

Si l'un des deux fichiers existe, rien n'est écrit (sauf avec `--force`, qui écrase les deux). La commande affiche ensuite l'import et l'appel `Mail.to(...).send(...)`.

## Queues

Certaines tâches n'ont rien à faire dans une requête HTTP : envoyer un mail, traiter une vidéo, appeler une API lente. Une **file d'attente** les met de côté ; un processus à part, le **worker**, les exécute en arrière-plan et les réessaie en cas d'échec. La requête répond tout de suite.

Flask-Artisan ne réinvente pas le moteur : il pose l'API de Laravel sur [RQ](https://python-rq.org) (Redis), qui gère le stockage, le worker, les nouvelles tentatives, la coupure des jobs trop longs, les jobs différés et le registre des échecs.

### Installer

Le pilote `sync` (défaut) exécute les jobs tout de suite, sans rien installer : pratique en développement et dans les tests. Pour une vraie file, il faut RQ et un serveur Redis :

```bash
pip install "flask-artisan[rq]"
docker run -d -p 6379:6379 redis:7     # un Redis local pour le développement
```

```ini
# .env
QUEUE_CONNECTION=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

Les connexions sont déclarées dans `config/queue.py` (`sync` et `redis` dans le squelette) ; la configuration est relue à chaque envoi. Un projet sans ce fichier utilise `sync`.

**Sécurité.** Le worker exécute ce qu'il lit dans Redis : quiconque peut écrire dans votre Redis peut lui faire exécuter du code (c'est vrai de RQ, Celery ou Laravel). Traitez Redis comme une base de données : mot de passe, réseau privé, connexion chiffrée (`rediss://`) s'il passe par Internet. Flask-Artisan stocke les jobs en JSON (jamais en `pickle`) et n'exécute que des classes de job, mais ce sont des garde-fous, pas une barrière.

### Écrire un job

```bash
flask make:job ProcessPodcast        # app/jobs/process_podcast.py
```

```python
# app/jobs/process_podcast.py
from flask_artisan.queue import Job

from app.models.podcast import Podcast
from app.services.transcoder import Transcoder


class ProcessPodcast(Job):
    queue = "audio"          # file (défaut : celle de la connexion, "default")
    tries = 3                # nombre total d'essais (défaut : 1)
    backoff = [10, 60]       # secondes avant le 2e, puis le 3e essai (défaut : 0)
    timeout = 120            # secondes avant que le worker coupe le job (défaut : 60)

    def __init__(self, podcast: Podcast):
        self.podcast = podcast

    def handle(self, transcoder: Transcoder):     # dépendances injectées par le conteneur
        transcoder.run(self.podcast)

    def failed(self, exc: Exception):             # facultatif : après le dernier essai raté
        self.podcast.update(status="failed")
```

- `backoff` peut être un nombre (le même délai à chaque fois) ou une liste ; si la liste est plus courte que le nombre d'essais, sa dernière valeur est répétée.
- `failed(exc)` est appelé **une fois**, quand il ne reste plus d'essai. Une erreur levée dans `failed` est journalisée sans masquer celle du job.

**Ce qui voyage dans la file.** Les attributs publics du job (ceux qui ne commencent pas par `_`) sont enregistrés en JSON. Sont acceptés : les valeurs JSON (`str`, nombres, `bool`, `None`, listes, dicts à clés `str`), les `datetime`, `date`, `Decimal`, et les **modèles**, qui voyagent par leur identifiant et sont **rechargés depuis la base** au moment de l'exécution : le job travaille sur des données à jour. Tout le reste (un fichier ouvert, un client HTTP…) lève `TypeError` dès l'envoi, en nommant l'attribut. Un modèle doit être enregistré (avoir un `id`) ; s'il a été supprimé avant l'exécution, le job échoue avec `ModelNotFound`.

Le job est reconstruit **sans appeler `__init__`** : ne mettez dans `__init__` que des affectations. Les classes de jobs doivent être définies au niveau d'un module (pas dans une fonction).

### Envoyer un job

```python
from flask_artisan import Queue, dispatch

ProcessPodcast.dispatch(podcast)                          # crée le job et le met en file
dispatch(ProcessPodcast(podcast).on_queue("urgent"))      # sur une autre file
dispatch(ProcessPodcast(podcast).delay(60))               # dans 60 secondes (ou un timedelta)
Queue.connection("redis").push(ProcessPodcast(podcast))   # sur une connexion précise
ProcessPodcast.dispatch_sync(podcast)                     # tout de suite, quel que soit le pilote
```

`dispatch` renvoie l'identifiant du job RQ (ou `None` avec `sync`). Avec `sync`, le job s'exécute immédiatement, après un aller-retour par la sérialisation (les erreurs de sérialisation apparaissent donc dès le développement) ; son exception remonte à l'appelant après l'appel de `failed`, et `tries`, `backoff` et `delay` sont ignorés.

**Transactions.** Un job envoyé pendant une transaction peut être exécuté avant le `commit` : le worker ne trouverait pas encore le modèle. Envoyez-le après la transaction.

### Lancer le worker

```bash
flask queue:work                      # connexion par défaut, file de la connexion
flask queue:work redis --queue urgent,default   # plusieurs files, par ordre de priorité
flask queue:work --burst              # s'arrête quand les files sont vides
```

**Le worker n'écoute que les files qu'on lui donne** : sans `--queue`, seulement celle de la connexion (`default`). Un job, un mail ou un écouteur envoyé sur une autre file (`queue = "audio"`) attend tant qu'aucun worker n'écoute cette file : listez-les toutes, par ordre de priorité (`--queue audio,listeners,mails,default`), ou lancez un worker par file.

Le worker exécute les jobs **dans le processus de l'application** (comme `php artisan queue:work`), chacun avec sa propre session de base de données. Il gère aussi les jobs différés et les essais espacés.

**En production**, faites-le tourner sous un superviseur qui le relance s'il s'arrête, et **redémarrez-le après chaque déploiement** : il charge le code une seule fois. Avec systemd :

```ini
# /etc/systemd/system/monsite-worker.service
[Service]
WorkingDirectory=/srv/monsite
ExecStart=/srv/monsite/.venv/bin/flask queue:work --queue audio,listeners,mails,default
Restart=always

[Install]
WantedBy=multi-user.target
```

Le worker RQ ne tourne pas sous Windows natif : utilisez WSL ou Docker.

### Jobs en échec

Un job qui a épuisé ses essais va dans le registre des échecs de RQ :

```bash
flask queue:failed                # id, classe, file, date, dernière ligne de l'erreur
flask queue:retry <id> [<id>…]    # le remet en file, avec tous ses essais
flask queue:retry all
flask queue:forget <id>           # le supprime
flask queue:flush                 # les supprime tous
```

Ces commandes couvrent toutes les files de la connexion et acceptent `--connection <nom>`. Les outils de RQ (`rq info`, [rq-dashboard](https://github.com/Parallels/rq-dashboard)) marchent aussi, à condition de leur indiquer le sérialiseur JSON : `--serializer rq.serializers.JSONSerializer`.

### Mails et écouteurs en file d'attente

```python
Mail.to(user).queue(Welcome(user))         # le worker enverra le mail
Mail.to(user).later(600, Reminder(user))   # dans 10 minutes
```

Les destinataires sont vérifiés tout de suite ; le mailable voyage comme un job (ses modèles par identifiant). Un attribut `queue = "mails"` sur la classe du mailable choisit la file.

Un écouteur d'événement qui hérite de `ShouldQueue` n'est pas appelé pendant `Event.dispatch` : il est mis en file, et le worker l'exécute avec l'événement reconstruit.

```python
from flask_artisan.queue import ShouldQueue


class SendShipmentNotification(ShouldQueue):
    queue = "listeners"      # facultatif, comme tries, backoff, timeout
    tries = 3

    def handle(self, event: OrderShipped):
        Mail.to(event.order.user).send(OrderShippedMail(event.order))
```

Il se déclare comme les autres écouteurs (dans `listen`, en classe ou en tuple `(Classe, "méthode")`). L'événement doit être une classe de l'application et être sérialisable (mêmes règles qu'un job) ; `Event.dispatch` renvoie `None` pour cet écouteur, qui ne peut pas arrêter la propagation.

### Tester

`Queue.fake()` enregistre les jobs poussés **sans les exécuter** (ils sont tout de même sérialisés : une erreur de sérialisation reste levée). Utilisé comme bloc `with`, il se restaure à la sortie :

```python
from wsgi import app

from flask_artisan import Queue
from app.jobs.process_podcast import ProcessPodcast


def test_upload_queues_processing():
    with Queue.fake() as fake:
        app.test_client().post("/api/podcasts", json={"title": "Épisode 1"})

    fake.assert_pushed(ProcessPodcast)
    fake.assert_pushed(ProcessPodcast, lambda job: job.podcast.title == "Épisode 1")
    fake.assert_pushed_on("audio", ProcessPodcast)
```

| Méthode | Vérifie que… |
|---|---|
| `assert_pushed(Classe, callback=None)` | le job a été poussé au moins une fois (et que `callback(job)` est vrai pour l'un d'eux) |
| `assert_pushed_times(Classe, n)` | le job a été poussé exactement `n` fois |
| `assert_not_pushed(Classe, callback=None)` | le job n'a pas été poussé (ou aucun ne satisfait `callback`) |
| `assert_nothing_pushed()` | aucun job n'a été poussé |
| `assert_pushed_on(file, Classe)` | le job a été poussé sur cette file |
| `pushed(Classe)` | (pas une assertion) la liste des jobs poussés |

Le callback reçoit l'instance passée à `dispatch` ; `job.queue_name` et `job.delay_seconds` y donnent la file et le délai demandés. `dispatch_sync` n'est pas intercepté. Pour tester ce que fait un job, appelez simplement `ProcessPodcast.dispatch_sync(...)` ou laissez le pilote `sync`.

## Cache

Le cache garde de côté le résultat d'un calcul coûteux (statistiques, réponse d'une API tierce, page de résultats) pour ne pas le refaire à chaque requête, et sert à compter des choses (tentatives, vues).

```python
from datetime import timedelta

from flask_artisan import Cache

stats = Cache.remember("stats:dashboard", 600, lambda: compute_stats())   # calculé au plus une fois toutes les 10 minutes
Cache.put("weather:paris", forecast, timedelta(hours=1))
Cache.get("weather:paris")                       # None si absent ou expiré
Cache.increment("visits")
Cache.forget("stats:dashboard")
```

### Configurer

Le store se choisit avec `CACHE_STORE` dans `.env` :

| Store | Où vont les valeurs | Usage |
|---|---|---|
| `file` (défaut) | un fichier par clé dans `storage/cache/` du projet | une seule machine, sans Redis |
| `redis` | le serveur Redis de `REDIS_URL` | production, plusieurs processus ou serveurs |
| `array` | la mémoire du processus, perdue au redémarrage | tests |

`redis` demande redis-py : `pip install "flask-artisan[redis]"` (déjà présent avec `[rq]`). Le cache peut partager le Redis des [queues](#queues) : ses clés portent un préfixe (`CACHE_PREFIX`, par défaut le nom de l'application suivi de `_cache:`), et `Cache.flush()` ne supprime que les clés de ce préfixe, jamais les files d'attente. Aucune version minimale de Redis n'est exigée.

Les stores sont déclarés dans `config/cache.py` (le squelette ajoute `storage/` au `.gitignore`). La configuration est relue à chaque appel ; un projet sans ce fichier utilise `file`, et son store `redis` lit `REDIS_URL`. Les fichiers du store `file` sont créés en mode `0644`, lisibles par une commande planifiée qui tournerait sous un autre utilisateur que le serveur web ; `flask cache:clear` n'efface que ces fichiers, jamais un autre fichier du dossier.

`Cache.get(...)` et les autres méthodes visent le store par défaut ; `Cache.store("redis")` en désigne un autre :

```python
Cache.store("redis").put("k", "v", 60)
```

### Méthodes

| Méthode | Effet |
|---|---|
| `get(key, default=None)` | la valeur, ou `default` (appelé s'il s'agit d'une fonction) |
| `put(key, value, ttl=None)` | stocke ; `ttl` en secondes ou `timedelta`, `None` = sans expiration |
| `add(key, value, ttl=None)` | stocke seulement si la clé est absente ; renvoie `True` si stockée (atomique, voir [Quel store choisir](#quel-store-choisir)) |
| `forever(key, value)` | `put` sans expiration |
| `remember(key, ttl, callback)` | la valeur en cache, sinon `callback()` stocké puis renvoyé |
| `remember_forever(key, callback)` | idem, sans expiration |
| `has(key)` / `missing(key)` | la clé a-t-elle une valeur ? |
| `pull(key, default=None)` | lit puis supprime |
| `forget(key)` | supprime ; renvoie `True` si la clé existait |
| `increment(key, by=1)` / `decrement(key, by=1)` | ajoute à un entier et renvoie le résultat ; une clé absente vaut 0 ; l'expiration est conservée |
| `flush()` | vide le store |

- `None` équivaut à « absent » : `put(key, None)` supprime la clé, et un `remember` dont le callback renvoie `None` ne stocke rien (il sera rappelé la fois suivante). Un `ttl` de 0 ou négatif supprime aussi la clé.
- Un `ttl` fractionnaire est arrondi à la seconde supérieure.
- `remember` n'est pas atomique : deux requêtes simultanées sur une clé absente peuvent calculer toutes les deux (comme Laravel sans verrou).
- `add`, `increment` et `pull` sont atomiques entre processus avec `redis`, et avec `file` sur une même machine (hors Windows) ; pour plusieurs serveurs, utilisez `redis`.
- Verrous : voir [Verrous](#verrous).

### Ce qu'on peut mettre en cache

Les valeurs sont enregistrées en JSON (jamais en `pickle`) : `str`, nombres, `bool`, listes, dicts à clés `str`, ainsi que `datetime`, `date` et `Decimal`. Toute autre valeur lève `TypeError` dès `put`, en nommant la clé.

Un **modèle** est stocké par son identifiant et **relu en base à chaque lecture** : la donnée est à jour, mais le cache n'épargne pas la requête. Pour éviter la base, mettez en cache des données calculées ou `to_dict()` :

```python
user_card = Cache.remember(f"user:{user.id}:card", 300, lambda: user.to_dict())
```

Une valeur devenue illisible (modèle supprimé depuis, classe déplacée, fichier corrompu) compte comme **absente** : la clé est supprimée, un avertissement est journalisé, et `remember` recalcule. Le cache ne lève jamais de 404.

### Tester

Utilisez le store `array` dans les tests (`CACHE_STORE=array`, ou `Cache.store("array")`). Les tests du projet généré partagent une application : videz le cache entre deux tests.

```python
import pytest

from flask_artisan import Cache


@pytest.fixture(autouse=True)
def empty_cache():
    yield
    Cache.flush()
```

### Vider le cache

```bash
flask cache:clear            # le store par défaut
flask cache:clear redis      # un store précis
```

## Limitation de débit et verrous

La limitation de débit refuse les requêtes au-delà d'un nombre donné par fenêtre de temps : contre le test de mots de passe en boucle, ou pour protéger une API. Les verrous garantissent qu'un seul processus fait un travail à la fois. Les deux reposent sur le [cache](#cache).

### Le middleware `throttle`

```python
Route.post("/login", AuthController.login).middleware("throttle:5,1")   # 5 requêtes par minute

with Route.middleware("throttle:60,1"):
    Route.get("/photos", PhotoController.index)
```

`throttle:<max>,<minutes>` laisse passer `max` requêtes par fenêtre de `minutes` minutes. Le squelette déclare l'alias dans `app/http/kernel.py`, limite le groupe `api` à `throttle:60,1` et `/api/login` à `throttle:5,1`.

Chaque réponse acceptée porte `X-RateLimit-Limit` et `X-RateLimit-Remaining`. Au-delà, la route n'est pas exécutée et le client reçoit :

```
HTTP/1.1 429 TOO MANY REQUESTS
Retry-After: 42
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1764150000

{"message": "Too Many Attempts."}
```

`Retry-After` donne les secondes à attendre, `X-RateLimit-Reset` l'horodatage Unix de réouverture. Une requête refusée ne compte pas : la fenêtre se rouvre à l'heure annoncée.

**Qui est compté.** Par défaut, l'adresse IP du client. Si un middleware `auth` a déjà identifié l'utilisateur **avant** `throttle`, c'est l'utilisateur qui est compté, quelle que soit son IP :

```python
with Route.middleware("auth:api", "throttle:60,1"):   # auth d'abord : limite par utilisateur
    Route.get("/user", AuthController.user)
```

`throttle` n'authentifie jamais lui-même (ni lecture de session, ni requête SQL). Les middlewares d'un groupe passent avant ceux de la route : le `throttle:60,1` du groupe `api` compte donc par IP.

**Compteurs partagés.** Le compteur est lié à la limite et à la personne, pas à la route : toutes les routes en `throttle:60,1` partagent le même compteur pour un client (comme Laravel), alors que `throttle:5,1` en a un autre. Quand deux limites s'appliquent (le groupe `api` et le login), chacune compte, et les en-têtes `X-RateLimit-*` sont ceux de la plus proche de la route.

Des paramètres qui ne sont pas des entiers positifs (`throttle:abc`) lèvent `ValueError` à la première requête.

### Derrière un proxy

Derrière nginx ou un load balancer, Flask voit l'IP du proxy : tous les clients partageraient un seul compteur. Indiquez le nombre de proxys devant l'application dans `.env` :

```env
TRUSTED_PROXIES=1
```

L'IP du client et le schéma (`https`) sont alors lus dans `X-Forwarded-For` et `X-Forwarded-Proto`, posés par le proxy (`ProxyFix` de Werkzeug). L'hôte et le port ne sont pas lus dans `X-Forwarded-Host` / `X-Forwarded-Port` : un proxy qui ne les pose pas laisserait le client choisir l'hôte des URL absolues (liens des mails) ; le proxy doit transmettre l'en-tête `Host`, ou fixez `SERVER_NAME` dans `config/flask.py`. Laissez `0` (défaut) sans proxy : sinon un client pourrait choisir son IP avec un faux `X-Forwarded-For`.

### `RateLimiter`

Pour compter soi-même, par exemple les échecs de connexion par adresse e-mail :

```python
from flask_artisan import Auth, RateLimiter


class AuthController:
    def login(self, request: LoginRequest):
        data = request.validated()
        key = f"login:{data['email'].lower()}"
        if RateLimiter.too_many_attempts(key, 5):
            seconds = RateLimiter.available_in(key)
            return {"message": f"Trop de tentatives, réessayez dans {seconds} s."}, 429
        user = Auth.validate(email=data["email"], password=data["password"])
        if user is None:
            RateLimiter.hit(key, 300)        # fenêtre de 5 minutes
            return {"message": "Invalid credentials."}, 401
        RateLimiter.clear(key)
        return {"token": user.create_token("api")}
```

| Méthode | Effet |
|---|---|
| `hit(key, decay_seconds=60)` | compte une tentative et renvoie le total ; la fenêtre démarre à la première |
| `attempts(key)` | tentatives de la fenêtre en cours |
| `too_many_attempts(key, max_attempts)` | `True` si `max_attempts` est atteint et que la fenêtre n'est pas finie |
| `remaining(key, max_attempts)` | tentatives restantes |
| `available_in(key)` | secondes avant la réouverture (0 si ouverte) |
| `clear(key)` | remet à zéro |
| `attempt(key, max_attempts, callback, decay_seconds=60)` | `False` si trop de tentatives, sinon compte puis renvoie `callback()` (`True` s'il renvoie `None`) |

Les compteurs vont dans le store par défaut, ou dans celui de `cache.limiter` (`config/cache.py`) :

```python
config = {
    "default": env("CACHE_STORE", "file"),
    "limiter": "redis",       # compteurs dans Redis, le reste du cache ailleurs
    ...
}
```

### Verrous

```python
from flask_artisan import Cache

lock = Cache.lock("rapport:mensuel", 120)     # expire seul au bout de 120 s
if lock.get():
    try:
        generer_rapport()
    finally:
        lock.release()
```

| Forme | Effet |
|---|---|
| `Cache.lock(name, seconds=0, owner=None)` | un verrou ; `seconds=0` : sans expiration |
| `lock.get()` | prend le verrou s'il est libre ; `True` / `False` |
| `lock.get(callback)` | si le verrou est libre : le prend, appelle `callback()`, le libère (même en cas d'exception) et renvoie son résultat ; sinon `False` |
| `lock.block(seconds)` / `lock.block(seconds, callback)` | comme `get`, mais attend jusqu'à `seconds` secondes (essai toutes les 250 ms), puis lève `LockTimeoutError` |
| `with Cache.lock(name, seconds):` | prend le verrou, le libère en sortie ; lève `LockTimeoutError` tout de suite s'il est pris |
| `lock.release()` | libère, **seulement si on en est le propriétaire** ; `True` / `False` |
| `lock.force_release()` | libère sans condition |
| `lock.owner` | jeton du propriétaire (aléatoire si non fourni) |
| `Cache.restore_lock(name, owner)` | le verrou d'un autre processus, pour le libérer |

```python
from flask_artisan.cache import LockTimeoutError

try:
    Cache.lock("stock:42", 10).block(5, lambda: decrementer_stock(42))
except LockTimeoutError:
    return {"message": "Réessayez."}, 409
```

Donnez toujours une durée à un verrou pris dans une requête : si le processus meurt avant `release()`, le verrou expire seul. Un processus lent dont le verrou a expiré, puis a été repris par un autre, ne peut pas libérer le verrou du second : `release()` renvoie `False`.

Pour libérer depuis un autre processus (verrou pris dans une requête, travail fini par un job), transmettez le propriétaire :

```python
lock = Cache.lock("import:clients", 600)
if lock.get():
    ImportClients.dispatch(owner=lock.owner)

# dans le job
Cache.restore_lock("import:clients", self.owner).release()
```

### Quel store choisir

| Store | Compteurs et verrous |
|---|---|
| `redis` | sûrs entre processus et entre serveurs (`SET NX`, `INCRBY`, script Lua pour `release`) |
| `file` (défaut) | sûrs entre processus d'**une même machine** (verrou `flock` sur `storage/cache/.lock`) ; pas sous Windows, où ils restent approximatifs |
| `array` | propres à chaque processus : chaque worker gunicorn a ses propres compteurs |

Avec plusieurs serveurs, utilisez `redis` (`CACHE_STORE=redis`, ou seulement `"limiter": "redis"` pour les compteurs).

### Tester

Avec le store `file`, les compteurs restent sur le disque d'un lancement de tests à l'autre : le 6ᵉ login en une minute répondrait 429. Utilisez `CACHE_STORE=array` en test et videz le cache entre deux tests (voir [Cache, Tester](#tester-1)), ou remettez un compteur à zéro avec `RateLimiter.clear(key)`.

## Console

Les générateurs écrivent le fichier au bon endroit, avec un squelette prêt à l'emploi :

```bash
flask make:controller PhotoController            # app/http/controllers/photo_controller.py
flask make:controller PhotoController --resource # les 7 méthodes de Route.resource
flask make:controller Admin/UserController       # sous-dossier admin/
flask make:model Post                            # app/models/post.py
flask make:event OrderShipped                    # app/events/order_shipped.py
flask make:listener SendShipmentNotification --event OrderShipped  # app/listeners/…
flask make:mail OrderShipped                     # app/mail/order_shipped.py + son template
flask make:job ProcessPodcast                    # app/jobs/process_podcast.py
flask make:request StorePostRequest              # app/http/requests/store_post_request.py
flask make:middleware EnsureJson                 # app/http/middleware/ensure_json.py
flask make:provider PaymentServiceProvider       # app/providers/payment_service_provider.py
flask make:command SendEmails                    # app/console/commands/send_emails.py → flask app:send-emails
flask cache:clear                                # vide le cache (voir « Cache »)
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


class Payment(Facade):
    accessor = PaymentGateway  # n'importe quelle clé du conteneur


Payment.charge(...)
```

## Feuille de route v0.1 (publiée)

1. ✅ Socle : package, Application, conteneur, providers, config, façades
2. ✅ Routage et middlewares (`routes/web.py`, controllers en classes)
3. ✅ ORM façon Eloquent sur SQLAlchemy, migrations
4. ✅ Authentification (façade `Auth`, guards session et token)
5. ✅ Commandes `flask make:*`, `flask migrate`, `flask route:list`

Après la v0.1 :

- ✅ Validation (`FormRequest`, règles façon Laravel, réponses 422 JSON)
- ✅ Événements (`Event.dispatch`, écouteurs, `Event.fake()`)
- ✅ Mail (mailables, transports `smtp` / `log` / `array`, `Mail.fake()`)
- ✅ Queues (jobs sur RQ, `flask queue:work`, échecs, `Mail.queue`, écouteurs `ShouldQueue`, `Queue.fake()`)
- ✅ Cache (`Cache.get/put/remember/increment`, stores `file`, `redis`, `array`)
- ✅ Limitation de débit et verrous (`throttle`, `RateLimiter`, `Cache.lock`, `TRUSTED_PROXIES`)

## Contribuer

Voir [CONTRIBUTING.md](https://github.com/ahoblepierre/flask-artisan/blob/main/CONTRIBUTING.md).

## Licence

MIT
