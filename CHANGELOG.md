# Changelog

Toutes les évolutions notables de Flask-Artisan. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), versions [SemVer](https://semver.org/lang/fr/).

## Non publié

### Ajouté

- **Mail** : `Mailable` (sujet, templates HTML et texte, contexte, pièces jointes `Attachment`, `reply_to`), `Mail.to(...).cc(...).bcc(...).send(...)` et `Mail.mailer(...)`, transports `smtp` (STARTTLS / SSL), `log` et `array`, `Mail.fake()` et ses assertions, `flask make:mail`.
- Templates Jinja cherchés dans `resources/views/`, puis dans `templates/` (défaut de Flask, toujours pris en charge).

### Modifié

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

[0.3.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.3.0
[0.2.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.2.0
[0.1.0]: https://github.com/ahoblepierre/flask-artisan/releases/tag/v0.1.0
