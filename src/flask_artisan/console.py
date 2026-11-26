import importlib
import keyword
import re
import sys
from pathlib import Path
from string import Template

import click
from flask import current_app
from flask.cli import AppGroup, with_appcontext

STUBS = Path(__file__).parent / "stubs"


def class_to_file(name: str) -> str:
    """CamelCase → snake_case, sigles compris : HTTPClient → http_client."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def split_name(name: str, allow_dirs: bool) -> tuple[list[str], str]:
    """ "Admin/UserController" → (["admin"], "UserController")."""
    *dirs, cls = name.split("/")
    if dirs and not allow_dirs:
        raise click.BadParameter(
            f"'{name}' : les sous-dossiers ne sont pas pris en charge ici "
            "(seul le premier niveau du dossier est chargé)."
        )
    for part in [*dirs, cls]:
        # Le nom de fichier (et de fonction pour make:command) ne doit pas être un mot réservé.
        if not part.isidentifier() or any(map(keyword.iskeyword, (part, class_to_file(part)))):
            raise click.BadParameter(
                f"'{name}' : '{part}' ({class_to_file(part)}) n'est pas un nom Python valide."
            )
    if not cls[0].isupper():
        raise click.BadParameter(f"'{name}' : un nom de classe commence par une majuscule.")
    return [class_to_file(d) for d in dirs], cls


def write_stub(
    folder: str, name: str, stub: str, *, force: bool, allow_dirs: bool = True, **values
) -> Path:
    """Écrit `stubs/<stub>.stub` dans `<projet>/<folder>/…/<nom>.py` et renvoie le chemin."""
    dirs, cls = split_name(name, allow_dirs)
    root = current_app.base_path()
    target = root / folder
    for part in dirs:
        shadowed = target / f"{part}.py"
        if shadowed.exists():
            raise click.ClickException(
                f"{shadowed.relative_to(root).as_posix()} existe : un dossier {part}/ le masquerait."
            )
        target = target / part
        target.mkdir(parents=True, exist_ok=True)
        (target / "__init__.py").touch()
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{class_to_file(cls)}.py"
    relative = path.relative_to(root).as_posix()
    if path.is_dir():
        raise click.ClickException(f"{relative} est un dossier, pas un fichier.")
    if path.exists() and not force:
        raise click.ClickException(f"Le fichier {relative} existe déjà (--force pour l'écraser).")
    source = Template((STUBS / f"{stub}.stub").read_text())
    path.write_text(source.substitute(class_name=cls, **values))
    click.echo(f"Créé : {relative}")
    return path


force_option = click.option("--force", is_flag=True, help="Écrase le fichier s'il existe.")


@click.command("make:controller")
@click.argument("name")
@click.option("--resource", is_flag=True, help="Les 7 méthodes de Route.resource.")
@force_option
@with_appcontext
def make_controller(name, resource, force):
    """Crée un controller dans app/http/controllers."""
    stub = "controller.resource" if resource else "controller"
    write_stub("app/http/controllers", name, stub, force=force)


@click.command("make:request")
@click.argument("name")
@force_option
@with_appcontext
def make_request(name, force):
    """Crée une FormRequest dans app/http/requests."""
    write_stub("app/http/requests", name, "request", force=force)


@click.command("make:model")
@click.argument("name")
@force_option
@with_appcontext
def make_model(name, force):
    """Crée un modèle dans app/models."""
    from flask_artisan.database.model import _table_name

    write_stub("app/models", name, "model", force=force, allow_dirs=False)
    click.echo(f'Ajoutez vos colonnes, puis : flask make:migration "create {_table_name(name)}"')


@click.command("make:middleware")
@click.argument("name")
@force_option
@with_appcontext
def make_middleware(name, force):
    """Crée un middleware dans app/http/middleware."""
    path = write_stub("app/http/middleware", name, "middleware", force=force)
    _, cls = split_name(name, allow_dirs=True)
    click.echo(
        f"Déclarez-le dans app/http/kernel.py :\n  {_import_line(path, cls)}\n"
        f'  middleware = {{"{class_to_file(cls)}": {cls}}}'
    )


@click.command("make:provider")
@click.argument("name")
@force_option
@with_appcontext
def make_provider(name, force):
    """Crée un service provider dans app/providers."""
    path = write_stub("app/providers", name, "provider", force=force)
    _, cls = split_name(name, allow_dirs=True)
    click.echo(f'Ajoutez-le à "providers" dans config/app.py :\n  {_import_line(path, cls)}')


@click.command("make:command")
@click.argument("name")
@click.option("--command", "command_name", help="Nom de la commande (défaut : app:<nom>).")
@force_option
@with_appcontext
def make_command(name, command_name, force):
    """Crée une commande du projet dans app/console/commands."""
    _, cls = split_name(name, allow_dirs=False)
    function = class_to_file(cls)
    command_name = command_name or "app:" + function.replace("_", "-")
    write_stub(
        "app/console/commands",
        name,
        "command",
        force=force,
        allow_dirs=False,
        command=command_name,
        function=function,
    )


@click.command("route:list")
@with_appcontext
def route_list():
    """Liste les routes déclarées avec Route : méthodes, URI, nom, action, middlewares."""
    from flask_artisan.routing import Router

    rows = []
    for route, _endpoint, stack in current_app.make(Router).registered:
        cls, target = route.handler
        action = f"{cls.__name__}@{target}" if cls else target.__name__
        middlewares = ", ".join(
            m.__name__ + (":" + ",".join(params) if params else "") for m, params in stack
        )
        name = route.endpoint_name or ""
        rows.append(("|".join(route.methods), route.rule, name, action, middlewares))
    if not rows:
        click.echo("Aucune route déclarée.")
        return
    rows.sort(key=lambda r: (r[1], r[0]))
    rows.insert(0, ("Méthodes", "URI", "Nom", "Action", "Middlewares"))
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for row in rows:
        click.echo("   ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())


def _import_line(path: Path, cls: str) -> str:
    module = ".".join(path.relative_to(current_app.base_path()).with_suffix("").parts)
    return f"from {module} import {cls}"


COMMANDS = [
    make_controller,
    make_model,
    make_middleware,
    make_provider,
    make_command,
    make_request,
    route_list,
]


class ArtisanGroup(AppGroup):
    """Le groupe `app.cli` : commandes du framework, puis celles de app/console/commands.

    Les commandes du projet ne sont importées que lorsque `flask` en a besoin : un fichier
    cassé ne doit pas empêcher l'app web de démarrer.
    """

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self._app = app
        self._discovered = False

    def list_commands(self, ctx):
        self._discover()
        return super().list_commands(ctx)

    def get_command(self, ctx, name):
        # Commandes du framework d'abord : un fichier cassé du projet ne bloque pas make:*.
        command = super().get_command(ctx, name)
        if command is None:
            self._discover()
            command = super().get_command(ctx, name)
        return command

    def _discover(self) -> None:
        if self._discovered:
            return
        folder = self._app.app_path("console/commands")
        if not folder.is_dir():
            return
        root = str(self._app.base_path())
        if root not in sys.path:
            sys.path.insert(0, root)
        for file in sorted(folder.glob("*.py")):
            if file.stem == "__init__":
                continue
            try:
                module = importlib.import_module(f"app.console.commands.{file.stem}")
            except Exception as exc:
                raise click.ClickException(
                    f"Erreur dans app/console/commands/{file.name} : {exc}"
                ) from exc
            for value in vars(module).values():
                # Seulement les commandes définies dans ce fichier, pas celles qu'il importe.
                if not isinstance(value, click.Command):
                    continue
                if getattr(value.callback, "__module__", None) != module.__name__:
                    continue
                # Le module reste en cache : une nouvelle app ne doit pas ré-envelopper.
                if not getattr(value.callback, "_artisan_appcontext", False):
                    value.callback = with_appcontext(value.callback)
                    value.callback._artisan_appcontext = True
                self.add_command(value)
        self._discovered = True  # pas avant : une découverte en échec est retentée
