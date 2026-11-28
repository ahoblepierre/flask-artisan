# Changelog

Toutes les évolutions notables de Flask-Artisan. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Sécurité

- URLs signées : un lien dont la requête était déplacée dans le chemin (`%3F`) restait valide après expiration ; il est désormais refusé, et `signed_url` refuse une valeur de route contenant `?` (#63). Les liens déjà envoyés restent valides, sauf ceux dont une valeur de route contenait `?` : ils répondent désormais 403.
- Le champ `token` (jeton de réinitialisation du mot de passe) n'est plus recopié dans le cookie de session après un échec de validation (#65).

## [0.10.0] - 2026-11-27

### Ajouté

- `flask auth:install` : inscription, mot de passe oublié et vérification de l'e-mail copiés dans le projet (routes, controllers, FormRequests, vues, tests). Ne modifie jamais un fichier existant (#59).
- `Password.send_reset_link` / `Password.reset` (`flask_artisan.auth.passwords`, table `password_reset_tokens`) ; une réinitialisation révoque aussi les tokens d'API (#59).
- Mixin `MustVerifyEmail` (colonne `email_verified_at`) et middleware `verified` (`EnsureEmailIsVerified`) (#59).
- URLs signées : `signed_url(...)` et middleware `signed` (`ValidateSignature`) (#59).
- Notifications `ResetPassword` et `VerifyEmail`, aux templates surchargeables dans `resources/views/flask_artisan/emails/` (#59).
- `RouteServiceProvider` charge `routes/auth.py` dans le groupe `web` s'il existe (#59).
- Squelette : `APP_URL` (`config("app.url")`), base des liens envoyés par e-mail, jamais l'en-tête `Host` (#59).

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.10,<0.11`.
- `RouteServiceProvider` charge désormais `routes/auth.py` s'il existe : un projet qui chargeait déjà ce fichier lui-même (depuis `routes/web.py` ou son propre provider) doit retirer ce chargement, sinon ses routes sont déclarées deux fois (#59).

## [0.9.0] - 2026-11-27

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.9,<0.10`.
- Validation : `integer` et `numeric` n'acceptent plus que des chiffres ASCII, sans espaces ni `_` (`" 12 "`, `"1_000"`, `"١٢٣"`, `".5"` sont refusés) (#53).
- Toute app déclare la route `GET /storage/<chemin>` (`storage.public`) du disque public, sauf avec `"serve": False` dans `config/filesystems.py`. Elle est ajoutée après les routes des providers : une route `/storage/...` déjà déclarée par le projet garde la priorité (#49).
- Un échec de validation sur une requête HTML hors API (formulaire, sans en-tête `Accept` JSON) redirige en arrière au lieu de renvoyer le 422 JSON ; envoyez `Accept: application/json` ou déclarez la route dans `routes/api.py` pour garder le JSON (#19).
- `expects_json` reconnaît aussi `X-Requested-With: XMLHttpRequest` ; le middleware `auth` répond 401 JSON sur une route de `routes/api.py` au lieu de rediriger vers `login` (#19).
- Une `AuthorizationError` (403) sur une requête HTML hors API rend la page 403 HTML au lieu du JSON (#19).

### Corrigé

- Une règle `regex` au motif invalide lève `ValueError` à la construction du `Validator`, au lieu d'une erreur 500 à la première valeur (#53).
- Un paramètre de controller annoté par une `FormRequest` avec une valeur par défaut est refusé à l'enregistrement de la route (`RouteError`) : la validation était sautée en silence (#53).

### Ajouté

- **Notifications** : classe `Notification` (`via`, `to_mail` qui renvoie un Mailable, `to_database`), mixin `Notifiable` (`notify`, `notifications`, `unread_notifications`, destinataire polymorphe), table `notifications` (UUID, `mark_as_read`), `Notification.send(...)` et `Notification.route("mail", …)` à la demande, mise en file avec `ShouldQueue` (un job par canal et par destinataire), `Notification.fake()` et ses assertions, `flask make:notification` ; le `User` du squelette hérite de `Notifiable` (#51).
- **Stockage de fichiers** : façade `Storage` (`put`, `get`, `exists`, `delete`, `files`, `url`, `put_file`, `download`…), disques `local` et `s3` (extra `[s3]`, compatible MinIO et R2), `config/filesystems.py` (`FILESYSTEM_DISK`), disque `public` servi par `/storage/<chemin>` (`nosniff`, types non sûrs en pièce jointe, mêmes en-têtes sur S3), `Storage.fake()` ; règles de validation `file`, `image`, `mimes` et tailles en kilo-octets ; la `FormRequest` lit `request.files` (#49).
- **Vues HTML** : une erreur de validation sur un formulaire HTML redirige vers la page précédente (même site) avec `errors` et `old()` dans les templates (saisies bornées à environ 2 Ko, sans mots de passe) ; les routes de `routes/api.py` restent toujours en JSON ; `csrf_field()`, `csrf_token()` et le middleware `VerifyCsrfToken` (419) ; le squelette a un layout, une page de connexion (`/login`, `/logout`, `/dashboard`), le CSRF dans le groupe `web` et `SESSION_COOKIE_SAMESITE = "Lax"` (#19).
- **Tests HTTP** : `app.test_client()` renvoie un client dont les réponses ont des assertions chaînables (`assert_status`, `assert_ok`, `assert_json`, `assert_json_path`, `assert_json_validation_errors`, `assert_header`, `assert_redirect`) et `client.acting_as(user, guard=None)` (session écrite ou vrai token) ; le squelette a un `tests/conftest.py` (base SQLite en mémoire, cache `array`) et un exemple (#46).

## [0.8.0] - 2026-11-27

### Ajouté

- **Tâches planifiées** : `routes/console.py` avec la façade `Schedule` (`command`, `job`, `call`), fréquences (`cron`, `every_five_minutes`, `hourly`, `daily_at`, `weekly_on`, `monthly_on`, `weekdays`…), `timezone`, `without_overlapping`, `on_one_server`, `due_events` pour les tests ; commandes `flask schedule:run`, `schedule:work`, `schedule:list` ; config `app.timezone` (`APP_TIMEZONE`, défaut UTC) (#42).
- Site de documentation (MkDocs Material, publié sur GitHub Pages) : https://ahoblepierre.github.io/flask-artisan/ ; le README est raccourci et renvoie vers le site (#40).

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.8,<0.9`, contient `routes/console.py` (exemples commentés) et `APP_TIMEZONE=UTC`.
- La page PyPI affiche le README court ; la documentation complète est sur le site.

## [0.7.0] - 2026-11-26

### Ajouté

- **Limitation de débit** : middleware `throttle:<max>,<minutes>` (429 avec `Retry-After`, en-têtes `X-RateLimit-*`, par utilisateur après `auth`, sinon par IP), façade `RateLimiter` (`hit`, `attempts`, `too_many_attempts`, `remaining`, `available_in`, `clear`, `attempt`), store des compteurs `cache.limiter`.
- **Verrous** : `Cache.lock(name, seconds)` (`get`, `block`, `release` réservé au propriétaire, `force_release`, `with`), `Cache.restore_lock(name, owner)`, `LockTimeoutError`.
- `app.trusted_proxies` (`TRUSTED_PROXIES`) : IP du client lue derrière un proxy.

### Modifié

- Cache : `add`, `increment` et `pull` du store `file` atomiques entre processus d'une même machine (`flock`, hors Windows) ; store `array` sûr entre threads.
- Squelette : le projet généré dépend de `flask-artisan>=0.7,<0.8`.
- Squelette : alias `throttle`, groupe `api` limité à 60 requêtes par minute, `/api/login` à 5 ; `TRUSTED_PROXIES` dans `.env.example`.

## [0.6.0] - 2026-11-26

### Ajouté

- **Cache** : façade `Cache` (`get`, `put`, `add`, `forever`, `remember`, `remember_forever`, `has`, `missing`, `pull`, `forget`, `increment`, `decrement`, `flush`, `store(name)`), stores `file` (défaut), `redis` (extra `flask-artisan[redis]`, préfixe, `flush` limité au préfixe) et `array`, valeurs en JSON (modèles par identifiant), `flask cache:clear`.

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.6,<0.7`.
- Squelette : `config/cache.py`, `CACHE_STORE` dans `.env.example`, `storage/` dans `.gitignore`.

## [0.5.0] - 2026-11-26

### Ajouté

- **Queues** sur RQ (extra `flask-artisan[rq]`) : `Job` (`handle` avec injection, `failed`, `queue`, `tries`, `backoff`, `timeout`), `dispatch`, `on_queue`, `delay`, `dispatch_sync`, façade `Queue`, pilotes `sync` et `rq`, sérialisation JSON (modèles par identifiant, rechargés à l'exécution), `flask queue:work`, `queue:failed`, `queue:retry`, `queue:forget`, `queue:flush`, `Queue.fake()`, `flask make:job`.
- Mail : `Mail.to(...).queue(...)` et `later(...)`, `assert_queued` / `assert_not_queued` / `assert_nothing_queued` dans `Mail.fake()`.
- Événements : écouteurs `ShouldQueue` exécutés par la file.

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.5,<0.6`.
- Squelette : `config/queue.py`, `QUEUE_CONNECTION` dans `.env.example`, dossier `app/jobs/`.

## [0.4.0] - 2026-11-26

### Ajouté

- **Mail** : `Mailable` (sujet, templates HTML et texte, contexte, pièces jointes `Attachment`, `reply_to`), `Mail.to(...).cc(...).bcc(...).send(...)` et `Mail.mailer(...)`, transports `smtp` (STARTTLS / SSL), `log` et `array`, `Mail.fake()` et ses assertions, `flask make:mail`.
- Templates Jinja cherchés dans `resources/views/`, puis dans `templates/` (défaut de Flask, toujours pris en charge).

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.4,<0.5`.
- Squelette : `config/mail.py`, bloc `MAIL_*` dans `.env.example`, dossiers `app/mail/` et `resources/views/emails/`.

## [0.3.0] - 2026-11-26

### Ajouté

- **Événements** : `Dispatcher` toujours présent (façade `Event`, helper `event()`), écouteurs en classe (injection, reconstruits à chaque émission), tuple ou fonction, héritage et arrêt par `False`, `EventServiceProvider` dans le squelette, `Event.fake()` et ses assertions, `flask make:event` et `flask make:listener`.

### Modifié

- Squelette : le projet généré dépend de `flask-artisan>=0.3,<0.4` et déclare un `EventServiceProvider`.

## [0.2.0] - 2026-11-26

### Ajouté

- **Validation** : `FormRequest` (`rules`, `authorize`, `messages`) validée à l'injection dans les controllers, `Validator` et `validate()`, règles façon Laravel (présence, types, taille, valeurs, `unique`/`exists`), réponses 422 / 403 en JSON, `flask make:request`.

### Modifié

- README : prérequis Python ≥ 3.10 et environnement virtuel dans « Démarrer un projet ».
- Squelette : le projet généré dépend de `flask-artisan>=0.2,<0.3`.
- Squelette : `/api/login` passe par `LoginRequest` et répond 422 (au lieu de 401) à un corps sans `email`/`password` valides.

## [0.1.0] - 2026-11-19

Première version publique.

### Ajouté

- **Socle** : `flask-artisan new <projet>` génère un projet ; `Application` (Flask + conteneur de services), service providers, configuration `config/*.py` + `.env`, façades et helpers (`app`, `config`, `base_path`).
- **Routage** : `routes/web.py` et `routes/api.py` (préfixe `/api`), façade `Route` (verbes, `name`, groupes `prefix`/`name`/`middleware`, `resource`), controllers en classes avec injection, middlewares en oignon déclarés dans un kernel (alias, paramètres, groupes).
- **ORM** façon Eloquent sur SQLAlchemy 2 : modèles annotés, requêtes chaînées, timestamps, soft delete, relations `has_one`/`has_many`/`belongs_to`/`belongs_to_many`, `with_`, assignation de masse (`fillable`), sérialisation JSON (`hidden`), transactions ; SQLite, PostgreSQL, MySQL et MariaDB ; migrations Alembic générées depuis les modèles (`flask make:migration`, `migrate`, `migrate:rollback`, `migrate:status`).
- **Auth** : façade `Auth` (`attempt`, `validate`, `login`, `logout`, `user`…), guards session et token (tokens d'API en base façon Sanctum), hash automatique du mot de passe, middleware `auth` / `auth:api`, routes `/api/login`, `/api/user`, `/api/logout` dans le squelette.
- **Console** : `flask make:controller|model|middleware|provider|command`, commandes du projet découvertes dans `app/console/commands/`, `flask route:list`.

[0.10.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.10.0
[0.9.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.9.0
[0.8.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.8.0
[0.7.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.7.0
[0.6.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.6.0
[0.5.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.5.0
[0.4.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.4.0
[0.3.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.3.0
[0.2.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.2.0
[0.1.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.1.0
