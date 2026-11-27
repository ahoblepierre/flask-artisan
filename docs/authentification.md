# Authentification

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

Deux guards sont déclarés dans `config/auth.py` : `web` (session Flask) et `api` (token Bearer en base). Le squelette contient une page de connexion pour le guard `web` (`/login`, `/logout`, `/dashboard`) : voir [Vues et formulaires](vues.md#la-page-de-connexion-du-squelette).

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

## Kit de démarrage : `flask auth:install`

La commande ajoute au projet l'inscription, le mot de passe oublié et la vérification de l'e-mail, comme Breeze pour Laravel. Le code installé appartient au projet : modifiez-le librement.

```bash
flask auth:install
```

Elle crée `routes/auth.py`, quatre controllers dans `app/http/controllers/auth/`, trois FormRequests, quatre vues dans `resources/views/auth/` et `tests/test_auth_flows.py`. Elle ne modifie et n'écrase jamais un fichier : si l'un d'eux existe déjà, elle n'écrit rien, liste les fichiers en conflit et sort avec le code 1.

Il reste six étapes à faire à la main, rappelées en fin de commande :

1. Ajouter `MustVerifyEmail` au `User`, **avant** `Model` : `class User(MustVerifyEmail, Authenticatable, HasApiTokens, Notifiable, Model)`, importé depuis `flask_artisan.auth`. Tant que ce n'est pas fait, les tests de vérification de `tests/test_auth_flows.py` sont sautés.
2. Facultatif : ajouter les alias `"verified": EnsureEmailIsVerified` et `"signed": ValidateSignature` dans `app/http/kernel.py`. Un projet généré depuis la 0.10 les a déjà.
3. Ajouter les liens « S'inscrire » (`url_for('register')`) dans `layouts/app.html` et « Mot de passe oublié ? » (`url_for('password.request')`) dans `auth/login.html`.
4. Lancer `flask make:migration "auth install"` puis `flask migrate`, pour créer la table `password_reset_tokens` et la colonne `email_verified_at`.
5. Configurer un vrai transport dans `config/mail.py` : le pilote `log` n'envoie rien.
6. Renseigner `APP_URL` dans `.env` (par exemple `https://exemple.fr`). Un projet généré avant la 0.10 doit aussi ajouter `"url": env("APP_URL")` à `config/app.py`.

`routes/auth.py` est chargé automatiquement dans le groupe `web` (CSRF), après `routes/web.py` :

| Méthode | Chemin | Nom |
|---|---|---|
| GET, POST | `/register` | `register` |
| GET, POST | `/forgot-password` | `password.request`, `password.email` |
| GET | `/reset-password/<token>` | `password.reset` |
| POST | `/reset-password` | `password.store` |
| GET | `/verify-email` | `verification.notice` |
| GET | `/verify-email/<id>/<hash>` | `verification.verify` (lien signé) |
| POST | `/email/verification-notification` | `verification.send` |

Les routes en POST et le lien de vérification sont limités par `throttle:6,1`. Ce compteur est **partagé** entre ces routes, par IP, ou par utilisateur s'il est connecté, comme dans Laravel. Après la connexion, l'utilisateur arrive sur `/dashboard`, pas sur la page qu'il demandait : s'il ouvre le lien de vérification sans être connecté, il devra l'ouvrir à nouveau une fois connecté.

### Mot de passe oublié

```python
from flask_artisan.auth.passwords import Password

Password.send_reset_link(email)              # Password.RESET_LINK_SENT, INVALID_USER ou RESET_THROTTLED
Password.reset(email, token, new_password)   # Password.PASSWORD_RESET, INVALID_TOKEN ou INVALID_USER
```

Le jeton est envoyé par e-mail et seule son empreinte SHA-256 est stockée, une ligne par adresse. Il est valable 60 minutes, et on ne peut en redemander un qu'après 60 secondes. Ces durées se règlent dans `config/auth.py`, avec `"passwords": {"expire": 60, "throttle": 60}`. Le formulaire affiche le même message que l'adresse ait un compte ou non.

Une réinitialisation réussie supprime le jeton, ferme les sessions ouvertes et **révoque les tokens d'API** de l'utilisateur. Elle ne connecte pas l'utilisateur : il est renvoyé vers `/login`.

### Vérification de l'e-mail

`MustVerifyEmail` ajoute `email_verified_at` et les méthodes `has_verified_email()`, `mark_email_as_verified()` et `send_email_verification_notification()`. Le middleware `verified` laisse passer un utilisateur vérifié, ou dont le modèle n'utilise pas `MustVerifyEmail`. Sinon, il redirige vers `verification.notice`, ou répond 403 JSON sur l'API.

```python
with Route.middleware("auth", "verified"):
    Route.get("/dashboard", DashboardController.index).name("dashboard")
```

Le lien envoyé est signé et expire après 60 minutes (`"verification": {"expire": 60}` dans `config/auth.py`). Il contient l'empreinte de l'adresse e-mail : il ne vaut plus rien si l'adresse change.

### Personnaliser les mails

Les deux mails, `ResetPassword` et `VerifyEmail` (`flask_artisan.auth.notifications`), passent par le canal mail des [notifications](notifications.md) : le `User` doit hériter de `Notifiable`, comme celui du squelette. Pour changer leur texte, créez dans le projet `resources/views/flask_artisan/emails/reset_password.html` (et `.txt`), ou `verify_email.html` (et `.txt`). Ces fichiers ont accès aux variables `url` et `expire`. Pour envoyer un tout autre mail, redéfinissez `send_password_reset_notification(token)` ou `send_email_verification_notification()` sur le `User`.

Les liens des mails sont absolus et commencent par `APP_URL` (`config("app.url")`), jamais par l'hôte de la requête : sinon, un attaquant qui enverrait la demande avec un en-tête `Host` à lui ferait partir le jeton de la victime vers son propre site. Sans `APP_URL`, l'envoi lève une erreur.

### URLs signées

```python
from flask_artisan import signed_url

url = signed_url("invoices.download", expires=3600, id=invoice.id)   # valable une heure
Route.get("/invoices/<int:id>/download", download).name("invoices.download").middleware("signed")
```

La signature (HMAC-SHA256 avec `APP_KEY`) couvre le chemin et les paramètres. Toute modification, ou un lien expiré, donne un 403. `_external=True` produit une URL absolue.
