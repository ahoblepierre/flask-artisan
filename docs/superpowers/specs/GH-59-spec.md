# GH-59 : kit de démarrage `flask auth:install` (inscription, mot de passe oublié, vérification de l'e-mail)

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/59

## Pourquoi

Un projet généré sait connecter et déconnecter un utilisateur (`SessionController`, `auth/login.html`, `/dashboard` derrière `auth`). Il lui manque les trois parcours que tout site avec des comptes doit écrire : l'inscription, le mot de passe oublié et la vérification de l'adresse e-mail. Laravel les livre avec Breeze. Le framework a désormais tout ce qu'il faut pour les assembler : vues, CSRF, flash des erreurs (#19), mail (#24), notifications (#51), limitation de débit (#36) et tests HTTP (#46).

## Objectifs

- **Dans le framework**, des briques réutilisables :
  - URLs signées ;
  - réinitialisation du mot de passe (jetons) ;
  - mixin `MustVerifyEmail` et middleware `verified` ;
  - deux notifications fournies, `ResetPassword` et `VerifyEmail`.
- **Une commande `flask auth:install`** (choix de Pierre, à la place d'un squelette qui les contiendrait d'office). Elle copie dans le projet le code que le développeur modifie librement : controllers, FormRequests, vues, routes et tests.
- **La connexion reste dans le squelette**, sans changement.
- **Doc :** la page « Authentification » est complétée.

## Non-objectifs

- La confirmation du mot de passe avant une action sensible (`password.confirm`), la page de profil, le changement d'e-mail, la suppression de compte.
- La double authentification.
- Une version API (JSON) de ces parcours. Seul le middleware `verified` répond aussi en JSON (voir plus bas).
- Le middleware `guest` (rediriger un utilisateur connecté hors de `/register`).
- Un `--force`, ou une modification automatique des fichiers existants.

## Anti-objectifs

- **`auth:install` ne modifie et n'écrase jamais un fichier existant** (option 1, choisie par Pierre).
  - Si l'un des fichiers à créer existe déjà, elle n'écrit **rien**. Elle liste les fichiers en conflit et sort avec le code 1.
  - Les changements à faire dans les fichiers du développeur sont seulement affichés, en fin de commande.
- **Un projet qui n'utilise ni `MustVerifyEmail` ni la réinitialisation** ne voit apparaître ni la table `password_reset_tokens` ni la colonne `email_verified_at` dans ses migrations. `Application` n'importe jamais ces modules d'elle-même, comme pour les notifications.
- **Un jeton de réinitialisation n'est jamais stocké en clair**, et on ne peut pas le réutiliser une fois le mot de passe changé.
- **Le formulaire « mot de passe oublié » ne révèle pas** si un e-mail correspond à un compte. Le message affiché est le même si le lien est envoyé, si l'e-mail est inconnu ou s'il est limité par l'anti-rafale.
- **Une URL signée modifiée** (paramètre, chemin ou expiration) **est refusée**.

## Approches envisagées

- **A. Commande `flask auth:install`** qui copie des fichiers dans le projet : retenue par Pierre. Le squelette reste léger pour un projet en API seule.
- **B. Les parcours présents d'office dans le squelette** : écartée par Pierre.
- Pour les fichiers existants, Pierre a retenu de **créer uniquement des fichiers neufs et d'afficher les ajouts à faire à la main**. Les deux autres possibilités étaient de modifier un fichier resté identique au squelette, ou d'écraser avec `--force`.
- **Briques dans le framework, code d'application dans le projet**, comme le partage entre Laravel et Breeze. Ce qui touche à la sécurité (signature, jetons, comparaison) se corrige par une mise à jour du package, pas dans chaque projet.

## Décisions

### URLs signées (`flask_artisan/signing.py`)

- `signed_url(endpoint: str, expires: int | None = None, **values) -> str`.
  - Il construit l'URL avec `url_for(endpoint, **values)`.
  - Si `expires` est donné (en secondes), il ajoute `expires=<timestamp UNIX>`.
  - Il ajoute ensuite `signature=<HMAC-SHA256 hex>`. La clé est `app.config["SECRET_KEY"]` (`APP_KEY`), et le message est le **chemin et la chaîne de requête, hors `signature`**.
  - On signe le chemin, pas l'hôte (choix du rédacteur) : un proxy qui réécrit l'hôte ou le schéma ne casse pas le lien.
  - L'URL renvoyée est relative, comme `url_for`. `_external=True` est transmis tel quel s'il est demandé. Les notifications l'utilisent pour produire une URL absolue dans le mail.
- `has_valid_signature(request) -> bool` :
  - la comparaison se fait en temps constant (`hmac.compare_digest`) ;
  - le lien est refusé si `expires` est passé ou n'est pas un entier ;
  - le message est reconstruit à partir de `request.path` et de la chaîne de requête brute, sans le paramètre `signature`, dans l'ordre reçu.
- Middleware `ValidateSignature` : 403 si la signature est invalide.
  - Alias `signed` dans le `Kernel` du squelette.
  - Les fichiers installés importent la classe directement. Ils fonctionnent donc dans un projet généré avant cette version, sans alias.
- Exportés par `flask_artisan` : `signed_url` et `ValidateSignature`.

### Réinitialisation du mot de passe (`flask_artisan/auth/passwords.py`)

Ce module est importé seulement à l'usage. Son import enregistre la table.

- Modèle `PasswordResetToken` :
  - table `password_reset_tokens` ;
  - colonnes `email` (clé primaire, texte), `token` (sha256 hex du jeton), `created_at` ;
  - pas de `updated_at` ni d'`id`. Si le `Model` maison ne le permet pas, le plan choisit l'équivalent le plus proche, avec un e-mail unique.
- Façade-objet `Password` (un module plat avec des fonctions convient aussi) :
  - `Password.send_reset_link(email: str) -> str` renvoie un statut ;
  - `Password.reset(email: str, token: str, password: str) -> str` renvoie un statut ;
  - les statuts sont des constantes chaîne : `RESET_LINK_SENT`, `RESET_THROTTLED`, `INVALID_USER`, `INVALID_TOKEN`, `PASSWORD_RESET`.
- `send_reset_link` :
  - cherche l'utilisateur par `email` dans le modèle `auth.model` ;
  - refuse avec `RESET_THROTTLED` si un jeton de moins de `auth.passwords.throttle` secondes (60 par défaut) existe pour cet e-mail ;
  - sinon, remplace le jeton de cet e-mail par un nouveau (`secrets.token_hex(32)`), stocké haché ;
  - appelle ensuite `user.send_password_reset_notification(token)`.
- `reset` :
  - vérifie l'utilisateur, puis que le jeton existe, a moins de `auth.passwords.expire` minutes (60 par défaut) et que son condensat correspond (`compare_digest`) ;
  - affecte ensuite le mot de passe (haché par `Authenticatable`), enregistre l'utilisateur et supprime le jeton ;
  - ne connecte **pas** l'utilisateur. Les autres sessions sont déjà coupées par l'empreinte du mot de passe ;
  - supprime aussi les jetons d'API de l'utilisateur si son modèle utilise `HasApiTokens`. Un jeton volé ne doit pas survivre à une réinitialisation (choix du rédacteur ; Laravel ne le fait pas d'office).
- La config `auth.passwords` est relue à chaque appel. Sans clé dans `config/auth.py` (projet existant), on prend les valeurs par défaut.
- Les e-mails sont comparés tels qu'ils sont saisis, comme `Auth.attempt` aujourd'hui (pas de mise en minuscules).

### Vérification de l'e-mail (`flask_artisan/auth/verification.py`)

- Mixin `MustVerifyEmail` :
  - il apporte `email_verified_at: Mapped[datetime | None]`, sur le modèle de `SoftDeletes` ;
  - il apporte aussi `has_verified_email() -> bool`, `mark_email_as_verified() -> None` (pose la date et enregistre) et `send_email_verification_notification() -> None` ;
  - il refuse, à la définition de la classe, d'être placé après `Model`, comme `Notifiable`.
- `email_verified_at` n'est jamais remplissable par `create()` ou `update()`, sauf si le projet l'ajoute à `fillable`.
- Middleware `EnsureEmailIsVerified` (alias `verified` du squelette). Si aucun utilisateur n'est connecté, ou si l'utilisateur utilise `MustVerifyEmail` sans avoir vérifié son e-mail :
  - il répond 403 JSON `{"message": "Your email address is not verified."}` si la route est JSON ou si la requête attend du JSON (`expects_json`, comme `Authenticate`) ;
  - sinon, il redirige vers `url_for("verification.notice")`.
  - Un utilisateur dont le modèle n'utilise pas `MustVerifyEmail` passe.
- Le lien de vérification est `signed_url("verification.verify", expires=auth.verification.expire × 60, id=user.id, hash=sha1(email))`. Il est absolu dans le mail, et `auth.verification.expire` vaut 60 minutes par défaut.
- Le hash de l'e-mail rend le lien invalide si l'adresse change.

### Notifications fournies (`flask_artisan/auth/notifications.py`)

- `ResetPassword(token)` et `VerifyEmail()` :
  - `via` renvoie `["mail"]` et `to_mail` renvoie un `Mailable`, avec un sujet en français ;
  - `ResetPassword` pointe sur `url_for("password.reset", token=…, email=…, _external=True)`, et `VerifyEmail` sur l'URL signée ci-dessus.
- Leurs templates (HTML et texte) sont livrés par le package dans `flask_artisan/resources/views/flask_artisan/emails/` :
  - `reset_password.html` / `.txt` ;
  - `verify_email.html` / `.txt`.
- `Application.__init__` ajoute ce dossier en **dernier** dans le `ChoiceLoader`. Un projet surcharge un template en créant `resources/views/flask_artisan/emails/<nom>` (choix du rédacteur, l'équivalent de `vendor:publish`).
- `send_password_reset_notification(token)` et `send_email_verification_notification()` appellent `self.notify(...)`. Un projet change le mail en surchargeant ces méthodes sur son `User`.
- Le `User` doit hériter de `Notifiable` (c'est le cas dans le squelette). Sinon, l'appel lève une erreur qui le dit.

### Chargement de `routes/auth.py`

`RouteServiceProvider.boot()` charge `routes/auth.py` après `routes/web.py`, avec le groupe `web`, **si le fichier existe**. Un projet sans ce fichier se comporte comme avant.

### `flask auth:install` (`flask_artisan/console.py`, modèles dans `flask_artisan/stubs/auth/`)

Les fichiers sont copiés tels quels (aucun gabarit à remplir) et listés dans `package-data`. Chemins créés, par rapport au projet :

| Fichier | Contenu |
|---|---|
| `routes/auth.py` | toutes les routes ci-dessous |
| `app/http/controllers/auth/__init__.py` | vide |
| `app/http/controllers/auth/registered_user_controller.py` | `create`, `store` |
| `app/http/controllers/auth/password_reset_link_controller.py` | `create`, `store` |
| `app/http/controllers/auth/new_password_controller.py` | `create`, `store` |
| `app/http/controllers/auth/email_verification_controller.py` | `notice`, `verify`, `send` |
| `app/http/requests/register_request.py` | `name` required\|string\|max:255, `email` required\|email\|max:255\|unique:users,email, `password` required\|string\|min:8\|confirmed |
| `app/http/requests/forgot_password_request.py` | `email` required\|email |
| `app/http/requests/reset_password_request.py` | `token` required, `email` required\|email, `password` required\|string\|min:8\|confirmed |
| `resources/views/auth/register.html` | |
| `resources/views/auth/forgot_password.html` | |
| `resources/views/auth/reset_password.html` | |
| `resources/views/auth/verify_email.html` | |
| `tests/test_auth_flows.py` | tests des trois parcours (`Notification.fake()`, client de test) ; les cas de vérification sont **sautés** (`pytest.skip`, avec un message qui renvoie à l'étape 1 affichée) tant que `User` n'utilise pas `MustVerifyEmail` |

Routes (groupe `web` via le provider) :

| Méthode | Chemin | Nom | Middlewares | Effet |
|---|---|---|---|---|
| GET | `/register` | `register` | | formulaire |
| POST | `/register` | | `throttle:6,1` | crée le `User`, le connecte (`Auth.login`), envoie la vérification si `MustVerifyEmail`, redirige vers `dashboard` |
| GET | `/forgot-password` | `password.request` | | formulaire |
| POST | `/forgot-password` | `password.email` | `throttle:6,1` | `Password.send_reset_link`, flash du même message pour `RESET_LINK_SENT`, `INVALID_USER` et `RESET_THROTTLED`, redirige en arrière |
| GET | `/reset-password/<token>` | `password.reset` | | formulaire (e-mail pris dans `?email=`) |
| POST | `/reset-password` | `password.store` | `throttle:6,1` | `Password.reset` ; succès : flash et redirection vers `login` ; `INVALID_TOKEN`/`INVALID_USER` : `ValidationError` sur `email` |
| GET | `/verify-email` | `verification.notice` | `auth` | page « vérifiez votre e-mail » (redirige vers `dashboard` si déjà vérifié) |
| GET | `/verify-email/<int:id>/<hash>` | `verification.verify` | `auth`, `ValidateSignature`, `throttle:6,1` | 403 si `id` ≠ utilisateur connecté ou `hash` ≠ sha1(email) ; sinon marque vérifié (une seule fois), redirige vers `dashboard` |
| POST | `/email/verification-notification` | `verification.send` | `auth`, `throttle:6,1` | renvoie le lien, flash, redirige en arrière |

Le compteur de `throttle:6,1` est partagé entre ces routes, par IP ou par utilisateur, car la clé du middleware ne contient pas la route. C'est le comportement de Laravel, qu'on garde : la doc le mentionne (choix du rédacteur).

Après la connexion, on ne revient pas sur l'URL demandée avant (`redirect()->intended()` de Laravel). Un utilisateur déconnecté qui clique le lien de vérification se connecte, puis clique le lien une seconde fois. La doc le dit, et c'est hors périmètre (choix du rédacteur).

`routes/auth.py` utilise les alias `auth` et `throttle`, présents dans le `Kernel` de tout projet généré depuis la 0.7. Il utilise `ValidateSignature` par classe, puisque l'alias `signed` n'existe que dans les nouveaux projets.

En fin de commande, elle affiche (texte exact laissé au plan) :

1. sur `User`, ajouter `MustVerifyEmail` avant `Model` et importer depuis `flask_artisan.auth` ;
2. facultatif : les alias `"verified": EnsureEmailIsVerified` et `"signed": ValidateSignature` dans `app/http/kernel.py`, puis `.middleware("verified")` sur les routes à protéger (par exemple `/dashboard`) ;
3. les liens « S'inscrire » dans `layouts/app.html` et « Mot de passe oublié ? » dans `auth/login.html` ;
4. `flask make:migration "auth install"` puis `flask migrate` ;
5. configurer `config/mail.py`, car le pilote `log` n'envoie rien.

### Squelette

- `Kernel` : les alias `verified` et `signed` sont ajoutés, pour les nouveaux projets.
- `config/auth.py` : clés `passwords` (`expire` 60, `throttle` 60) et `verification` (`expire` 60), commentées.
- Le `User` ne change pas (pas de `MustVerifyEmail` d'office, cohérent avec l'install à la demande).

## Ce qui reste au rédacteur du plan

- Le texte exact des vues (en français, sur le modèle de `auth/login.html`), des messages flash et des mails.
- Comment `MustVerifyEmail` déclare sa colonne pour que le `Model` maison la prenne (voir `SoftDeletes`).
- Le découpage des tâches. Il faut un test d'intégration qui génère un projet, lance `flask auth:install` et fait passer `tests/test_auth_flows.py` du projet en sous-processus, comme les tests existants du squelette. Il le fait deux fois : avec le `User` généré (les cas de vérification sont sautés), puis après avoir ajouté `MustVerifyEmail`.
- Les textes de la doc (`docs/authentification.md`), qui doivent passer `mkdocs build --strict`.
