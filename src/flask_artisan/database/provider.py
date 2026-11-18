from flask_artisan.database.manager import DatabaseManager
from flask_artisan.providers import ServiceProvider


class DatabaseServiceProvider(ServiceProvider):
    """Enregistre la base (`"db"`, façade DB) et ferme la session en fin de requête."""

    def register(self):
        manager = DatabaseManager(self.app)
        self.app.instance("db", manager)
        self.app.instance(DatabaseManager, manager)
        self.app.teardown_appcontext(lambda exc: manager.remove())
