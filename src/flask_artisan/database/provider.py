from flask_artisan.database.json import ModelJSONProvider
from flask_artisan.database.manager import DatabaseManager
from flask_artisan.database.migrations import COMMANDS, import_models
from flask_artisan.providers import ServiceProvider


class DatabaseServiceProvider(ServiceProvider):
    """Enregistre la base (`"db"`, façade DB) et ferme la session en fin de requête."""

    def register(self):
        manager = DatabaseManager(self.app)
        self.app.instance("db", manager)
        self.app.instance(DatabaseManager, manager)
        self.app.teardown_appcontext(lambda exc: manager.remove())
        # Flask crée son fournisseur JSON dans __init__ : on le remplace ici.
        self.app.json = ModelJSONProvider(self.app)
        for cmd in COMMANDS:
            self.app.cli.add_command(cmd)

    def boot(self):
        # Comme l'autoload de Laravel : toutes les relations par nom trouvent leur modèle.
        if self.app.app_path("models").is_dir():
            import_models(self.app)
