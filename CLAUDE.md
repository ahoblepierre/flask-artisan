# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Le projet

Flask-Artisan : un framework open source qui apporte les conventions de Laravel à Flask. **Flask reste le moteur** (décision actée) : on ajoute une couche (conteneur, service providers, façades, routage à la Laravel, ORM façon Eloquent sur SQLAlchemy, auth, commandes ajoutées au CLI `flask`) sans casser la compatibilité avec l'écosystème Flask. Le différenciateur face à Masonite est justement d'être du Flask.

Chantiers 1 à 5 de la v0.1 mergés (socle #1, routage #3, ORM #5, auth #7, CLI #9). Publiée sur PyPI (0.1.0 #11, 0.2.0 #17 avec la validation #15, 0.3.0 #22 avec les événements #20, 0.4.0 #26 avec le mail #24, 0.5.0 #30 avec les queues #28, 0.6.0 #34 avec le cache #32, 0.7.0 #38 avec la limitation de débit et les verrous #36, 0.8.0 #44 avec les tâches planifiées #42 et le site de documentation #40).

## Feuille de route (v0.1 publique = chantiers 1 à 5)

Chaque chantier a sa propre spec et son propre plan, dans cet ordre :

1. **Socle** : package pip `flask-artisan` (framework) séparé d'un squelette de projet généré par `flask-artisan new <projet>` ; `Application` qui enveloppe Flask, conteneur, service providers, config `config/*.py` + `.env`, façades.
2. **Routage & middlewares** : `routes/web.py` / `routes/api.py`, controllers en classes, groupes/préfixes, middlewares nommés via un kernel.
3. **ORM** : modèles façon Eloquent sur SQLAlchemy 2 (timestamps, soft delete, relations), migrations Alembic via le CLI.
4. **Auth** : façade `Auth`, guards session et token, hash automatique, middleware `auth`.
5. **CLI** : commandes ajoutées à `flask` (`flask make:*`, `flask migrate`, `flask route:list`) ; seule la création de projet passe par `flask-artisan new`.

Après v0.1 : validation (Form Requests), helpers, events, mail, cache, queues.

## Tickets, branches, specs

Ce repo est public et n'utilise **pas** le Jira de l'entreprise (remplace la règle Jira globale). Les tickets sont des **GitHub Issues** sur `ahoblepierre/flask-artisan` (créer avec `gh issue create`).

- Branche : `feat/<n°>-slug` ou `fix/<n°>-slug`
- Spec / plan : `docs/superpowers/specs/GH-<n°>-spec.md`, `docs/superpowers/plans/GH-<n°>-plan.md`
- Commit et titre de PR contiennent `(#<n°>)` ; la PR ferme l'issue (`Closes #<n°>`).

## Publication

Version unique : `__version__` de `src/flask_artisan/__init__.py` (lu par setuptools). Publication par `.github/workflows/publish.yml` (Trusted Publishing) : lancement manuel → TestPyPI, tag `v*` → PyPI après approbation. Procédure dans CONTRIBUTING.md.

## Commandes

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                         # toute la suite
.venv/bin/pytest tests/test_container.py::test_bound     # un seul test
.venv/bin/ruff check . && .venv/bin/ruff format .        # lint + format (la CI vérifie les deux)
.venv/bin/flask-artisan new /chemin/vers/demo            # générer un projet pour essayer
.venv/bin/pip install -e ".[docs]" && .venv/bin/mkdocs serve   # prévisualiser le site de doc
```

## Documentation

La doc publique vit dans `docs/*.md` (site MkDocs Material, `mkdocs.yml`, publié sur GitHub Pages par `.github/workflows/docs.yml` à chaque push sur `main`) ; `docs/superpowers/` (specs, plans) est exclu du site. Le README reste court (page PyPI, liens absolus seulement). Une fonctionnalité met à jour sa page ; `mkdocs build --strict` échoue sur un lien ou une ancre cassés.

## Architecture

- **Trois livrables distincts** : le repo (code + docs + tests), le package pip (`src/flask_artisan/` seulement) et le projet généré (copie de `src/flask_artisan/skeleton/`). `packages.find include = ["flask_artisan*"]` couvre tous les sous-paquets (squelette et `alembic_env` compris, sinon setuptools les livre en « données » de façon dépréciée) ; les fichiers non Python (dotfiles du squelette, `stubs/`, `alembic_env/*.mako`) sont listés dans `package-data`.
- `Application` ([application.py](src/flask_artisan/application.py)) hérite de `Flask` **et** de `Container`. Le constructeur charge `.env`, puis `config/*.py` dans un `Repository`, fait le pont vers `app.config` (`SECRET_KEY`, `DEBUG`, contenu de `config/flask.py`), s'enregistre dans le conteneur (`"app"`, `"config"`), devient l'instance courante, puis register/boot les providers de `config("app.providers")`.
- L'état interne du conteneur est préfixé `_container_` et deux tests garantissent qu'aucun nom ne masque un attribut de Flask : tout nouvel attribut d'`Application`/`Container` doit passer ces tests.
- Façades et helpers résolvent via `Application.get_instance()`, sans cache. Les tests remettent l'instance à `None` (fixture autouse dans `tests/conftest.py`).
- **Routage** ([routing.py](src/flask_artisan/routing.py)) : un `Router` est enregistré dans le conteneur (`"router"`, façade `Route`).
  - Les routes ne sont acceptées que dans la « fenêtre de collecte » que `Application.boot()` (et `register()` après le boot) ouvre autour des `boot()` des providers.
  - À la fermeture de la fenêtre, `flush()` les pousse dans Flask avec `add_url_rule`. C'est ce qui permet à `.name()` de s'appliquer après `Route.get()`.
  - Chaque vue exécute le pipeline de middlewares résolu depuis le kernel au `flush` ([middleware.py](src/flask_artisan/middleware.py)), puis le handler via `app.make` (controller) et `app.call` (injection). Chaque résultat passe par `make_response`.
  - `RouteServiceProvider` branche le kernel dans `register()` et charge `routes/*.py` dans `boot()`.
- **Base de données** ([database/](src/flask_artisan/database/)) : sous-paquet.
  - `DatabaseServiceProvider` enregistre le `DatabaseManager` (`"db"`, façade `DB`), remplace `app.json` (sérialisation des modèles) et ajoute les commandes de migration à `app.cli`.
  - Le manager possède le moteur (créé à la première utilisation) et une `scoped_session` avec `expire_on_commit=False`. La session est retirée en fin de requête. `save()` valide toute la session, sauf dans `DB.transaction()`.
  - `Model.__init_subclass__` complète la classe avant le mapping : noms réservés, `__tablename__`, `id`, timestamps, conversion des marqueurs `has_many`/`belongs_to`… en `relationship()`.
  - Les paires has_many/belongs_to sur la même clé sont reliées par `back_populates` dans un écouteur `before_configured`. Les SAWarning sont des erreurs dans pytest.
  - Le soft delete est un filtre global `with_loader_criteria` posé sur l'événement `do_orm_execute` du sessionmaker. Il est désactivé par l'option d'exécution `include_trashed`.
  - Alembic est piloté par programme : `env.py` et `script.py.mako` sont fournis par le package (`alembic_env/`), et les versions vivent dans `database/migrations/` du projet.
  - Les modèles et `Model.metadata` sont globaux au processus : les modèles de test portent des noms uniques dans toute la suite (préfixe par fichier : `QUser`, `RPost`…).
- **Auth** ([auth/](src/flask_artisan/auth/)) : sous-paquet, `AuthServiceProvider` enregistre l'`AuthManager` (`"auth"`, façade `Auth`).
  - `Authenticatable` hache `password` via `@validates` de SQLAlchemy : appelé à l'affectation, jamais au chargement. Une valeur déjà hachée (`scrypt:`, `pbkdf2:`) est gardée.
  - `PersonalAccessToken` est un modèle du framework : il entre dans `Model.metadata` dès l'import de `flask_artisan.auth`. La façade `Auth` (accesseur en chaîne) n'importe pas ce sous-paquet, pour qu'un projet sans auth n'ait pas cette table.
  - Les guards sont construits à chaque appel depuis `config/auth.py`. L'utilisateur résolu et le guard choisi par le middleware (`should_use`) vivent dans `request.environ` (pas `g`, que partagent les requêtes d'un même app context englobant).
  - La session stocke l'id et une empreinte du hash du mot de passe : changer le mot de passe coupe les sessions. Le hard delete d'un utilisateur supprime ses tokens (SQLite réutilise les id).
- **Console** ([console.py](src/flask_artisan/console.py)) : `Application` remplace `app.cli` par un `ArtisanGroup` et y ajoute `make:*` et `route:list`. Les modèles de fichiers sont dans `stubs/` (`string.Template`, listés dans `package-data`).
  - Les commandes Click de `app/console/commands/*.py` ne sont importées que par le CLI (`list_commands`, ou `get_command` pour un nom qui n'est pas une commande du framework) : un fichier cassé ne bloque ni l'app web ni `make:*`/`migrate`/`route:list`. Leur callback est enveloppé dans `with_appcontext`.
  - `make:model` et `make:command` refusent les sous-dossiers : `import_models` et la découverte ne lisent que le premier niveau.
  - `Router.registered` garde (route, endpoint, middlewares résolus) de chaque route poussée dans Flask, pour `route:list`.
- **Validation** ([validation.py](src/flask_artisan/validation.py)) : `FormRequest.__init__` lit la requête, appelle `authorize()` puis valide ; l'autowiring du conteneur suffit à la déclencher pour un paramètre de controller annoté. `ValidationError` (422) et `AuthorizationError` (403) sont des `HTTPException` qui portent leur réponse JSON (aucun gestionnaire enregistré) ; le `Router` les rend au dernier étage du pipeline, pour que les middlewares voient le 422/403. Les règles sont des fonctions `(valeur, params, champ, validator)` dans `RULES`, jamais appelées avec `None` ; paramètres et identifiants SQL sont vérifiés à la construction du `Validator` (erreur du développeur → `ValueError`). `unique`/`exists` passent par `DB.session`.
- **Événements** ([events.py](src/flask_artisan/events.py)) : `Application` crée le `Dispatcher` à côté du `Router` (`"events"`, façade `Event`). Les écouteurs sont normalisés à `listen` (erreur immédiate si invalides) ; une classe est reconstruite par `app.make` à chaque émission. `Event.fake()` est un **mode** du dispatcher (pas une instance de remplacement) : les services qui le tiennent déjà le voient ; `EventFake` lit ses enregistrements et `restore()` (ou la sortie du `with`) quitte le mode fake, indispensable car les tests du squelette partagent une seule app.
- **Mail** ([mail.py](src/flask_artisan/mail.py)) : `Application` crée le `Mailer` à côté du `Dispatcher` (`"mail"`, façade `Mail`) ; bibliothèque standard seulement (`email.message`, `smtplib`). La config `mail.*` est relue à chaque envoi (défauts sans `config/mail.py` : `log`) ; `smtp` et `log` sont reconstruits à chaque envoi, seuls les transports `array` sont gardés (pour leurs messages). `Mail.fake()` est un mode du mailer, comme `Event.fake()` ; il enregistre une copie du mailable avec ses destinataires, sans rendu. Les templates sont cherchés dans `resources/views/` puis `templates/` : `jinja_loader` est affecté **à l'instance** dans `Application.__init__` (le redéfinir dans la classe casserait le test qui interdit de masquer Flask).
- **Queues** ([queue/](src/flask_artisan/queue/)) : sous-paquet, `Application` crée le `QueueManager` (`"queue"`, façade `Queue`, helper `dispatch`). Moteur = **RQ**, importé seulement à l'usage (`worker.py`, `commands.py`) : sans l'extra `[rq]`, le pilote `sync` suffit. Jobs stockés en JSON (`JSONSerializer` passé à chaque file, registre et worker ; jamais `pickle`), les modèles par identifiant (`serialization.py`), reconstruits sans `__init__` et vérifiés (sous-classe de `Job`/`Mailable`/`ShouldQueue`/`Model`) — défense en profondeur seulement : Redis est une infrastructure de confiance, car RQ importe la fonction nommée avant notre code. `queue:work` = `SimpleWorker` dans le processus de l'app ; `worker.run` pousse un contexte d'application par job (sa fin retire la session), alors qu'un job `sync` réutilise le contexte de l'appelant pour ne pas retirer sa session. `failed()` seulement quand `retries_left` est épuisé ; `tries` dans `job.meta` pour que `queue:retry` rende tous les essais. `Queue.fake()` est un mode du gestionnaire. Les tests sont dans `tests/queues/` (un dossier `queue` masquerait le module standard) et utilisent `fakeredis[lua]`.
- **Cache** ([cache.py](src/flask_artisan/cache.py)) : `Application` crée le `CacheManager` (`"cache"`, façade `Cache` ; ses méthodes publiques visent le store par défaut via `__getattr__`). `Store` porte toute la logique (clés, TTL, `remember`, `pull`, lecture tolérante : valeur illisible = absente et supprimée) ; chaque pilote (`ArrayStore`, `FileStore`, `RedisStore`) ne stocke que du texte JSON (`_get`, `_put`, `_add`, `_delete`, `_pull`, `_increment`, `_flush`). Valeurs par la sérialisation des queues (modèles par identifiant), jamais `pickle`. `put(k, None)` supprime. Redis : client mis en cache par URL (`_redis`), `flush` par `SCAN` sur le préfixe échappé, `pull` en `MULTI`. Config relue à chaque `store()` ; seuls les `array` sont gardés. Tests de contrat communs aux trois pilotes dans `tests/cache/` (horloge : `time.time` remplacé).
- **Limitation de débit et verrous** ([rate_limiting.py](src/flask_artisan/rate_limiting.py), `Lock` dans [cache.py](src/flask_artisan/cache.py)) : `Application` crée le `RateLimiter` (`"limiter"`, façade `RateLimiter`) ; compteurs `key` + `key:timer` dans le store `cache.limiter` (sinon défaut), algorithme `hit` de Laravel (jamais de compteur sans TTL). Middleware `ThrottleRequests` (alias `throttle` du squelette) : clé `sha1(max|minutes|identité)`, identité = `user:<guard>:<id>` d'un utilisateur **déjà résolu** dans `request.environ["flask_artisan.auth"]` (jamais d'authentification par `throttle`), sinon IP ; vérifie, compte, puis refuse et décompte si `hit` dépasse (rafale) ; en-têtes posés par `setdefault` (le plus proche de la route gagne). `Cache.lock` : `_add` pour prendre, primitive `_delete_if` pour libérer (propriétaire encodé en JSON ; Lua sur Redis). Sections critiques : `threading.Lock` pour `array`, `fcntl.flock` sur `.lock` du dossier pour `file` (ouvert en lecture seule, rien sous Windows ; **non réentrant** : sous `_locked`, lire par `_read`, jamais `_get`, qui reprend le verrou pour supprimer une clé expirée). `app.trusted_proxies` (`TRUSTED_PROXIES`) enveloppe `wsgi_app` dans `ProxyFix` (IP et schéma seulement, jamais `X-Forwarded-Host`). Tests dans `tests/rate_limiting/`.
- **Tâches planifiées** ([scheduling.py](src/flask_artisan/scheduling.py)) : `Application` crée le registre `Schedule` (`"schedule"`, façade `Schedule`), rempli par `routes/console.py` que seules les commandes `schedule:*` chargent (`load` vide le registre puis exécute le fichier ; jamais l'app web). `CronExpression` maison (5 champs, règle du « ou » jour du mois / jour de semaine, pas de dépendance) ; `Event.is_due` compare l'heure locale du fuseau (`tz` de la tâche, sinon `app.timezone`). `run_due` exécute en séquence : commande par `app.cli.main(standalone_mode=False)` dans le même processus, job envoyé par la queue, fonction par `app.call` (positionnels liés par nom). Échec isolé (trace sur stderr, code 1). Verrous par `Cache.lock` : `schedule:<sha1(expr+fuseau+nom)>` pour `without_overlapping` (libéré en `finally`), suffixé de la minute UTC pour `on_one_server` (jamais libéré). `_now`/`_sleep` sont remplacés dans les tests ; `schedule:work` pousse un contexte d'app par minute. Tests dans `tests/scheduling/`.
- **Vues HTML** ([views.py](src/flask_artisan/views.py), [csrf.py](src/flask_artisan/csrf.py)) : `Router._view` rend `ValidationError`/`AuthorizationError` en JSON si `route.json` (groupe ouvert par `load(..., json=True)`, posé pour `routes/api.py`) ou `expects_json` (dans `middleware.py`, réimporté par `auth`), sinon redirige en arrière (Referer du même hôte, sinon `/`) en flashant `_flash_errors`/`_flash_old` (sans mots de passe ni saisie > 1000 caractères). `age_flash` (premier `before_request`) les déplace vers `request.environ["flask_artisan.flash"]` et remet `session.accessed` à False s'il n'y a rien (Flask 3.1 marque toute lecture, d'où un `Vary: Cookie` sinon). `context_processor` : `errors`, `old`, `csrf_token`, `csrf_field`. `VerifyCsrfToken` : `_token` ou `X-CSRF-TOKEN` contre `session["_token"]`, 419, sauté si `app.testing`.
- **Tests HTTP** ([testing.py](src/flask_artisan/testing.py)) : `Application.__init__` fixe `test_client_class = TestClient` à l'instance (comme `jinja_loader`). `TestClient` combine `TestResponse` (assertions chaînables) avec `app.response_class`, comme Werkzeug le fait déjà : la réponse reste une réponse Flask. `acting_as` passe par le vrai guard (session écrite par `session_transaction`, ou vrai token `"test"` dans `environ_base`) ; import tardif de `flask_artisan.auth` (table des tokens). Le `tests/conftest.py` du squelette force SQLite en mémoire et le cache `array` avant d'importer `wsgi`.
- `Application.get_instance()` renvoie `current_app` pendant une requête, sinon la dernière app créée.
- `flask run` écrase `app.debug` avec `FLASK_DEBUG` : le `.env` du squelette contient `FLASK_DEBUG=${APP_DEBUG}`. Les tests du projet généré tournent en sous-processus avec un environnement sans `FLASK_*`/`APP_*`.
