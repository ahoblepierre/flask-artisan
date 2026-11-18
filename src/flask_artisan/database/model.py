import inspect as pyinspect
import re
from datetime import date, datetime, time, timezone
from typing import Any, ClassVar

from sqlalchemy import DateTime, Integer, inspect, select
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedColumn, mapped_column

from flask_artisan.database.query import ModelNotFound

column = mapped_column

PROTECTED = frozenset({"id", "created_at", "updated_at", "deleted_at"})

# Méthodes publiques de Model (et du constructeur de requêtes) : interdites comme noms de colonne.
RESERVED = {
    "all",
    "create",
    "delete",
    "fill",
    "find",
    "find_or_fail",
    "metadata",
    "query",
    "refresh",
    "registry",
    "save",
    "to_dict",
    "update",
}


class MassAssignmentError(Exception):
    pass


class Model(DeclarativeBase):
    """Modèle façon Eloquent : `User.create(...)`, `user.save()`, `User.find(1)`."""

    fillable: ClassVar[list | None] = None
    hidden: ClassVar[list] = []
    timestamps: ClassVar[bool] = True

    def __init_subclass__(cls, **kw):
        if not cls.__dict__.get("__abstract__", False):
            _prepare(cls)
        super().__init_subclass__(**kw)

    # --- classe ---

    @classmethod
    def create(cls, **attrs) -> "Model":
        return cls().fill(**attrs).save()

    @classmethod
    def find(cls, id: Any) -> "Model | None":
        pk = inspect(cls).primary_key[0]
        return _db().session.scalars(select(cls).where(pk == id)).first()

    @classmethod
    def find_or_fail(cls, id: Any) -> "Model":
        found = cls.find(id)
        if found is None:
            raise ModelNotFound(f"{cls.__name__} {id} introuvable.")
        return found

    @classmethod
    def all(cls) -> list:
        return list(_db().session.scalars(select(cls)).all())

    # --- instance ---

    def fill(self, **attrs) -> "Model":
        mapper = inspect(type(self))
        known = {a.key for a in mapper.attrs}
        protected = PROTECTED | {c.key for c in mapper.primary_key}
        for key, value in attrs.items():
            if key in protected:
                continue
            if self.fillable is not None:
                if key in self.fillable:
                    setattr(self, key, value)
                continue
            if key not in known:
                raise MassAssignmentError(
                    f"{type(self).__name__} n'a pas d'attribut '{key}' : retirez-le ou "
                    "déclarez `fillable` pour ignorer les clés en trop."
                )
            setattr(self, key, value)
        return self

    def save(self) -> "Model":
        if self.timestamps:
            now = datetime.now(timezone.utc)
            if getattr(self, "created_at", None) is None:
                self.created_at = now
            self.updated_at = now
        db = _db()
        db.session.add(self)
        _commit(db)
        return self

    def update(self, **attrs) -> "Model":
        return self.fill(**attrs).save()

    def delete(self) -> None:
        db = _db()
        db.session.delete(db.session.merge(self) if inspect(self).detached else self)
        _commit(db)

    def refresh(self) -> "Model":
        session = _db().session
        session.add(self)
        session.refresh(self)
        return self

    def to_dict(self, _seen: set | None = None) -> dict:
        """Colonnes moins `hidden`, plus les relations déjà chargées ; dates en ISO 8601."""
        seen = (_seen or set()) | {id(self)}
        state = inspect(self)
        data = {}
        for attr in state.mapper.column_attrs:
            if attr.key not in self.hidden:
                data[attr.key] = _plain(getattr(self, attr.key))
        for rel in state.mapper.relationships:
            if rel.key in self.hidden or rel.key in state.unloaded:
                continue
            value = getattr(self, rel.key)
            if isinstance(value, Model):
                if id(value) not in seen:
                    data[rel.key] = value.to_dict(seen)
            elif value is None:
                data[rel.key] = None
            else:
                data[rel.key] = [v.to_dict(seen) for v in value if id(v) not in seen]
        return data


def _db():
    from flask_artisan.application import Application

    return Application.get_instance().make("db")


def _commit(db) -> None:
    if db.in_transaction():
        db.session.flush()
    else:
        db.session.commit()


def _plain(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (datetime, date, time)) else value


def _prepare(cls: type) -> None:
    """Avant le mapping : noms réservés, nom de table, id et timestamps par défaut."""
    for name in _declared_names(cls):
        if name in RESERVED:
            raise TypeError(
                f"{cls.__name__}.{name} : '{name}' est une méthode de Model, "
                "choisissez un autre nom de colonne ou de relation."
            )
    if "__tablename__" not in cls.__dict__:
        cls.__tablename__ = _table_name(cls.__name__)
    if not any(isinstance(v, MappedColumn) and v.column.primary_key for v in cls.__dict__.values()):
        cls.id = mapped_column(Integer, primary_key=True, sort_order=-100)
    if cls.timestamps:
        for name in ("created_at", "updated_at"):
            if name not in cls.__dict__:
                setattr(cls, name, mapped_column(DateTime(timezone=True), sort_order=100))


def _declared_names(cls: type) -> set:
    try:  # Python 3.14+ : annotations différées, lues sans les évaluer
        import annotationlib

        names = set(annotationlib.get_annotations(cls, format=annotationlib.Format.FORWARDREF))
    except ImportError:
        names = set(pyinspect.get_annotations(cls))
    return names | {k for k, v in cls.__dict__.items() if isinstance(v, MappedColumn)}


def _table_name(class_name: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    if re.search(r"[^aeiou]y$", snake):
        return snake[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", snake):
        return snake + "es"
    return snake + "s"


__all__ = ["Mapped", "MassAssignmentError", "Model", "column"]
