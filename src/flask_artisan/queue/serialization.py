"""Sérialisation JSON des jobs : les modèles voyagent par identifiant, rechargés à l'exécution."""

import importlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any

MARKERS = ("__model__", "__datetime__", "__date__", "__decimal__")


def class_path(cls: type) -> str:
    """Chemin d'import `module.Classe` ; une classe locale ne peut pas être retrouvée."""
    if "<locals>" in cls.__qualname__:
        raise TypeError(
            f"{cls.__qualname__} : une classe mise en file doit être définie au niveau d'un "
            "module (pas dans une fonction)."
        )
    return f"{cls.__module__}.{cls.__qualname__}"


def import_class(path: str, base: type) -> type:
    """Importe `module.Classe` et vérifie que c'est une sous-classe de `base`."""
    if not isinstance(path, str) or "." not in path:
        raise TypeError(f"Chemin de classe invalide : {path!r}.")
    cls = None
    # Les classes imbriquées (A.B) : on remonte jusqu'à un module importable.
    parts = path.split(".")
    for i in range(len(parts) - 1, 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        try:
            for name in parts[i:]:
                target = getattr(target, name)
        except AttributeError:
            break
        cls = target
        break
    if not isinstance(cls, type) or not issubclass(cls, base):
        raise TypeError(f"{path!r} n'est pas une classe {base.__name__}.")
    return cls


def dump(value: Any, where: str) -> Any:
    """Convertit une valeur en JSON ; `where` nomme l'attribut dans les erreurs."""
    from flask_artisan.database.model import Model

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [dump(item, where) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError(f"{where} : les clés d'un dict mis en file doivent être des chaînes.")
        if any(key in MARKERS for key in value):
            raise TypeError(f"{where} : clé réservée ({', '.join(MARKERS)}).")
        return {key: dump(item, f"{where}.{key}") for key, item in value.items()}
    if isinstance(value, Model):
        if getattr(value, "id", None) is None:
            raise TypeError(
                f"{where} : modèle sans id (enregistrez-le avant de le mettre en file)."
            )
        return {"__model__": class_path(type(value)), "id": value.id}
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    raise TypeError(
        f"{where} : valeur de type {type(value).__name__} impossible à mettre en file "
        "(acceptés : JSON, modèle, datetime, date, Decimal)."
    )


def load(value: Any) -> Any:
    if isinstance(value, list):
        return [load(item) for item in value]
    if isinstance(value, dict):
        if "__model__" in value:
            from sqlalchemy import inspect

            from flask_artisan.database.model import Model

            cls = import_class(value["__model__"], Model)
            if inspect(cls, raiseerr=False) is None:  # Model lui-même, ou une classe non mappée
                raise TypeError(f"{value['__model__']!r} n'est pas un modèle mappé.")
            return cls.find_or_fail(value["id"])
        if "__datetime__" in value:
            return datetime.fromisoformat(value["__datetime__"])
        if "__date__" in value:
            return date.fromisoformat(value["__date__"])
        if "__decimal__" in value:
            return Decimal(value["__decimal__"])
        return {key: load(item) for key, item in value.items()}
    return value


def serialize(obj: Any) -> dict:
    """{"class": chemin, "data": attributs publics convertis}."""
    cls = type(obj)
    path = class_path(cls)
    data = {
        key: dump(item, f"{cls.__name__}.{key}")
        for key, item in vars(obj).items()
        if not key.startswith("_")
    }
    return {"class": path, "data": data}


def restore(payload: dict, base: type) -> Any:
    """Reconstruit l'objet sans appeler `__init__` (comme Laravel)."""
    cls = import_class(payload.get("class"), base)
    obj = cls.__new__(cls)
    for key, item in (payload.get("data") or {}).items():
        if not isinstance(key, str) or key.startswith("_"):
            raise TypeError(f"Attribut invalide dans un job : {key!r}.")
        setattr(obj, key, load(item))
    return obj
