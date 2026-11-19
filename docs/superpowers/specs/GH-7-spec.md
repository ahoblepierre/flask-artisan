# GH-7 — Auth : façade Auth, guards session et token, hash automatique, middleware auth

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/7
Statut : en attente d'approbation

## Intention

Un projet Flask-Artisan ne sait aujourd'hui ni connecter un utilisateur ni protéger une route. Ce chantier apporte l'authentification **façon Laravel** :

```python
Auth.attempt(email=email, password=password)   # session (routes/web.py)
Auth.user()
token = user.create_token("mobile")            # token en base, façon Sanctum (routes/api.py)
Route.get("/api/user", AuthController.user).middleware("auth:api")
```

Un développeur Laravel doit retrouver ses réflexes : `Auth::attempt`, `Auth::user`, `createToken`, `auth:sanctum`, hash automatique du mot de passe.

## Objectifs

1. Le mot de passe d'un `User` est haché tout seul, quelle que soit la façon de l'écrire (`create`, `update`, `fill`, affectation).
2. Deux guards prêts à l'emploi : `web` (session Flask signée) et `api` (token Bearer stocké en base).
3. Un token API est révocable individuellement (suppression de sa ligne).
4. Une route se protège avec `.middleware("auth")` ou `"auth:api"`, et la réponse sans utilisateur est adaptée au guard (JSON 401 ou redirection).
5. Un projet généré expose `/api/login`, `/api/logout`, `/api/user` qui marchent avec curl après `flask make:migration` + `flask migrate`.

## Non-objectifs (hors périmètre)

- « Remember me », reset de mot de passe, vérification d'email.
- Rate limiting du login.
- Abilities / scopes des tokens, expiration des tokens.
- Écrans HTML de login/register et protection CSRF des formulaires (pas de vues ni de validation avant la v0.1).
- Autorisations (Gates, Policies).
- Plusieurs modèles d'utilisateurs (un seul modèle, configuré).

## Anti-objectifs

- Stocker ou comparer un token ou un mot de passe en clair.
- Révéler par le message ou par le temps de réponse qu'un email existe.
- Ajouter une dépendance : Werkzeug (hash) et `secrets`/`hashlib` (tokens) suffisent.
- Casser Flask : la session reste la session Flask, `request` reste celui de Flask.

## Approches considérées

Pour le guard token :

- **A. Tokens en base, façon Sanctum** (retenue). Table `personal_access_tokens`, empreinte SHA-256 stockée, token en clair montré une seule fois. Révocable, convention Laravel. Coût : un modèle, une requête par appel API.
- **B. Tokens signés sans état** (itsdangerous). Rien en base, mais non révocable avant expiration.
- **C. JWT** (PyJWT). Dépendance en plus, mêmes limites que B, hors des conventions Laravel.

Pour le squelette : les briques plus un `AuthController` API (retenu), plutôt qu'un kit complet type Breeze (prématuré sans vues ni validation) ou rien du tout (pas de démo).

## Décisions

### Paquet

- Nouveau sous-paquet `src/flask_artisan/auth/`, ajouté à `packages.find include`.
- La façade `Auth` (dans `facades.py`) n'importe pas `flask_artisan.auth` : un projet sans auth n'a pas de table `personal_access_tokens` dans ses migrations.
- Exports : `from flask_artisan import Auth` (façade) ; `from flask_artisan.auth import Authenticatable, HasApiTokens, PersonalAccessToken, Authenticate, AuthManager, AuthServiceProvider, AuthenticationError`.

### Configuration `config/auth.py` (squelette)

```python
from app.models.user import User

config = {
    "defaults": {"guard": "web"},
    "guards": {
        "web": {"driver": "session"},
        "api": {"driver": "token"},
    },
    "model": User,
}
```

- Un guard inconnu (`Auth.guard("x")`, `"auth:x"`) lève `AuthenticationError` avec un message qui liste les guards configurés. Pour `"auth:x"`, l'erreur sort à la première requête sur la route (choix : éviter d'ajouter au routeur un crochet de validation des paramètres de middleware).
- Un driver inconnu lève la même erreur.
- Sans `config/auth.py`, le provider échoue avec un message clair (le modèle est indispensable).

### Hash automatique (`Authenticatable`)

- Mixin à mettre sur le modèle : `class User(Authenticatable, HasApiTokens, Model)`.
- Toute écriture de l'attribut `password` (constructeur, `fill`, `create`, `update`, `user.password = ...`) stocke `werkzeug.security.generate_password_hash(valeur)` (scrypt, défaut de Werkzeug).
- Une valeur qui est déjà un hash Werkzeug (`scrypt:…`, `pbkdf2:…`) n'est pas re-hachée. Une valeur lue depuis la base n'est pas re-hachée.
- `None` reste `None`.
- `user.check_password(plain) -> bool` via `check_password_hash`.
- Le nom de la colonne est `password` (pas configurable en v0.1).

### Tokens (`HasApiTokens`, `PersonalAccessToken`)

- `PersonalAccessToken` est un modèle du framework : table `personal_access_tokens`, colonnes `id`, `user_id` (entier indexé, **sans** clé étrangère, pour ne pas figer le nom de la table des utilisateurs), `name`, `token` (empreinte SHA-256 en hex, unique), `last_used_at` (nullable), timestamps.
- Il est dans `Model.metadata` dès que `flask_artisan.auth` est importé : `flask make:migration` le voit avec les modèles du projet. **Pas de fichier de migration livré** : la première migration générée crée `users` et `personal_access_tokens`.
- `user.create_token(name) -> str` : génère `secrets.token_urlsafe(40)`, enregistre son empreinte, renvoie le texte en clair `"<id>|<secret>"` (format Sanctum). C'est la seule fois où il est visible.
- `user.tokens()` : `Builder` des tokens de l'utilisateur (`PersonalAccessToken.where("user_id", user.id)`).
- `user.current_access_token()` : le `PersonalAccessToken` qui a authentifié la requête courante (guard token), sinon `None`.
- Révoquer : `token.delete()` (suppression définitive, pas de soft delete).
- Un token est retrouvé par `id`, puis l'empreinte du secret est comparée avec `hmac.compare_digest`. `last_used_at` est mis à jour à chaque authentification réussie par un `UPDATE` direct (pas `save()`, qui toucherait `updated_at` et validerait toute la session en pleine requête).

### Façade `Auth` et `AuthManager`

- `AuthServiceProvider` enregistre un `AuthManager` sous `"auth"` (façade `Auth`) et `AuthManager`.
- `Auth.guard(name=None)` renvoie le guard (défaut : celui de la requête courante, voir middleware, sinon `defaults.guard`).
- Méthodes relayées au guard par défaut : `user()`, `id()`, `check()`, `guest()`, `validate(**credentials)`, `attempt(**credentials)`, `login(user)`, `logout()`.
- L'utilisateur résolu est mis en cache pour la requête (dans `flask.g`), pas au-delà.

| Méthode | Guard session | Guard token |
|---|---|---|
| `user()` | lit l'id dans la session, charge l'utilisateur | lit `Authorization: Bearer <token>`, vérifie, charge l'utilisateur |
| `validate(**cred)` | renvoie l'utilisateur si les identifiants sont bons, sinon `None` ; ne connecte pas | idem |
| `attempt(**cred)` | `validate` puis `login` ; renvoie `bool` | `AuthenticationError` (sans état : utiliser `validate` + `create_token`) |
| `login(user)` | vide la session, puis y écrit l'id | `AuthenticationError` |
| `logout()` | vide la session | `AuthenticationError` (révoquer le token à la place) |

- `validate` cherche l'utilisateur par toutes les clés sauf `password` (`where` successifs), puis appelle `check_password`. Si aucun utilisateur n'est trouvé, il vérifie quand même le mot de passe contre un hash factice, pour que le temps de réponse ne dise pas si l'email existe. Sans `password` dans les identifiants : `None`.
- `validate` est un ajout par rapport à Laravel (où `validate` renvoie un booléen) : il renvoie l'utilisateur, ce qui sert au login API.
- Un utilisateur supprimé (ou soft-deleted) après le login n'est plus authentifié : `user()` renvoie `None`.

### Middleware `auth` (`Authenticate`)

- `.middleware("auth")` : guard par défaut ; `"auth:api"` : guard `api` ; `"auth:web,api"` : le premier guard qui trouve un utilisateur.
- Le guard qui a réussi devient le guard par défaut **pour la requête** (comme `shouldUse` de Laravel) : dans une route `auth:api`, `Auth.user()` renvoie l'utilisateur du token.
- Sans utilisateur, la réponse dépend du client, pas des guards (règle `expectsJson` de Laravel, y compris pour `auth:web,api`) :
  - le client attend du JSON (`request.is_json`, ou le type préféré de l'en-tête `Accept` contient `json` ; un `*/*` seul ne compte pas) : `401` JSON `{"message": "Unauthenticated."}` ;
  - sinon, si une route nommée `login` existe : redirection vers elle ;
  - sinon : `401` JSON.
- Le kernel du squelette déclare `middleware = {"auth": Authenticate}`.

### Squelette

- `app/models/user.py` : `class User(Authenticatable, HasApiTokens, Model)` ; `fillable`, `hidden` inchangés.
- `config/auth.py` (ci-dessus).
- `config/app.py` : `AuthServiceProvider` après `DatabaseServiceProvider`.
- `app/http/kernel.py` : alias `auth`.
- `app/http/controllers/auth_controller.py` et `routes/api.py` :
  - `POST /api/login` (JSON `email`, `password`) → `200 {"token": "..."}` ou `401 {"message": "Invalid credentials."}` (même message que l'email existe ou non, même réponse si des champs manquent) ;
  - `POST /api/logout` (`auth:api`) → supprime le token courant, `204` ;
  - `GET /api/user` (`auth:api`) → l'utilisateur en JSON (sans `password`, grâce à `hidden`).
- Le token est nommé d'après le champ `device_name` s'il est fourni, sinon `"api"`.

## Pièges connus

- **`APP_KEY` vide.** Les sessions Flask exigent `SECRET_KEY`. Le squelette génère déjà `APP_KEY` ; si elle est vide, Flask lève son erreur habituelle au premier `login`. On ne la masque pas.
- **Session cookie signée, pas chiffrée.** On n'y met que l'id de l'utilisateur.
- **Fixation de session.** La session Flask par cookie n'a pas d'identifiant à régénérer : `login` vide la session avant d'écrire, ce qui en tient lieu.
- **Hash factice.** Il doit être calculé une fois (au chargement du module ou paresseusement), pas à chaque appel.

## Laissé au constructeur

- Découpage en modules sous `src/flask_artisan/auth/`.
- Mécanique du hash automatique (événement d'attribut SQLAlchemy `set`, `@validates`, ou `__setattr__`), du moment que la lecture depuis la base ne re-hache pas.
- Forme interne des guards (classes `SessionGuard`, `TokenGuard` ou autre) et clé de session utilisée.
- Comment `user_id` du token est relié au modèle configuré (simple requête `model.find`).

## Livraison

- Tests pytest : hash (toutes les voies d'écriture, pas de double hash), tokens (création, empreinte stockée, vérification, révocation, token malformé), guards, `attempt`/`validate` (email inconnu, mauvais mot de passe, champs manquants), middleware (`auth`, `auth:api`, plusieurs guards, redirection `login`, JSON 401, guard inconnu au boot), `Auth.user()` dans une route `auth:api`.
- Test de bout en bout du projet généré : migration crée `personal_access_tokens`, puis login API → token → `/api/user` → logout → token refusé.
- README (section auth) et CLAUDE.md mis à jour.
- PR `feat/7-auth`, titre avec `(#7)`, corps avec `Closes #7`. CI verte sur 3.10 à 3.13.
