# GH-5 — ORM : modèles façon Eloquent sur SQLAlchemy 2, migrations Alembic

Ticket : https://github.com/ahoblepierre/flask-artisan/issues/5
Statut : brouillon, en attente d'approbation

## Intention

Un projet Flask-Artisan n'a aujourd'hui aucune couche de données. Ce chantier apporte un ORM dont l'API est **maison et façon Eloquent** :

```python
User.where("age", ">", 18).order_by("name").first()
user.save()
post.comments
```

Le SQL de chaque base est délégué à **SQLAlchemy 2**, et les migrations à **Alembic**.

Le but est de laisser chaque projet choisir sa base sans toucher au code : SQLite, PostgreSQL, MySQL ou MariaDB, sélectionnée dans le `.env` comme dans Laravel.

## Objectifs

1. Changer de base revient à changer `DB_CONNECTION` (et installer le pilote). Le code des modèles et des requêtes ne bouge pas.
2. Un développeur Laravel reconnaît l'API : `find`, `where`, `create`, `save`, `delete`, timestamps, soft delete, `fillable`, `hidden`, relations, `with_`.
3. Les colonnes sont décrites une seule fois, dans le modèle, avec des annotations de type. L'IDE connaît donc `user.email`.
4. Les migrations sont générées en comparant les modèles à la base, puis appliquées et annulées par des commandes `flask`.
5. Le projet généré marche tout de suite sur SQLite, sans rien installer.

## Non-objectifs

- Factories et seeders.
- Pagination.
- ORM asynchrone.
- Événements de modèle (`creating`, `saved`…) et observers.
- Plusieurs connexions utilisées en même temps : on peut en déclarer plusieurs, mais seule `default` sert.
- Requêtes de masse (`User.where(...).update(...)` ou `.delete()`).
- Scopes locaux ou globaux définis par l'utilisateur.
- Casts et accessors.
- `migrate:fresh`, `migrate:refresh`.
- Liaison automatique d'un modèle depuis l'URL (route model binding) : à revoir après ce chantier.
- Les autres générateurs `flask make:*` (model, controller…) : chantier 5.

## Anti-objectifs

- Générer du SQL nous-mêmes. Tout passe par SQLAlchemy, sans aucune concaténation de valeurs dans du SQL.
- Exiger Flask-SQLAlchemy ou s'y brancher.
- Empêcher l'usage direct de SQLAlchemy. `DB.session` et `select()` restent accessibles comme porte de sortie.
- Exiger un pilote de base pour démarrer : SQLite (bibliothèque standard) suffit.

## Approches considérées

**Moteur**

| | Approche | Verdict |
|---|---|---|
| A | API maison, SQLAlchemy 2 seul en dessous (sans Flask-SQLAlchemy) | **Choisie par Pierre** : l'API est entièrement à nous, et le SQL de chaque base vient d'un outil éprouvé. |
| B | Tout maison : générateur SQL et une grammaire par base | Écartée : des mois de travail, migrations comprises, et un risque d'injection SQL à chaque erreur d'échappement. |
| C | Par-dessus Flask-SQLAlchemy | Écartée : on ne contrôle plus l'API ni la session. |

**Description des colonnes**

| | Approche | Verdict |
|---|---|---|
| 1 | Dans le modèle (annotations `Mapped`), migrations générées en comparant modèles et base | **Choisie par Pierre** : les colonnes s'écrivent une fois et l'IDE les connaît. Le geste n'est pas celui de Laravel, et la migration générée est à relire. |
| 2 | Dans les migrations avec un constructeur `Schema`, le modèle ne décrivant rien | Écartée : le modèle lit la base au démarrage (il faut donc une base pour démarrer), l'IDE ne connaît plus les colonnes, et il faudrait écrire et maintenir `Schema`. |

## Décisions

### Dépendances et pilotes

- `sqlalchemy>=2.0` et `alembic>=1.13` deviennent des dépendances du package : l'ORM fait partie du framework.
- Les pilotes sont des extras : `flask-artisan[pgsql]` installe `psycopg[binary]`, et `flask-artisan[mysql]` installe `PyMySQL` (MySQL et MariaDB). SQLite n'a besoin de rien.

### Configuration

Le squelette contient `config/database.py` :

```python
config = {
    "default": env("DB_CONNECTION", "sqlite"),
    "connections": {
        "sqlite": {"driver": "sqlite", "database": env("DB_DATABASE", "database/database.sqlite")},
        "mysql":  {"driver": "mysql",  "host": ..., "port": 3306, "database": ..., "username": ..., "password": ...},
        "mariadb": {...même forme que mysql...},
        "pgsql":  {"driver": "pgsql",  "host": ..., "port": 5432, ...},
    },
}
```

- Chaque connexion accepte une clé `url` (lue dans `DB_URL`). Si elle est présente, elle remplace les autres clés.
- Le framework construit l'URL SQLAlchemy depuis le driver :
  - `sqlite` → `sqlite:///chemin` ;
  - `mysql` et `mariadb` → `mysql+pymysql://…` ;
  - `pgsql` → `postgresql+psycopg://…`.
- Un chemin SQLite relatif s'entend depuis la racine du projet.
- `:memory:` doit marcher pour les tests : une seule connexion partagée par toute l'app.
- Le `.env.example` du squelette reçoit `DB_CONNECTION=sqlite`, et les autres clés `DB_*` en commentaire.
- Un pilote absent donne une erreur qui dit quel extra installer.

### Connexion et session

- Un `DatabaseServiceProvider` du framework enregistre un `DatabaseManager` en singleton dans le conteneur, sous `"db"` et sous sa classe.
- Ce manager possède le moteur (créé à la première utilisation) et la session.
- Le squelette ajoute ce provider à `config/app.py`.
- Une façade `DB` donne :
  - `DB.session` : la session SQLAlchemy courante ;
  - `with DB.transaction():` ;
  - `DB.engine` ;
  - *Choix de Claude :* `DB.create_all()` et `DB.drop_all()`, qui créent et suppriment les tables de tous les modèles importés, sans passer par les migrations. Ils sont documentés pour les tests sur `:memory:`.
- La session vit le temps d'une requête. Elle est fermée à la fin de la requête (`teardown_appcontext`), et ce qui n'a pas été validé est annulé.
- Hors requête (`flask shell`, commandes, tests), la session marche aussi et dure jusqu'au `DB.session.close()` suivant.
- `save()`, `create()`, `update()` et `delete()` **valident immédiatement**, comme dans Laravel où chaque `save()` est une requête.
- **Toute la session est validée** (décision de Pierre). `a.name = "x"` suivi de `b.save()` écrit donc aussi `a`. C'est le comportement normal de SQLAlchemy, mais il s'écarte de Laravel : la doc le dit.
- *Choix de Claude :* la session est créée avec `expire_on_commit=False`, pour que les objets restent lisibles et sérialisables après `save()` et après la fermeture de la session en fin de requête.
- À l'intérieur de `with DB.transaction():`, ils se contentent d'envoyer les changements. La transaction est validée à la sortie du bloc et annulée en cas d'exception. Les transactions imbriquées ne sont pas gérées dans ce chantier : un `transaction()` imbriqué rejoint simplement celle qui est en cours.

### Modèles

```python
from flask_artisan.database import Model, SoftDeletes, Mapped, column, foreign_id

class User(Model, SoftDeletes):
    name: Mapped[str]
    email: Mapped[str] = column(unique=True)
    password: Mapped[str]
    fillable = ["name", "email", "password"]
    hidden = ["password"]
```

- `Model` est la base déclarative SQLAlchemy du framework.
- `column(...)` enveloppe `mapped_column`, et `Mapped` est réexporté. Toute la syntaxe SQLAlchemy 2 reste valide dans un modèle.
- **Clé primaire :** chaque modèle a `id: Mapped[int]`, entier auto-incrémenté, sauf s'il déclare lui-même sa clé.
- **Nom de table :** le nom de la classe, en snake_case et au pluriel (`User` → `users`, `BlogPost` → `blog_posts`, `Category` → `categories`). La pluralisation suit des règles anglaises simples : `y` → `ies`, `s/x/z/ch/sh` → `es`, sinon `s`. `__tablename__` la surcharge.
- **Timestamps :** `created_at` et `updated_at` sont ajoutés par défaut, en UTC et avec fuseau. Ils sont remplis par `save()`. `timestamps = False` les désactive.
- **Soft delete :** `SoftDeletes` ajoute `deleted_at`.
  - `delete()` remplit `deleted_at` au lieu de supprimer la ligne.
  - Toutes les requêtes du modèle excluent ces lignes, relations comprises.
  - `Model.with_trashed()` et `Model.only_trashed()` reviennent sur ce filtre.
  - `restore()` remet la ligne, `force_delete()` la supprime vraiment, et `trashed()` dit si elle est supprimée.
- **Assignation de masse :**
  - si `fillable` est déclaré, `create()`, `fill()` et `update()` ignorent toute autre clé, y compris une clé qui ne correspond à aucune colonne (*choix de Claude* : `User.create(**request.form)` ne casse pas à cause de `csrf_token`) ;
  - sans `fillable`, toute clé qui correspond à une colonne est acceptée, et une clé qui ne correspond à aucune colonne lève une erreur ;
  - *choix de Claude :* `id`, `created_at`, `updated_at` et `deleted_at` ne sont jamais assignables en masse.
- *Choix de Claude :* une colonne ou une relation qui porte le nom d'une méthode du modèle ou du constructeur de requête (`count`, `latest`, `save`, `query`…) lève une erreur dès la définition de la classe, en nommant l'attribut en cause.
- **Sérialisation :**
  - `to_dict()` renvoie les colonnes moins `hidden`, plus les relations déjà chargées (sérialisées de la même façon). Les dates sont au format ISO 8601.
  - Un controller peut renvoyer un modèle, une liste de modèles ou un dict qui en contient : Flask en fait du JSON. On étend le fournisseur JSON de Flask, sans toucher à `make_response`.

### Requêtes

API sur la classe, qui renvoie un constructeur de requête chaînable :

| Méthode | Effet |
|---|---|
| `Model.query()` | constructeur vide |
| `Model.all()` | toutes les lignes |
| `Model.find(id)` | la ligne ou `None` |
| `Model.find_or_fail(id)` | la ligne ou `ModelNotFound`, une sous-classe de `werkzeug.exceptions.NotFound` (donc une 404 dans une requête) |
| `Model.create(**attrs)` | crée, enregistre et renvoie l'instance |
| `.where(col, valeur)` / `.where(col, op, valeur)` | `op` parmi `=`, `!=`, `<`, `<=`, `>`, `>=`, `like` ; un autre opérateur lève une erreur |
| `.or_where(...)` | même forme, en OU |
| `.where_in(col, valeurs)`, `.where_null(col)`, `.where_not_null(col)` | — |
| `.order_by(col, "asc" \| "desc")`, `.latest(col="created_at")`, `.limit(n)`, `.offset(n)` | — |
| `.with_(*relations)` | chargement immédiat des relations (`"posts"`, `"posts.comments"`) |
| `.get()`, `.first()`, `.first_or_fail()`, `.count()`, `.exists()`, `.pluck(col)` | exécution |

- Toutes les méthodes du constructeur sont aussi accessibles depuis la classe : `User.where(...)` équivaut à `User.query().where(...)`.
- Un nom de colonne inconnu lève une erreur qui le nomme.
- Instance : `save()`, `update(**attrs)`, `delete()`, `refresh()`, `fill(**attrs)`.

### Relations

```python
class User(Model):
    posts = has_many("Post")
    profile = has_one("Profile")

class Post(Model):
    user_id: Mapped[int] = foreign_id("users")
    user = belongs_to("User")
    tags = belongs_to_many("Tag")
```

- Clés étrangères par convention, comme Laravel (*choix de Claude*) :
  - `belongs_to` part du **nom de l'attribut** : `user = belongs_to("User")` utilise `user_id`, et `author = belongs_to("User")` utilise `author_id` ;
  - `has_one` et `has_many` partent du **modèle propriétaire** : `posts = has_many("Post")` sur `User` cherche `user_id` dans `Post`.

  Un argument `foreign_key=` les surcharge.
- `foreign_id("users")` déclare une colonne entière avec clé étrangère vers `users.id`, avec `on_delete=` en option.
- `belongs_to_many` crée la table pivot par convention :
  - nom = les deux noms de modèle au singulier en snake_case, par ordre alphabétique (`post_tag`) ;
  - colonnes `post_id` et `tag_id`, clés étrangères, clé primaire composite.

  Un argument `table=` surcharge le nom. Pour une table pivot déclarée par le framework, la migration générée la crée comme les autres.
- Chargement paresseux par défaut. `with_()` charge tout d'un coup.
- `post.tags.append(tag)` suivi de `save()` fonctionne, comme une liste SQLAlchemy.

### Migrations

- Commandes ajoutées au CLI `flask` :
  - `flask make:migration "add users"` : génère par comparaison, puis affiche le fichier créé ;
  - `flask migrate` : applique tout ;
  - `flask migrate:rollback [--step N]` : annule, 1 étape par défaut ;
  - `flask migrate:status` : liste les migrations appliquées et en attente.
- Les fichiers vivent dans `database/migrations/` et sont nommés `AAAA_MM_JJ_HHMMSS_add_users.py`. Le framework fournit l'environnement Alembic, donc le projet n'a ni `alembic.ini` ni `env.py`.
- Pour la comparaison, `make:migration` importe tous les modules de `app/models/` (convention du squelette), afin que tous les modèles soient connus.
- SQLite : le mode « batch » d'Alembic est activé pour que les modifications de colonnes marchent.
- `make:migration` sans changement détecté ne crée pas de fichier et le dit.

### Squelette

```
app/models/__init__.py
app/models/user.py              exemple : User(name, email, password), fillable, hidden
config/database.py
database/migrations/            dossier vide (.gitkeep)
database/.gitignore             ignore *.sqlite
```

- `config/app.py` ajoute `DatabaseServiceProvider`.
- Le test du projet généré vérifie que `flask make:migration` puis `flask migrate` créent la table `users` dans SQLite.

### Exports

- `from flask_artisan import DB` (façade).
- `from flask_artisan.database import Model, SoftDeletes, Mapped, column, foreign_id, has_one, has_many, belongs_to, belongs_to_many, ModelNotFound, DatabaseManager, DatabaseServiceProvider`.

## Pièges connus

- **Modèles globaux, moteurs par application.** Les classes de modèles et leurs métadonnées sont globales au processus. Le moteur et la session appartiennent à l'application (via `Application.get_instance()`). Deux apps dans un même processus partagent donc les modèles mais pas les bases.
- **Ce qu'Alembic ne voit pas.** Il ne détecte pas un renommage de colonne ou de table (il le voit comme une suppression suivie d'un ajout). La doc doit dire de relire chaque migration générée.
- **Session hors requête.** Un script qui ne ferme jamais la session garde une connexion ouverte. C'est le comportement normal de SQLAlchemy, et la doc le mentionne.

## Laissé au constructeur

- Découpage en modules sous `src/flask_artisan/database/`.
- Branchement du JSON. Flask crée son fournisseur JSON dans `Flask.__init__` : il faut donc remplacer `app.json` dans le provider, et non passer par `json_provider_class`.
- Mécanique du filtre soft delete (`with_loader_criteria`, événement `do_orm_execute` ou filtre dans le constructeur), du moment que les relations en profitent aussi.
- Mécanique de génération de la table pivot et de résolution des noms de modèles en chaîne.
- Nom de la table de suivi des migrations : celle d'Alembic par défaut, ou `migrations` comme Laravel.
- Format exact de la sortie de `migrate:status`.

## Livraison

- Tests pytest sur SQLite (fichier et `:memory:`) pour la config, les modèles, les requêtes, le soft delete, les relations, la sérialisation, les transactions et les commandes de migration.
- Test de bout en bout du projet généré.
- Pas de test PostgreSQL ou MySQL en CI dans ce chantier : la construction des URL est testée sans serveur.
- README (section base de données) et CLAUDE.md mis à jour.
- PR `feat/5-orm`, titre avec `(#5)`, corps avec `Closes #5`. CI verte sur 3.10 à 3.13.
