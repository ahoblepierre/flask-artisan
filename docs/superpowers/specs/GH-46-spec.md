# GH-46 : assertions de test HTTP et `acting_as`

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/46

## Pourquoi

Aujourd'hui, les tests d'un projet utilisent le client de test brut de Flask. On lit `response.status_code` et `response.get_json()` à la main. Pour s'authentifier, on crée un token et on construit l'en-tête `Authorization`. Laravel enchaîne les assertions sur la réponse (`assertOk()->assertJson(...)`) et authentifie en une ligne (`actingAs($user)`). Toutes les fonctions livrées jusqu'ici (routage, validation, auth, limitation de débit) se testeraient plus vite et plus lisiblement de cette façon.

## Objectifs

```python
def test_profile(client, user):
    client.acting_as(user, "api").get("/api/user").assert_ok().assert_json({"id": user.id})
    client.post("/api/login", json={}).assert_status(422).assert_json_validation_errors(["email"])
```

- `app.test_client()` renvoie un client du framework. Ses réponses portent des assertions chaînables, et chacune renvoie la réponse.
- `client.acting_as(user, guard=None)` authentifie les requêtes suivantes de ce client, en passant par le vrai guard.
- Les tests du squelette montrent un exemple, et une page de doc « Tests HTTP » est ajoutée.

## Non-objectifs

- Assertions sur les vues HTML (`assert_see`, `assert_view_is`), qui relèvent de #19.
- Assertions sur la base (`assert_database_has`), les fakes HTTP sortants et `assert_exact_json` : pour comparer tout le JSON, on écrit `assert response.json == {...}`.
- Les raccourcis de statut au-delà de `assert_ok` (`assert_created`, `assert_not_found`…) : `assert_status(201)` suffit.
- Les fixtures pytest fournies par le framework : le squelette montre les siennes.

## Anti-objectifs

- Aucun test existant, que ce soit dans le repo ou dans un projet généré, ne doit changer de comportement. Le client reste un `FlaskClient` et la réponse reste une `TestResponse` de Werkzeug : on ajoute des méthodes, sans en modifier aucune.
- `acting_as` ne doit pas court-circuiter l'auth. Il doit passer par le middleware `auth` et par le guard. Sinon, `Auth.user().current_access_token()` renverrait `None`, et le `logout` du squelette planterait.
- Aucun code de test ne doit entrer dans le chemin des requêtes de production : `auth/` ne change pas.

## Approches envisagées

- **A. Comme Laravel, avec le guard par défaut** : retenue par Pierre. `acting_as(user)` utilise le guard par défaut (`web` dans le squelette), et `acting_as(user, "api")` vise le guard token.
- **B. Tous les guards configurés** : écartée. Chaque appel créerait un token en base, même pour un test web, et le comportement serait implicite.
- **Utilisateur injecté dans `request.environ` sans vrai token** : écartée. `current_access_token()` renverrait `None`, et il faudrait un faux token dans `auth/`.
- **Accrocher le client par `test_client_class`, réglé sur l'instance dans `Application.__init__`** (choix du rédacteur) : c'est la même technique que pour `jinja_loader`, ce qui ne masque aucun attribut de la classe `Flask`. L'option de faire porter les assertions par `app.response_class` a été écartée, car elle les ajouterait aux réponses de production.

## Décisions

### Module `flask_artisan/testing.py`

- `TestResponse(werkzeug.test.TestResponse)` porte les assertions.
- `TestClient(flask.testing.FlaskClient)` :
  - il passe à `super().__init__` une classe `(TestResponse, app.response_class)`, en reprenant ce que Werkzeug fait déjà avec `(werkzeug TestResponse, app.response_class)` (choix du rédacteur, à la suite de la relecture). La réponse reste une instance de `app.response_class` : elle garde le module JSON de Flask, `max_cookie_size` et les méthodes d'une `response_class` propre au projet. Un test le vérifie ;
  - il porte `acting_as`.
- `Application.__init__` fixe `self.test_client_class = TestClient`.
- Les deux classes sont exportées par `flask_artisan.testing`, mais pas par `flask_artisan`.

### Assertions

Chaque assertion renvoie `self`. En cas d'échec, elle lève une `AssertionError` dont le message montre l'attendu, la valeur reçue et un extrait du corps (500 caractères au plus). Pytest affiche ce message tel quel.

| Méthode | Vérifie |
|---------|---------|
| `assert_status(code)` | `status_code == code` |
| `assert_ok()` | `assert_status(200)` |
| `assert_json(data)` | Le corps est du JSON (sinon échec « pas du JSON ») et contient `data`. Pour un dict, chaque clé de `data` est présente, avec une valeur qui correspond récursivement (même règle). Les autres valeurs, listes comprises, doivent être égales. C'est le sous-ensemble de `assertJson` de Laravel. |
| `assert_json_path(path, value)` | `path` est un chemin pointé (`"user.email"`, `"items.0.id"`) ; un segment entier indexe une liste. Un chemin absent fait échouer l'assertion en nommant le segment manquant. La valeur trouvée doit être égale à `value`. |
| `assert_json_validation_errors(fields)` | Le statut est 422 et chaque champ de `fields` (une liste ou une chaîne) est une clé de `json["errors"]`, le format de `ValidationError`. |
| `assert_header(name, value=None)` | L'en-tête est présent ; si `value` est fourni, la valeur est égale. |
| `assert_redirect(location=None)` | Le statut est 301, 302, 303, 307 ou 308 ; si `location` est fourni, l'en-tête `Location` est égal à `location`. Werkzeug garde le `Location` tel que la vue l'a produit (`/login`, par exemple). |

### `acting_as(user, guard=None)`

- Il résout le guard par `app.make(AuthManager).guard(guard)`. Le guard par défaut de la config est utilisé si `guard` vaut `None`. Un guard inconnu lève l'`AuthenticationError` existante.
- **`SessionGuard`** : dans `session_transaction()`, il écrit `SESSION_KEY = user.id` et `SESSION_HASH_KEY = _fingerprint(user)`, les mêmes clés que `SessionGuard.login`, importées de `auth/manager.py`.
- **`TokenGuard`** : il crée un vrai token avec `user.create_token("test")` et fixe `self.environ_base["HTTP_AUTHORIZATION"] = "Bearer <token>"`.
- Il renvoie le client, ce qui permet d'enchaîner (`client.acting_as(user).get(...)`).
- L'effet dure pour toutes les requêtes suivantes de ce client. Un nouvel appel à `acting_as` remplace l'utilisateur (la session est réécrite, ou l'en-tête est remplacé). Pour redevenir invité, on prend un nouveau client.
- Le guard session a besoin d'une `SECRET_KEY`, comme l'app elle-même. La création d'un token a besoin de la base, comme `create_token` partout ailleurs.

### Squelette et doc

- Les tests du squelette ajoutent `tests/conftest.py` (fixture `client`) et un test qui crée un utilisateur, puis vérifie `GET /api/user` avec `acting_as(user, "api")` et `POST /api/login` en 422 avec `assert_json_validation_errors`.
- Le conftest du squelette force le store de cache `array` (choix du rédacteur, à la suite de la relecture). Sans ça, le `throttle:5,1` de `/api/login`, avec le store `file` partagé entre les exécutions, renverrait 429 au lieu de 422 dès qu'on lance les tests plus de cinq fois par minute.
- Ils réutilisent la base du projet généré (SQLite). La façon de préparer la base dans les tests (migrations, ou `create_all` sur une base en mémoire) est laissée au plan, selon ce que le squelette permet déjà.
- La page `docs/tests-http.md` est ajoutée au nav, en fin de section HTTP. Le README ajoute une ligne et CLAUDE.md une puce d'architecture. Le CHANGELOG reçoit une entrée sous `[Non publié]`.

## Laissé au constructeur

- Le texte exact des messages d'échec.
- La structure interne de la comparaison récursive.
- La préparation de la base dans les tests du squelette, voir plus haut.
