import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_KEYWORDS = {
    "true": True,
    "(true)": True,
    "false": False,
    "(false)": False,
    "null": None,
    "(null)": None,
    "empty": "",
    "(empty)": "",
}


def env(key: str, default: Any = None) -> Any:
    """Lit une variable d'environnement avec les conversions de Laravel."""
    value = os.environ.get(key)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in _KEYWORDS:
        return _KEYWORDS[lowered]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_env_file(path: Path) -> None:
    """Charge un fichier .env sans écraser les variables déjà définies."""
    if Path(path).is_file():
        load_dotenv(path, override=False)
