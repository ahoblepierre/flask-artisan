import copy
import operator
from typing import Any

from sqlalchemy import func, inspect, literal, select
from werkzeug.exceptions import NotFound


class ModelNotFound(NotFound):
    """Levée par find_or_fail / first_or_fail : une 404 pendant une requête."""


OPERATORS = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "like": lambda col, value: col.like(value),
}

_MISSING = object()


class Builder:
    """Requête chaînable et immuable : chaque méthode renvoie un nouveau Builder."""

    def __init__(self, model: type):
        self._model = model
        self._condition = None
        self._order: tuple = ()
        self._limit: int | None = None
        self._offset: int | None = None
        self._load: tuple = ()
        self._options: dict = {}

    # --- construction ---

    def where(self, col: str, op_or_value: Any, value: Any = _MISSING) -> "Builder":
        return self._add(operator.and_, self._compare(col, op_or_value, value))

    def or_where(self, col: str, op_or_value: Any, value: Any = _MISSING) -> "Builder":
        return self._add(operator.or_, self._compare(col, op_or_value, value))

    def where_in(self, col: str, values) -> "Builder":
        return self._add(operator.and_, self._column(col).in_(list(values)))

    def where_null(self, col: str) -> "Builder":
        return self._add(operator.and_, self._column(col).is_(None))

    def where_not_null(self, col: str) -> "Builder":
        return self._add(operator.and_, self._column(col).is_not(None))

    def order_by(self, col: str, direction: str = "asc") -> "Builder":
        if direction not in ("asc", "desc"):
            raise ValueError(f"Direction de tri '{direction}' invalide : 'asc' ou 'desc'.")
        column = self._column(col)
        return self._copy(_order=(*self._order, column.desc() if direction == "desc" else column))

    def latest(self, col: str = "created_at") -> "Builder":
        return self.order_by(col, "desc")

    def limit(self, n: int) -> "Builder":
        return self._copy(_limit=n)

    def offset(self, n: int) -> "Builder":
        return self._copy(_offset=n)

    def with_(self, *relations: str) -> "Builder":
        return self._copy(_load=(*self._load, *relations))

    def with_trashed(self) -> "Builder":
        self._require_soft_deletes()
        return self._copy(_options={**self._options, "include_trashed": True})

    def only_trashed(self) -> "Builder":
        return self.with_trashed().where_not_null("deleted_at")

    # --- exécution ---

    def get(self) -> list:
        return list(self._session().scalars(self._select(select(self._model))).all())

    def first(self):
        return self._session().scalars(self.limit(1)._select(select(self._model))).first()

    def first_or_fail(self):
        found = self.first()
        if found is None:
            raise ModelNotFound(f"Aucun {self._model.__name__} ne correspond à la requête.")
        return found

    def count(self) -> int:
        stmt = self._filtered(select(func.count()).select_from(self._model))
        return self._session().scalar(stmt)

    def exists(self) -> bool:
        stmt = self._filtered(select(literal(1)).select_from(self._model)).limit(1)
        return self._session().scalar(stmt) is not None

    def pluck(self, col: str) -> list:
        return list(self._session().scalars(self._select(select(self._column(col)))).all())

    # --- interne ---

    def _copy(self, **changes) -> "Builder":
        new = copy.copy(self)
        new.__dict__.update(changes)
        return new

    def _add(self, conjunction, expr) -> "Builder":
        condition = expr if self._condition is None else conjunction(self._condition, expr)
        return self._copy(_condition=condition)

    def _column(self, name: str):
        if name not in inspect(self._model).column_attrs:
            raise ValueError(f"{self._model.__name__} n'a pas de colonne '{name}'.")
        return getattr(self._model, name)

    def _compare(self, col: str, op_or_value: Any, value: Any):
        op, value = ("=", op_or_value) if value is _MISSING else (op_or_value, value)
        if op not in OPERATORS:
            raise ValueError(f"Opérateur '{op}' invalide : {', '.join(OPERATORS)}.")
        return OPERATORS[op](self._column(col), value)

    def _filtered(self, stmt):
        if self._condition is not None:
            stmt = stmt.where(self._condition)
        return stmt.execution_options(**self._options) if self._options else stmt

    def _select(self, stmt):
        stmt = self._filtered(stmt)
        if self._order:
            stmt = stmt.order_by(*self._order)
        if self._limit is not None:
            stmt = stmt.limit(self._limit)
        if self._offset is not None:
            stmt = stmt.offset(self._offset)
        return stmt

    def _require_soft_deletes(self) -> None:
        from flask_artisan.database.model import SoftDeletes

        if not issubclass(self._model, SoftDeletes):
            raise TypeError(f"{self._model.__name__} n'utilise pas SoftDeletes.")

    def _session(self):
        from flask_artisan.database.model import _db

        return _db().session
