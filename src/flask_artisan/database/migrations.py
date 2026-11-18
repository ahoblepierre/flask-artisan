import importlib
import sys
from pathlib import Path

import click
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from flask import current_app
from flask.cli import with_appcontext

ENV_DIR = Path(__file__).parent / "alembic_env"
FILE_TEMPLATE = "%%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d%%(second).2d_%%(slug)s"


def alembic_config(app) -> Config:
    versions = app.base_path("database/migrations")
    versions.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.set_main_option("script_location", str(ENV_DIR))
    config.set_main_option("path_separator", "os")
    config.set_main_option("version_locations", str(versions))
    config.set_main_option("file_template", FILE_TEMPLATE)
    config.attributes["app"] = app
    return config


def import_models(app) -> None:
    """Importe app/models/*.py pour que l'autogénération connaisse tous les modèles."""
    root = str(app.base_path())
    if root not in sys.path:
        sys.path.insert(0, root)
    for file in sorted(app.app_path("models").glob("*.py")):
        if file.stem != "__init__":
            importlib.import_module(f"app.models.{file.stem}")


def _app():
    return current_app._get_current_object()


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except CommandError as exc:
        raise click.ClickException(str(exc)) from exc


@click.command("make:migration")
@click.argument("message")
@with_appcontext
def make_migration(message: str) -> None:
    """Génère une migration en comparant les modèles à la base."""
    app = _app()
    import_models(app)
    config = alembic_config(app)
    empty = []

    def skip_empty(context, revision, directives):
        if directives[0].upgrade_ops.is_empty():
            directives[:] = []
            empty.append(True)

    config.attributes["process_revision_directives"] = skip_empty
    script = _run(command.revision, config, message=message, autogenerate=True)
    if empty or script is None:
        click.echo("Aucun changement détecté : aucune migration créée.")
        return
    click.echo(f"Migration créée : {Path(script.path).relative_to(app.base_path())}")
    click.echo("Relisez-la : un renommage apparaît comme une suppression suivie d'un ajout.")


@click.command("migrate")
@with_appcontext
def migrate() -> None:
    """Applique les migrations en attente."""
    _run(command.upgrade, alembic_config(_app()), "head")
    click.echo("Migrations appliquées.")


@click.command("migrate:rollback")
@click.option("--step", default=1, show_default=True, help="Nombre de migrations à annuler.")
@with_appcontext
def migrate_rollback(step: int) -> None:
    """Annule les dernières migrations."""
    _run(command.downgrade, alembic_config(_app()), f"-{step}")
    click.echo(f"{step} migration(s) annulée(s).")


@click.command("migrate:status")
@with_appcontext
def migrate_status() -> None:
    """Liste les migrations appliquées [x] et en attente [ ]."""
    app = _app()
    script = ScriptDirectory.from_config(alembic_config(app))
    with app.make("db").engine.connect() as connection:
        heads = MigrationContext.configure(connection).get_current_heads()
    applied = {r.revision for head in heads for r in script.iterate_revisions(head, "base")}
    revisions = list(reversed(list(script.walk_revisions())))
    if not revisions:
        click.echo("Aucune migration.")
    for rev in revisions:
        mark = "x" if rev.revision in applied else " "
        click.echo(f"[{mark}] {Path(rev.path).name}")


COMMANDS = [make_migration, migrate, migrate_rollback, migrate_status]
