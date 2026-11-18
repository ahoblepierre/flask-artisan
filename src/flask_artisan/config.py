import importlib.util
from pathlib import Path
from typing import Any

_MISSING = object()


class ConfigError(Exception):
    pass


class Repository:
    """Configuration de l'application, accessible en notation pointée (`app.name`)."""

    def __init__(self, items: dict | None = None):
        self._items = items if items is not None else {}

    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._items
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def has(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def set(self, key: str, value: Any) -> None:
        *parents, last = key.split(".")
        node = self._items
        for part in parents:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[last] = value

    def all(self) -> dict:
        return self._items

    @classmethod
    def from_directory(cls, path: Path) -> "Repository":
        """Charge chaque `config/<nom>.py` (dict `config`) sous la clé `<nom>`."""
        path = Path(path)
        items = {}
        if path.is_dir():
            for file in sorted(path.glob("*.py")):
                if not file.name.startswith("_"):
                    items[file.stem] = _load_file(file)
        return cls(items)


def _load_file(file: Path) -> dict:
    # Chargé par chemin, jamais par nom de module : pas de conflit avec un autre package `config`.
    spec = importlib.util.spec_from_file_location(f"flask_artisan_config_{file.stem}", file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ConfigError(
            f"Impossible de charger le fichier de config {file.name} : {exc}"
        ) from exc
    value = getattr(module, "config", None)
    if not isinstance(value, dict):
        raise ConfigError(
            f"Le fichier de config {file.name} doit définir un dict `config = {{...}}`."
        )
    return value
