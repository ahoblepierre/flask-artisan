from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask_artisan.application import Application


class ServiceProvider:
    """`register()` déclare des bindings ; `boot()` fait tout le reste (init_app d'extensions…)."""

    def __init__(self, app: Application):
        self.app = app

    def register(self) -> None:
        pass

    def boot(self) -> None:
        pass
