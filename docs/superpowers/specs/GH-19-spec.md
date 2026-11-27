# GH-19 : vues HTML (validation avec redirection, `old()`, CSRF, flash)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/19

## Pourquoi

Flask-Artisan ne sert aujourd'hui que des API JSON. Un formulaire HTML invalide reçoit un 422 JSON brut, il n'y a aucune protection CSRF, et le guard session n'a aucune page de connexion. Le middleware `auth` sait pourtant déjà rediriger vers une route `login`. Laravel rend tout ça naturel : la redirection vers la page précédente, `$errors`, `old()`, `@csrf` et `session('status')`. Ce chantier ouvre les sites rendus côté serveur.

## Objectifs (approche A, choisie par Pierre)

- **Échec de validation sur une requête HTML :**
  - redirection vers la page précédente ;
  - les erreurs et les saisies sont gardées en session pour une seule requête ;
  - une requête qui attend du JSON garde le 422 JSON d'aujourd'hui.
- **Dans les templates Jinja :** `errors`, `old()`, `csrf_token()` et `csrf_field()`. Les messages flash restent ceux de Flask (`flash`, `get_flashed_messages`).
- **Middleware CSRF `VerifyCsrfToken`**, placé dans le groupe `web` du squelette.
- **Squelette :**
  - un layout et une page `/login` (formulaire, guard session, `POST /logout`) ;
  - une page `/dashboard` protégée par `auth` ;
  - des tests qui couvrent le parcours.
- **Doc :** une page « Vues et formulaires », et les pages Validation et Authentification mises à jour.

## Non-objectifs

- Inscription, mot de passe oublié et profil (un kit de démarrage à la Breeze, option C, qui fera un chantier à part).
- Le middleware `guest` (rediriger un utilisateur connecté qui ouvre `/login`) et la redirection vers la page demandée avant la connexion (`intended`).
- L'usurpation de méthode (`_method=DELETE` dans un formulaire) et les pages d'erreur HTML personnalisées (404, 500).
- `old()` pour les champs à valeurs multiples : la première valeur seulement.
- Des assertions de session dans le client de test (`assert_session_has_errors`).
- Les composants à la Blade : l'héritage de Jinja (`{% extends %}`, `{% block %}`, `{% include %}`) sert de layout.

## Anti-objectifs

- Une API (requête qui attend du JSON, ou routes de `routes/api.py`) ne doit voir aucun changement :
  - toujours le 422 JSON ;
  - aucun CSRF ;
  - aucune écriture de session.
- La redirection après une erreur ne doit jamais sortir du site (redirection ouverte) : un `Referer` d'un autre hôte est ignoré.
- Les mots de passe ne sont jamais gardés en session par `old()`.
- Un projet sans auth ne doit pas importer `flask_artisan.auth`, qui déclare la table des tokens. Le routage ne doit donc pas importer ce sous-paquet.

## Approches envisagées

- **A. Le mécanisme, plus une page de connexion** : retenue par Pierre.
- **B. Le mécanisme seul** : écartée, car la redirection de `auth` vers `login` resterait sans cible.
- **C. Un kit complet** : écartée pour ce chantier.
- **CSRF écrit par nous, sans dépendance** (choix du rédacteur). Flask-WTF apporterait WTForms pour une comparaison de jetons d'environ trente lignes, avec ses propres noms (`csrf_token`, `X-CSRFToken`). Nous gardons les noms de Laravel (`_token`, `X-CSRF-TOKEN`, statut 419). Un projet reste libre d'ajouter Flask-WTF à la place.

## Décisions

### Requête qui attend du JSON

- `expects_json(request)` passe de `auth/middleware.py` à `middleware.py` (choix du rédacteur), et `auth/middleware.py` le réimporte.
- La règle ne change pas : `request.is_json`, ou un type préféré qui contient `json`.

### Routes d'API : toujours en JSON (choix A de Pierre, à la suite de la relecture)

- Une route déclarée dans `routes/api.py` répond toujours en JSON (422 et 403), quoi que demande la requête. Un `curl -d email=… /api/login` sans `Accept: application/json` reçoit donc le 422 JSON d'aujourd'hui, sans redirection ni cookie.
- **Mécanisme :**
  - `Router.load(path, prefix="", middleware=(), json=False)` ouvre un groupe qui porte `json` ;
  - `PendingRoute.json` vaut vrai si l'un des groupes englobants le porte ;
  - `RouteServiceProvider.boot` passe `json=True` pour `routes/api.py`. Cela ne dépend pas de la présence du groupe `api` dans le kernel.
- **Pour les autres routes**, `expects_json(request)` décide.
- **Rejeté :** l'option B, `expects_json` seul comme dans Laravel par défaut, avec laquelle un client d'API sans en-tête `Accept` serait redirigé.

### Validation sur une requête HTML

Dans `Router._view`, à l'endroit où `ValidationError` est déjà interceptée :

- **Si la route est `json` ou si `expects_json(request)`**, `exc.get_response()` est appelé comme aujourd'hui.
- **Sinon :**
  - **Session.** Elle reçoit `session["_flash_errors"] = exc.errors` et `session["_flash_old"]`. Les saisies sont reprises comme dans `FormRequest.__init__` (`request.args` puis `request.form`, une valeur par clé), sans `password`, `password_confirmation` ni `current_password` (la liste `DONT_FLASH` de Laravel), et sans `_token`.
  - **Taille du cookie.** Une saisie de plus de 1 000 caractères n'est pas flashée (choix du rédacteur, à la suite de la relecture). La session Flask est un cookie limité à environ 4 Ko : un `textarea` long le ferait ignorer par le navigateur, et l'utilisateur perdrait sa connexion en même temps que ses saisies. `old()` rend alors la valeur par défaut. Les erreurs sont toujours flashées.
  - **Redirection.** C'est une redirection 302 vers `request.referrer` si son schéma et son hôte sont ceux de la requête (`request.host_url`), sinon vers `/`.
- **Pour `AuthorizationError`**, selon la même règle, une requête HTML reçoit le 403 HTML de Werkzeug (`Forbidden().get_response()`), et une requête qui attend du JSON garde son 403 JSON (choix du rédacteur).

### Données flashées : une seule requête

- `Application.__init__` enregistre un `before_request`. Il déplace `_flash_errors` et `_flash_old` de la session vers `request.environ["flask_artisan.flash"]`, et les retire de la session. Il ne touche pas à la session si ces clés n'y sont pas (aucun cookie posé pour une API).
- Le choix de `request.environ` et non de `g` suit la même raison que l'auth : `g` est partagé par les requêtes d'un même app context englobant.

### Fonctions des templates

Elles sont enregistrées par `Application.__init__` dans un `context_processor`, ou comme globales Jinja. Elles vivent dans le module `flask_artisan/views.py`.

| Nom | Comportement |
|-----|--------------|
| `errors` | un `ErrorBag` : `errors.has("email")`, `errors.first("email")` (sinon `""`), `errors.get("email")` (une liste), `errors.all()` (tous les messages), `errors.any()`, et `bool(errors)` |
| `old("email", default="")` | la saisie flashée, sinon `default` |
| `csrf_token()` | le jeton de la session (`session["_token"]`), créé à la demande avec `secrets.token_urlsafe(32)` |
| `csrf_field()` | `Markup('<input type="hidden" name="_token" value="…">')`, avec la valeur échappée |

`ErrorBag` et `old` sont aussi importables depuis `flask_artisan.views`, pour les tests et le code Python.

### `VerifyCsrfToken`

- C'est un middleware de `flask_artisan/csrf.py`, exporté par `flask_artisan`.
- Les méthodes `GET`, `HEAD` et `OPTIONS` passent sans contrôle.
- Pour les autres méthodes, le jeton est lu dans le formulaire (`_token`), sinon dans l'en-tête `X-CSRF-TOKEN`. Il est comparé à `session["_token"]` avec `hmac.compare_digest`. Un jeton absent d'un côté ou de l'autre est un échec.
- **En cas d'échec :** statut 419.
  - Une requête qui attend du JSON reçoit `{"message": "CSRF token mismatch."}`.
  - Les autres reçoivent une page HTML courte, « Page expirée ».
- **Pendant les tests :** le contrôle est sauté quand `current_app.testing` est vrai (choix du rédacteur, comme Laravel le fait pendant les tests unitaires). La conftest du squelette passe `app.testing = True`. Les tests du framework vérifient le middleware avec `testing` à faux.
- **À la connexion et à la déconnexion :** `SessionGuard.login` et `logout` vident déjà la session, donc le jeton est régénéré à la demande suivante, comme `regenerateToken` de Laravel. Rien ne change dans `auth/`.

### Squelette

- **`config/flask.py`** : `"SESSION_COOKIE_SAMESITE": "Lax"`, avec une ligne de commentaire (défense en profondeur avec le CSRF).
- **Kernel** : `groups["web"] = [VerifyCsrfToken]`.
- **`resources/views/layouts/app.html`** : la structure HTML, les messages flash et un bloc `content`, avec un style minimal en ligne.
- **`resources/views/auth/login.html`** :
  - un formulaire `POST /login` avec `csrf_field()` ;
  - l'email pré-rempli par `old("email")` ;
  - les erreurs de chaque champ.
- **`resources/views/dashboard.html`** : il affiche l'utilisateur et un formulaire `POST /logout` avec `csrf_field()`.
- **`app/http/controllers/session_controller.py`** (`SessionController`) :
  - `create` affiche `auth/login.html` ;
  - `store(request: LoginRequest)` appelle `Auth.attempt(email=…, password=…)`, puis redirige vers `dashboard` et flashe « Connecté. » ; si l'attempt échoue, il lève `ValidationError({"email": ["Ces identifiants ne correspondent à aucun compte."]})` ;
  - `destroy` appelle `Auth.logout()` et redirige vers `/`.
- **`app/http/controllers/dashboard_controller.py`** affiche `dashboard.html`.
- **`routes/web.py`** :
  - `GET /login` (nom `login`) ;
  - `POST /login` avec `throttle:5,1` ;
  - `POST /logout` (nom `logout`, avec `auth`) ;
  - `GET /dashboard` (nom `dashboard`, avec `auth`).
- **Throttle partagé.** `POST /login` et `POST /api/login` partagent le compteur `throttle:5,1` d'une même IP, car la clé du middleware ne contient pas la route. C'est le comportement existant de `throttle` (choix du rédacteur, à la suite de la relecture) : 5 essais par minute en tout, ce qui va dans le sens de la protection contre le test de mots de passe en boucle.
- **`Referer` dans les tests.** Le client de test de Werkzeug n'envoie pas de `Referer`. Les tests de la redirection en arrière le passent eux-mêmes (`headers={"Referer": …}`).
- `LoginRequest` est réutilisé tel quel (`device_name` est en `sometimes`).
- **`tests/test_web_auth.py`** :
  - `/dashboard` d'un invité redirige vers `/login` ;
  - une connexion avec un mauvais mot de passe redirige en arrière, et la page affiche l'erreur et l'email saisi ;
  - une bonne connexion mène au tableau de bord ;
  - la déconnexion fonctionne.

### Doc

- **Nouvelle page `docs/vues.md`, « Vues et formulaires »**, ajoutée au nav en tête de la section HTTP, après Routage. Elle couvre :
  - les templates dans `resources/views/` et le layout ;
  - les erreurs et `old()` ;
  - le CSRF ;
  - les messages flash ;
  - le comportement JSON ou redirection.
- `validation.md` reçoit une ligne qui renvoie vers cette page.
- `authentification.md` présente la page de connexion du squelette.
- Mises à jour aussi : le README (une ligne), CLAUDE.md (une puce) et le CHANGELOG.

## Laissé au constructeur

- Le HTML et le CSS exacts du squelette.
- Le texte de la page 419.
- L'emplacement exact de l'enregistrement du `before_request` et du `context_processor` dans `Application`, tant que le test qui interdit de masquer un attribut de Flask reste vert.
