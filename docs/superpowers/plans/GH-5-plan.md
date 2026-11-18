# ORM et migrations — plan d'implémentation

> **Pour les agents :** sous-skill requis : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans pour exécuter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**But :** un ORM à l'API façon Eloquent (modèles, requêtes chaînées, timestamps, soft delete, relations, JSON) sur SQLAlchemy 2, plus des migrations Alembic générées depuis les modèles et pilotées par `flask make:migration`, `flask migrate`, `flask migrate:rollback` et `flask migrate:status`.

**Architecture :**
- Un sous-package `flask_artisan.database` contient le code.
- Un `DatabaseManager`, singleton du conteneur sous `"db"`, possède le moteur et une `scoped_session` (`expire_on_commit=False`). La session est retirée en fin de requête.
- `Model` est la base déclarative SQLAlchemy du framework. Son `__init_subclass__` complète la classe avant le mapping : nom de table, `id`, timestamps, relations par convention, contrôle des noms réservés.
- Les requêtes passent par un constructeur `Builder` qui enveloppe un `select()`.
- Le soft delete est un filtre global posé sur l'événement `do_orm_execute` du sessionmaker, avec `with_loader_criteria`. Ce filtre s'applique aussi aux relations chargées à la demande : c'est vérifié sur SQLAlchemy 2.1.
- Alembic est piloté par programme. Son `env.py` est fourni par le framework, et les versions sont dans `database/migrations/` du projet.

**Stack :** Python ≥ 3.10, Flask ≥ 3, SQLAlchemy ≥ 2.0, Alembic ≥ 1.13, pytest, ruff.

**Spec :** [docs/superpowers/specs/GH-5-spec.md](../specs/GH-5-spec.md)

## Contraintes globales

- Dépendances du package : `sqlalchemy>=2.0`, `alembic>=1.13`. Extras : `pgsql = ["psycopg[binary]>=3.1"]`, `mysql = ["PyMySQL>=1.1"]`.
- Aucune valeur n'est concaténée dans du SQL : tout passe par les expressions SQLAlchemy.
- `save()`, `create()`, `update()` et `delete()` valident toute la session (décision de Pierre). Dans `DB.transaction()`, ils se contentent d'un `flush()`.
- Les champs `id`, `created_at`, `updated_at` et `deleted_at` ne sont jamais assignables en masse.
- Avec `fillable`, toute autre clé est ignorée en silence. Sans `fillable`, une clé qui n'est pas une colonne lève `MassAssignmentError`.
- Messages d'erreur en français, nommant le modèle, la colonne ou l'attribut fautif.
- Tout attribut ajouté à `Application` doit passer les tests « aucun attribut Flask masqué ».
- Les modèles de test portent des noms uniques dans toute la suite, préfixés par fichier (`QUser`, `RPost`…). Le registre SQLAlchemy est global, et deux classes de même nom cassent la résolution des relations par nom.
- Commits : `feat: … (#5)`, `docs: … (#5)`. Lancer `.venv/bin/ruff check . && .venv/bin/ruff format --check .` avant chaque commit.

## Review Focus

1. **Deux apps dans un même processus.** Elles partagent les modèles, mais chacune a son moteur : un modèle sauvé dans l'app A ne doit pas apparaître dans la base de B (tâche 1).
2. **Session en fin de requête.** Un changement non validé est annulé, et un objet renvoyé par le controller reste sérialisable après la fermeture, grâce à `expire_on_commit=False` (tâches 1 et 2).
3. **Soft delete et relations.** `user.posts` et `with_("posts")` excluent les posts supprimés. `with_trashed()` ne fuit pas sur les requêtes suivantes (tâche 4).
4. **`update()` avec `fillable` et des clés parasites** (`csrf_token`) : elles sont ignorées et rien ne casse (tâche 2).
5. **Migration de modification sous SQLite** : ajouter une colonne non nulle sans valeur par défaut, puis faire un rollback. Le mode batch doit tenir le coup (tâche 6).

## Fichiers

| Fichier | Rôle |
|---|---|
| `pyproject.toml` | dépendances, extras, package-data (env Alembic et dotfiles du squelette) |
| `src/flask_artisan/database/__init__.py` | exports publics |
| `src/flask_artisan/database/connection.py` | `connection_url(conn: dict, base_path: Path) -> str`, erreur de pilote absent |
| `src/flask_artisan/database/manager.py` | `DatabaseManager` |
| `src/flask_artisan/database/provider.py` | `DatabaseServiceProvider` (manager, teardown, JSON, CLI) |
| `src/flask_artisan/database/model.py` | `Model`, `SoftDeletes`, `column`, `foreign_id`, nommage, assignation de masse, `to_dict` |
| `src/flask_artisan/database/query.py` | `Builder`, `ModelNotFound` |
| `src/flask_artisan/database/relations.py` | `has_one`, `has_many`, `belongs_to`, `belongs_to_many` |
| `src/flask_artisan/database/json.py` | fournisseur JSON qui sérialise les modèles |
| `src/flask_artisan/database/migrations.py` | commandes CLI de migration |
| `src/flask_artisan/database/alembic_env/env.py`, `script.py.mako` | environnement Alembic fourni par le framework |
| `src/flask_artisan/facades.py`, `src/flask_artisan/__init__.py` | façade `DB` |
| `src/flask_artisan/skeleton/…` | modèles, config, migrations |
| `tests/conftest.py` | fixture `db_app` |
| `tests/database/test_*.py` (nouveau dossier, avec `__init__.py`) | — |
| `README.md`, `CLAUDE.md` | doc |

## Fixture de test commune (tâche 1)

`db_app(*providers, database="':memory:'")` crée un projet par `make_project` en ajoutant `DatabaseServiceProvider` et les providers donnés. Elle écrit `config/database.py` avec une connexion `sqlite` vers `database`, construit l'`Application`, appelle `DB.create_all()` et renvoie l'app. Les tâches suivantes l'utilisent toutes.

---

### Task 1: dépendances, connexion, `DatabaseManager`, provider et façade `DB`

**Fichiers :**
- Modifier : `pyproject.toml`, `src/flask_artisan/facades.py`, `src/flask_artisan/__init__.py`, `tests/conftest.py`
- Créer : `database/__init__.py`, `connection.py`, `manager.py`, `provider.py`
- Test : `tests/database/test_connection.py`, `tests/database/test_manager.py`

**Interfaces :**
- Produit :
  - `connection_url(conn: dict, base_path: Path) -> str`.
  - `class DatabaseError(Exception)`.
  - `class DatabaseManager` :
    - `__init__(self, app)` ;
    - `engine` (propriété, moteur créé à la première utilisation) ;
    - `session` (propriété : la session courante de la `scoped_session`) ;
    - `transaction()`, un gestionnaire de contexte ;
    - `in_transaction() -> bool` ;
    - `create_all()`, `drop_all()` ;
    - `remove()`, qui ferme la session courante.
  - `DatabaseServiceProvider`. Son `register()` enregistre le manager en singleton sous `"db"` et `DatabaseManager`, et branche `teardown_appcontext` sur `remove()`.
  - La façade `DB` (accessor `"db"`).
  - La fixture `db_app`. Tant que `Model` n'existe pas (tâche 2), `create_all` agit sur une métadonnée vide.

- [ ] **Étape 1 : tests.**
  - `test_connection.py`, construction des URL :
    - SQLite relatif résolu depuis `base_path` → `sqlite:////abs/…/database/database.sqlite` ;
    - `:memory:` → `sqlite://` ;
    - `mysql` et `mariadb` → `mysql+pymysql://u:p@h:3306/db` ;
    - `pgsql` → `postgresql+psycopg://u:p@h:5432/db` ;
    - un mot de passe contenant `@` ou `/` est échappé (le construire avec `sqlalchemy.engine.URL.create`) ;
    - `url` présente → elle gagne ;
    - driver inconnu → `DatabaseError` qui nomme le driver.
  - `test_connection.py`, `test_missing_driver_names_extra` : en simulant l'absence du module `pymysql` (`monkeypatch.setitem(sys.modules, "pymysql", None)`), accéder à `manager.engine` pour une connexion `mysql` lève `DatabaseError`, avec `flask-artisan[mysql]` dans le message.
  - `test_manager.py` :
    - `test_db_registered` : `app.make("db") is app.make(DatabaseManager)`, et `DB.engine` fonctionne ;
    - `test_memory_shared_connection` : une table créée avec `DB.session.execute(text("create table t(x int)"))` puis validée reste visible après `DB.remove()` ;
    - `test_session_removed_on_teardown` : une ligne insérée sans commit pendant une requête (route déclarée par un provider de test) n'est plus là après la requête ;
    - `test_transaction_commits_and_rolls_back` : une exception dans `with DB.transaction()` annule. `in_transaction()` vaut `True` dans le bloc et `False` après ;
    - `test_nested_transaction_joins` : un `transaction()` imbriqué ne valide pas avant la sortie du bloc externe ;
    - `test_two_apps_two_databases` : deux `db_app` sur deux fichiers SQLite distincts (`tmp_path`). Une table créée dans l'un n'existe pas dans l'autre.
- [ ] **Étape 2 :** `.venv/bin/pytest tests/database -q`. Attendu : erreurs d'import.
- [ ] **Étape 3 : implémenter.**
  - `pyproject.toml` : ajouter les dépendances et les extras ; package-data `"database/alembic_env/*"` (créé en tâche 6, à déclarer maintenant) ; réinstaller avec `.venv/bin/pip install -e ".[dev]"`.
  - Pour `:memory:`, le moteur utilise `poolclass=StaticPool` et `connect_args={"check_same_thread": False}`.
  - La session est `scoped_session(sessionmaker(engine, expire_on_commit=False))`.
  - La façade `DB` va dans `facades.py`, et l'export dans `flask_artisan/__init__.py`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : tout vert.
- [ ] **Étape 5 :** commit `feat: connexion à la base, DatabaseManager et façade DB (#5)`.

### Task 2: `Model` (nommage, `id`, timestamps, assignation de masse, persistance, JSON)

**Fichiers :**
- Créer : `database/model.py`, `database/json.py`, et le début de `database/query.py` (`ModelNotFound`, plus le strict nécessaire à `find`/`all`)
- Modifier : `database/provider.py` (JSON), `database/__init__.py`
- Test : `tests/database/test_model.py`

**Interfaces :**
- Consomme : `DatabaseManager.session`, `in_transaction()`.
- Produit :
  - `class Model(DeclarativeBase)`, avec :
    - attributs de classe `fillable: list | None = None`, `hidden: list = []`, `timestamps = True` ;
    - classe : `create(**attrs)`, `find(id)`, `find_or_fail(id)`, `all()` ;
    - instance : `fill(**attrs) -> self`, `save() -> self`, `update(**attrs) -> self`, `delete() -> None`, `refresh() -> self`, `to_dict() -> dict`.
  - `column(*args, **kw)` (alias de `mapped_column`), `Mapped` réexporté.
  - `class MassAssignmentError(Exception)`, `class ModelNotFound(werkzeug.exceptions.NotFound)`.
  - Constante `RESERVED: frozenset[str]`, la liste des noms de méthodes publiques de `Model` et de `Builder`. La tâche 3 la complète.
  - Le modèle accède à sa session par `Application.get_instance().make("db")`.

- [ ] **Étape 1 : tests** (modèles préfixés `M`).
  - `test_tablename` : `MUser` → `m_users`, `MCategory` → `m_categories`, `MBox` → `m_boxes`, `MBlogPost` → `m_blog_posts`. `__tablename__` explicite → respecté.
  - `test_id_added` : `MUser.__table__.c.id.primary_key`. Un modèle qui déclare `code: Mapped[str] = column(primary_key=True)` n'a pas de colonne `id`.
  - `test_timestamps` : `create()` remplit `created_at` et `updated_at` (aware UTC), et `save()` après modification avance `updated_at`. Avec `timestamps = False`, pas de colonnes.
  - `test_create_find_all`.
  - `test_find_or_fail_404` : une route qui fait `MUser.find_or_fail(999)` → 404.
  - `test_fillable_ignores_other_keys` : `create(name=…, csrf_token=…, is_admin=True)` avec `fillable=["name"]` → `is_admin` reste à sa valeur par défaut, sans erreur.
  - `test_without_fillable_unknown_key_raises` : `MassAssignmentError` qui nomme la clé.
  - `test_protected_fields_never_mass_assigned` : `create(id=50, created_at=…)` sans `fillable` → `id != 50`, et sans erreur (les champs protégés sont ignorés).
  - `test_save_commits_whole_session` : `a.name = "x"`, puis `b.save()`, puis une nouvelle session → `a` est modifié en base. Ce test fixe le comportement documenté.
  - `test_save_inside_transaction_only_flushes` : une exception dans le bloc annule le `save()`.
  - `test_update_and_delete_and_refresh`.
  - `test_reserved_name_raises` : définir `class MBad(Model): count: Mapped[int]` lève `TypeError`, dont le message contient `count`.
  - `test_to_dict_hidden_and_iso_dates`.
  - `test_controller_returns_model_and_list` : les routes renvoient `MUser.find(1)` et `MUser.all()`, et donnent du JSON sans `password`. Les dates sont en ISO.
  - `test_serializable_after_request_session_closed` : l'objet renvoyé est sérialisé après `remove()`, sans erreur.
- [ ] **Étape 2 :** lancer les tests. Attendu : erreurs d'import.
- [ ] **Étape 3 : implémenter.**
  - Avant `super().__init_subclass__()`, `Model.__init_subclass__` :
    1. contrôle `RESERVED` sur les annotations et les attributs du `__dict__` de la classe ;
    2. pose `__tablename__` s'il est absent ;
    3. ajoute `id` si aucune colonne n'a `primary_key=True` ;
    4. ajoute `created_at` et `updated_at` (`DateTime(timezone=True)`) si `timestamps` est vrai.

    Les mixins (`SoftDeletes`) et les classes `__abstract__` sont ignorés.
  - Les timestamps sont remplis dans `save()` avec `datetime.now(timezone.utc)`.
  - `app.json` est remplacé dans `DatabaseServiceProvider.register()` par une sous-classe de `DefaultJSONProvider`, dont `default()` gère `Model` via `to_dict()`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: Model façon Eloquent, timestamps, assignation de masse et JSON (#5)`.

### Task 3: constructeur de requêtes

**Fichiers :**
- Modifier : `database/query.py`, `database/model.py`
- Test : `tests/database/test_query.py`

**Interfaces :**
- Consomme : `Model` (tâche 2).
- Produit :
  - `class Builder`, avec :
    - `where(col, op_or_value, value=_MISSING)`, `or_where(...)`, `where_in(col, values)`, `where_null(col)`, `where_not_null(col)` ;
    - `order_by(col, direction="asc")`, `latest(col="created_at")`, `limit(n)`, `offset(n)` ;
    - `with_(*relations)` (enregistré ici, appliqué en tâche 5) ;
    - `get() -> list`, `first()`, `first_or_fail()`, `count() -> int`, `exists() -> bool`, `pluck(col) -> list`.

    Chaque méthode chaînable renvoie un nouveau `Builder` : le builder est immuable, donc un builder réutilisé ne fuit pas.
  - `Model.query() -> Builder`. Chaque méthode publique du builder est aussi accessible depuis la classe (`classmethod` qui fait `cls.query().<méthode>(...)`).
  - `RESERVED` contient tous ces noms.

- [ ] **Étape 1 : tests** (modèles préfixés `Q`, avec un jeu de 5 lignes).
  - Opérateurs : `where("age", 30)`, et `=`, `!=`, `<`, `<=`, `>`, `>=`, `like`.
  - `test_invalid_operator_raises`, `test_unknown_column_raises` : le message nomme l'opérateur ou la colonne.
  - `test_or_where` : `where(a).or_where(b)` donne `a OR b`.
  - `where_in`, `where_null`, `where_not_null`.
  - `order_by` asc et desc, `latest`, `limit` et `offset`.
  - `first`, `first_or_fail` (404 sur un résultat vide), `count`, `exists`, `pluck`.
  - `test_builder_is_immutable` : `base = QUser.where("age", ">", 1)`, puis `base.where("name", "x")` ne modifie pas `base.count()`.
  - `test_class_level_proxies` : `QUser.where(...)` équivaut à `QUser.query().where(...)`.
  - `test_injection_safe` : `where("name", "x' OR '1'='1")` renvoie 0 ligne.
- [ ] **Étape 2 :** lancer les tests. Attendu : FAIL.
- [ ] **Étape 3 :** implémenter.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: constructeur de requêtes chaînable (#5)`.

### Task 4: `SoftDeletes`

**Fichiers :**
- Modifier : `database/model.py`, `database/manager.py` (événement `do_orm_execute`), `database/query.py`
- Test : `tests/database/test_soft_deletes.py`

**Interfaces :**
- Produit :
  - `class SoftDeletes` (mixin) : `deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)` ;
  - instance : `delete()` (pose `deleted_at` puis `save()`), `restore()`, `force_delete()`, `trashed() -> bool` ;
  - classe et builder : `with_trashed()`, `only_trashed()`.
  - Le filtre global est enregistré sur le sessionmaker du manager. Il s'applique quand `is_select` est vrai et que l'option d'exécution `include_trashed` est absente : `with_loader_criteria(SoftDeletes, lambda cls: cls.deleted_at.is_(None), include_aliases=True)`.

- [ ] **Étape 1 : tests** (préfixe `S`).
  - `delete` puis `find` → `None`, et une ligne existe toujours en base (`text("select count(*)")`).
  - `with_trashed().count()` inclut la ligne, `only_trashed()` ne renvoie qu'elle.
  - `restore()` la fait réapparaître, `force_delete()` la supprime de la table.
  - `test_with_trashed_does_not_leak` : après un `with_trashed()`, un `SUser.all()` exclut à nouveau la ligne.
  - `test_relation_excludes_trashed` est **écrit en tâche 5**, quand les relations existent.
- [ ] **Étape 2 :** lancer les tests. Attendu : FAIL.
- [ ] **Étape 3 :** implémenter.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: soft delete (#5)`.

### Task 5: relations et `with_`

**Fichiers :**
- Créer : `database/relations.py`
- Modifier : `database/model.py`, `database/query.py`, `database/manager.py` (`create_all` appelle `configure_mappers()` d'abord)
- Test : `tests/database/test_relations.py`

**Interfaces :**
- Produit :
  - `has_one(model: str, foreign_key=None)`, `has_many(model: str, foreign_key=None)`, `belongs_to(model: str, foreign_key=None)` et `belongs_to_many(model: str, table=None)`. Chacun renvoie un marqueur que `Model.__init_subclass__` convertit en `relationship()`, avant le mapping, avec ces conventions :
    - `belongs_to` sur l'attribut `attr` → `foreign_keys="{Owner}.{attr}_id"` ;
    - `has_one`/`has_many` sur `Owner` → `foreign_keys="{Target}.{snake(Owner)}_id"`, et `uselist=False` pour `has_one` ;
    - `belongs_to_many` → `secondary=` un callable qui crée la table pivot à la demande dans `Model.metadata`. Nom par défaut : les deux noms de modèle au singulier en snake_case, par ordre alphabétique. Colonnes `{a}_id` et `{b}_id`, avec clés étrangères vers les `__tablename__` réels et clé primaire composite.
  - `foreign_id(table: str, on_delete: str | None = None)` : `mapped_column(ForeignKey(f"{table}.id", ondelete=on_delete))`.
  - `Builder.with_` est appliqué avec `selectinload`. Le chemin pointé (`"posts.comments"`) est enchaîné.

- [ ] **Étape 1 : tests** (préfixe `R` : `RUser`, `RPost`, `RTag`, `RProfile`, `RComment`).
  - `has_many` et son inverse `belongs_to` : `user.posts` et `post.user`.
  - `test_belongs_to_key_from_attribute` : `author = belongs_to("RUser")` avec la colonne `author_id = foreign_id("r_users")` fonctionne, y compris quand le même modèle a aussi `user_id`.
  - `has_one` renvoie un objet, pas une liste.
  - `belongs_to_many` : la table `r_post_r_tag` existe après `create_all()`, et `post.tags.append(tag); post.save()` est relu depuis une nouvelle session.
  - `belongs_to_many(..., table="taggings")` surcharge le nom.
  - `test_with_loads_eagerly` : après `RUser.with_("posts").get()` puis `DB.remove()`, `users[0].posts` est accessible.
  - `with_("posts.comments")`.
  - `test_relation_excludes_trashed` : `RPost` utilise `SoftDeletes`, et un post supprimé n'apparaît ni dans `user.posts` ni dans `with_("posts")`.
  - `test_to_dict_includes_loaded_relations_only` : `to_dict()` contient `posts` après `with_`, et ne le contient pas sans (aucune requête déclenchée).
- [ ] **Étape 2 :** lancer les tests. Attendu : FAIL.
- [ ] **Étape 3 :** implémenter.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: relations has_one, has_many, belongs_to, belongs_to_many (#5)`.

### Task 6: migrations Alembic et commandes `flask`

**Fichiers :**
- Créer : `database/migrations.py`, `database/alembic_env/env.py`, `database/alembic_env/script.py.mako`
- Modifier : `database/provider.py` (dans `register()` : `app.cli.add_command(...)` pour les 4 commandes)
- Test : `tests/database/test_migrations.py`

**Interfaces :**
- Produit :
  - `alembic_config(app) -> alembic.config.Config`, avec :
    - `script_location` = le dossier `alembic_env` du package ;
    - `version_locations` = `<projet>/database/migrations` ;
    - `file_template = "%%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d%%(second).2d_%%(slug)s"`.

    L'objet `app` est transmis à `env.py` par `config.attributes["app"]`.
  - `env.py` :
    - prend le moteur via `app.make("db").engine` et `target_metadata = Model.metadata` ;
    - appelle `configure_mappers()` avant tout ;
    - active `render_as_batch` quand le dialecte est SQLite ;
    - supporte le mode online uniquement.
  - Commandes click :
    - `make:migration MESSAGE` : importe tous les modules de `app/models/` avec `importlib.import_module("app.models.<nom>")`, la racine du projet étant dans `sys.path`, puis lance l'autogénération. Si aucun changement n'est détecté (callback `process_revision_directives` qui vide les directives), il affiche « Aucun changement détecté » et ne crée pas de fichier. Sinon, il affiche le chemin créé ;
    - `migrate` : `upgrade head` ;
    - `migrate:rollback --step N` : `downgrade -N` (1 par défaut) ;
    - `migrate:status` : une ligne par révision, `[x]` appliquée ou `[ ]` en attente, avec le nom de fichier.
  - Le dossier `database/migrations/` est créé s'il manque.

- [ ] **Étape 1 : tests.** Ils passent par `app.test_cli_runner().invoke(args=[...])`, avec un projet sur un fichier SQLite et un module de modèle écrit dans `<projet>/app/models/mig_note.py`. La racine du projet est ajoutée à `sys.path` le temps du test. Le modèle est créé une seule fois par session de test, sous un nom unique `MigNote`.
  - `test_make_migration_creates_file` : le nom de fichier respecte `^\d{4}_\d{2}_\d{2}_\d{6}_create_notes\.py$`, et le contenu contient `create_table`.
  - `test_make_migration_no_changes` : après `migrate`, un second `make:migration` affiche « Aucun changement » et ne crée pas de fichier.
  - `test_migrate_creates_table` : `inspect(engine).has_table("mig_notes")`.
  - `test_status` : `[ ]` avant `migrate`, `[x]` après.
  - `test_rollback_drops_table`.
  - `test_sqlite_alter_in_batch` : ajouter une colonne non nulle avec `server_default` au modèle, générer, migrer, puis faire un rollback, sans erreur. Le modèle est modifié par un second fichier dans un dossier temporaire distinct, ou en redéfinissant la table via `extend_existing` : au choix de l'exécutant, avec une ruling.
- [ ] **Étape 2 :** lancer les tests. Attendu : FAIL (`No such command`).
- [ ] **Étape 3 :** implémenter, puis vérifier que `alembic_env/` est bien embarqué par le wheel : `pip wheel . --no-deps -w <scratch>` puis `unzip -l | grep alembic_env`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q`. Attendu : vert.
- [ ] **Étape 5 :** commit `feat: migrations Alembic et commandes flask make:migration / migrate (#5)`.

### Task 7: squelette, documentation et bout en bout

**Fichiers :**
- Créer dans `skeleton/` :
  - `app/models/__init__.py`, `app/models/user.py` ;
  - `config/database.py` ;
  - `database/migrations/.gitkeep`, `database/.gitignore` (`*.sqlite`).
- Modifier :
  - `skeleton/config/app.py` : `DatabaseServiceProvider` en premier provider ;
  - `skeleton/.env.example` : `DB_CONNECTION=sqlite`, et les autres `DB_*` en commentaire ;
  - `pyproject.toml` : package-data pour les deux dotfiles ;
  - `README.md`, `CLAUDE.md`.
- Test : `tests/test_cli.py`.

**Interfaces :**
- Le `User` du squelette : `name`, `email` (unique), `password`, `fillable = ["name", "email", "password"]` et `hidden = ["password"]`.

- [ ] **Étape 1 : tests.**
  - `test_generated_project_has_database_files` : `config/database.py`, `app/models/user.py` et `database/migrations/.gitkeep` existent.
  - `test_generated_project_migrates` : en sous-processus dans le projet généré, `flask make:migration "create users"` puis `flask migrate` réussissent (`returncode == 0`), et `database/database.sqlite` contient la table `users` (vérifié avec `sqlite3`).

  Les tests existants du squelette restent verts.
- [ ] **Étape 2 :** `.venv/bin/pytest tests/test_cli.py -q`. Attendu : les nouveaux tests échouent.
- [ ] **Étape 3 :** écrire le squelette, puis vérifier le wheel : `unzip -l` doit contenir `skeleton/database/.gitignore`, `skeleton/database/migrations/.gitkeep` et `config/database.py`.
- [ ] **Étape 4 :** `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`. Attendu : vert.
- [ ] **Étape 5 : documentation.**
  - README : section « Base de données », avec :
    - le choix de la base dans le `.env` et les extras `[pgsql]` et `[mysql]` ;
    - les modèles, les requêtes, le soft delete et les relations ;
    - la phrase « `save()` valide toute la session » ;
    - `DB.transaction()` et `DB.create_all()` pour les tests ;
    - les migrations, avec « relisez chaque migration générée : un renommage apparaît comme suppression + ajout ».

    Cocher le chantier 3 dans la feuille de route.
  - CLAUDE.md :
    - architecture de `flask_artisan.database` (manager et `scoped_session`, `Model.__init_subclass__`, filtre soft delete via `do_orm_execute`, environnement Alembic fourni par le package) ;
    - la règle de nommage des modèles de test.
- [ ] **Étape 6 :** commits `feat: le squelette a une base SQLite, un modèle User et des migrations (#5)`, puis `docs: base de données dans README et CLAUDE.md (#5)`.

---

## Vérification finale

- `.venv/bin/pytest -q` est vert, et ruff est propre.
- À la main, dans un projet généré :
  1. `flask make:migration "create users"`, puis `flask migrate` ;
  2. dans `flask shell` : `User.create(name="a", email="a@x", password="p")` puis `User.all()` ;
  3. `flask migrate:status` affiche `[x]`.
