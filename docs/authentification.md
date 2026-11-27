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
