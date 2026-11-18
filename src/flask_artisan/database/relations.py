from sqlalchemy import Column, ForeignKey, Table, event
from sqlalchemy.orm import Mapper, mapped_column, relationship


class Relation:
    """Marqueur posé dans le corps d'un modèle, converti en relationship() au mapping."""

    def __init__(self, kind: str, model: str, foreign_key: str | None = None, table=None):
        self.kind = kind
        self.model = model
        self.foreign_key = foreign_key
        self.table = table


def has_one(model: str, foreign_key: str | None = None) -> Relation:
    return Relation("has_one", model, foreign_key)


def has_many(model: str, foreign_key: str | None = None) -> Relation:
    return Relation("has_many", model, foreign_key)


def belongs_to(model: str, foreign_key: str | None = None) -> Relation:
    return Relation("belongs_to", model, foreign_key)


def belongs_to_many(model: str, table: str | None = None) -> Relation:
    return Relation("belongs_to_many", model, table=table)


def foreign_id(table: str, on_delete: str | None = None):
    """Colonne clé étrangère vers `table.id` : `user_id: Mapped[int] = foreign_id("users")`."""
    return mapped_column(ForeignKey(f"{table}.id", ondelete=on_delete))


def build(owner: type, attr: str, rel: Relation, snake) -> object:
    """Conventions Laravel : belongs_to part de l'attribut, has_one/has_many du propriétaire."""
    if rel.kind == "belongs_to":
        fk = f"{owner.__name__}.{rel.foreign_key or attr + '_id'}"
        prop = relationship(rel.model, foreign_keys=fk)
    elif rel.kind in ("has_one", "has_many"):
        fk = f"{rel.model}.{rel.foreign_key or snake(owner.__name__) + '_id'}"
        prop = relationship(rel.model, foreign_keys=fk, uselist=rel.kind == "has_many")
    else:
        return relationship(rel.model, secondary=lambda: _pivot(owner, rel, snake))
    _pending.append((prop, rel.kind, owner.__name__, rel.model, fk))
    return prop


# Relations pas encore reliées à leur inverse (has_many User→Post / belongs_to Post→User).
_pending: list[tuple] = []


@event.listens_for(Mapper, "before_configured")
def _link_inverses() -> None:
    """Relie has_one/has_many et belongs_to sur la même clé étrangère (back_populates).

    Sans ce lien, SQLAlchemy avertit que les deux relations écrivent la même colonne.
    """
    parents = [p for p in _pending if p[1] in ("has_one", "has_many")]
    children = [p for p in _pending if p[1] == "belongs_to"]
    for parent in parents:
        matches = [c for c in children if (c[2], c[3], c[4]) == (parent[3], parent[2], parent[4])]
        if len(matches) == 1 and parent[0].back_populates is None:
            child = matches[0]
            parent[0].back_populates = child[0].key
            child[0].back_populates = parent[0].key
    _pending.clear()


def _pivot(owner: type, rel: Relation, snake) -> Table:
    """Table pivot créée à la demande : `post_tag` (post_id, tag_id), ordre alphabétique."""
    target = owner.registry._class_registry[rel.model]
    a, b = snake(owner.__name__), snake(target.__name__)
    name = rel.table or "_".join(sorted([a, b]))
    metadata = owner.metadata
    if name in metadata.tables:
        return metadata.tables[name]
    return Table(
        name,
        metadata,
        Column(f"{a}_id", ForeignKey(f"{owner.__tablename__}.id"), primary_key=True),
        Column(f"{b}_id", ForeignKey(f"{target.__tablename__}.id"), primary_key=True),
    )
