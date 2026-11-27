# Tests HTTP

`app.test_client()` renvoie le client de test du framework. C'est toujours le client de Flask : tout ce qui marchait (`response.status_code`, `response.get_json()`, `session_transaction()`) marche encore. Ses réponses ont en plus des assertions qui s'enchaînent, et `acting_as` authentifie un utilisateur en une ligne.

```python
def test_profile(client, user):
    client.acting_as(user, "api").get("/api/user").assert_ok().assert_json({"email": user.email})


def test_login_requires_email(client):
    client.post("/api/login", json={}).assert_status(422).assert_json_validation_errors(["email"])
```

## Assertions

Chaque assertion renvoie la réponse, ce qui permet de les enchaîner. En cas d'échec, elle lève une `AssertionError` qui montre l'attendu, la valeur reçue et le début du corps de la réponse.

| Méthode | Vérifie |
|---------|---------|
| `assert_status(code)` | le statut est `code` |
| `assert_ok()` | le statut est 200 |
| `assert_json(data)` | le corps est du JSON qui **contient** `data` : chaque clé d'un dict est présente, avec une valeur qui correspond (récursivement pour les dicts imbriqués) ; les autres valeurs, listes comprises, doivent être égales |
| `assert_json_path("user.email", value)` | la valeur au chemin pointé est égale à `value` ; un segment entier indexe une liste (`"items.0.id"`) |
| `assert_json_validation_errors(["email"])` | le statut est 422 et chaque champ a une erreur de [validation](validation.md) |
| `assert_header(name, value=None)` | l'en-tête est présent et, si `value` est donné, a cette valeur |
| `assert_redirect(location=None)` | le statut est une redirection (301, 302, 303, 307, 308) et, si `location` est donné, l'en-tête `Location` vaut `location` (tel que la vue l'a produit, `/login` par exemple) |

Pour comparer tout le JSON, utilisez `assert response.json == {...}`.

## `acting_as`

```python
client.acting_as(user)          # guard par défaut (web, session)
client.acting_as(user, "api")   # guard token, pour les routes en auth:api
```

`acting_as` passe par la vraie [authentification](authentification.md) :

- avec un guard session, l'utilisateur est écrit dans la session du client, comme le ferait `Auth.login(user)` ;
- avec un guard token, un vrai token nommé `"test"` est créé en base et envoyé dans l'en-tête `Authorization: Bearer …`. `Auth.user().current_access_token()` fonctionne donc comme en production (un `logout` qui supprime le token, par exemple).

Comme dans Laravel, sans guard, c'est le guard par défaut (`web` dans le squelette) : `client.acting_as(user).get("/api/user")` renvoie 401. Pour l'API, précisez `"api"`.

L'utilisateur reste authentifié pour toutes les requêtes suivantes de ce client. Un nouvel appel à `acting_as` le remplace. Pour redevenir invité, prenez un nouveau client avec `app.test_client()`.

Un guard inconnu lève `AuthenticationError`.

## Les tests du squelette

Le projet généré contient `tests/conftest.py`. Avant d'importer l'app, il force :

- une base SQLite **en mémoire** (`DB_CONNECTION=sqlite`, `DB_DATABASE=:memory:`), dont les tables sont créées avant chaque test et supprimées après, sans toucher à `database/database.sqlite` ;
- le store de cache `array`, pour que les compteurs du throttle de `/api/login` ne restent pas d'un lancement à l'autre.

La fixture `client` renvoie `app.test_client()`. Pour l'utiliser dans vos tests :

```python
from app.models.user import User
from wsgi import app


def test_user_endpoint(client):
    with app.app_context():
        user = User.create(name="Ada", email="ada@example.org", password="secret")
    client.acting_as(user, "api").get("/api/user").assert_ok()
```

```bash
pytest
```
