# Changelog

Toutes les évolutions notables de Flask-Artisan. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

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

[0.7.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.7.0
[0.6.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.6.0
[0.5.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.5.0
[0.4.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.4.0
[0.3.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.3.0
[0.2.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.2.0
[0.1.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.1.0
