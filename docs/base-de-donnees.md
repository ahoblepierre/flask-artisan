# Base de données

L'API est façon Eloquent. Le SQL de chaque base est délégué à SQLAlchemy 2, et les migrations à Alembic. On choisit la base dans `.env` :

```
DB_CONNECTION=sqlite      # sqlite (par défaut, rien à installer), mysql, mariadb, pgsql
DB_HOST=127.0.0.1
DB_DATABASE=blog
```

Pilotes : `pip install "flask-artisan[pgsql]"` (PostgreSQL) ou `"flask-artisan[mysql]"` (MySQL et MariaDB).

## Modèles

```python
from flask_artisan.database import (
    Mapped, Model, SoftDeletes, belongs_to, belongs_to_many, column, foreign_id, has_many,
)


class User(Model, SoftDeletes):           # table "users", id, created_at, updated_at, deleted_at
    name: Mapped[str]
    email: Mapped[str] = column(unique=True)
    password: Mapped[str]
    posts = has_many("Post")              # cherche Post.user_id
    fillable = ["name", "email", "password"]
    hidden = ["password"]


class Post(Model):
    title: Mapped[str]
    user_id: Mapped[int] = foreign_id("users")
    user = belongs_to("User")             # utilise user_id (nom de l'attribut + _id)
    tags = belongs_to_many("Tag")         # table pivot post_tag
```

## Requêtes

```python
User.create(name="Ana", email="ana@x.io", password=hashed)
User.find(1)
User.find_or_fail(1)                      # 404 pendant une requête
User.where("name", "like", "A%").or_where("email", "like", "%@x.io").order_by("name").get()
User.where_in("id", [1, 2]).count()
User.with_("posts.tags").latest().first() # chargement immédiat des relations
user.update(name="Bob")
user.delete()                             # avec SoftDeletes : deleted_at rempli
User.with_trashed().get()
User.only_trashed().first().restore()
```

- Un controller peut renvoyer un modèle ou une liste de modèles : la réponse est du JSON, sans les champs de `hidden`.
- Avec `fillable`, toute autre clé est ignorée : `User.create(**request.form)` ne prend pas `is_admin` ni `csrf_token`. `id` et les dates ne sont jamais assignables en masse.
- **`save()` valide toute la session.** Si vous modifiez `a` puis appelez `b.save()`, `a` est aussi enregistré. Pour grouper plusieurs écritures :

```python
from flask_artisan import DB

with DB.transaction():      # validé à la sortie, annulé sur exception
    order.save()
    stock.update(quantity=stock.quantity - 1)
```

`DB.session` donne la session SQLAlchemy, pour tout ce que l'API ne couvre pas.

La session est fermée automatiquement à la fin de chaque requête. Un script ou une commande qui tourne longtemps doit appeler `DB.remove()` quand il a fini, sinon sa connexion reste ouverte.

## Migrations

```bash
flask make:migration "create users"   # compare les modèles à la base, écrit database/migrations/…
flask migrate                         # applique
flask migrate:rollback --step 1       # annule
flask migrate:status                  # [x] appliquée, [ ] en attente
```

Relisez chaque migration générée. Alembic ne voit pas les renommages : il les écrit comme une suppression suivie d'un ajout.

Dans les tests, `DB.create_all()` crée les tables sans passer par les migrations. C'est pratique avec `DB_DATABASE=:memory:`.
