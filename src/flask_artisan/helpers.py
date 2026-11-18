from pathlib import Path
from typing import Any

from flask_artisan.application import Application


def app(abstract=None, **params) -> Any:
    application = Application.get_instance()
    return application if abstract is None else application.make(abstract, **params)


def config(key: str | None = None, default: Any = None) -> Any:
    repository = Application.get_instance().make("config")
    return repository if key is None else repository.get(key, default)


def base_path(path: str = "") -> Path:
    return Application.get_instance().base_path(path)
