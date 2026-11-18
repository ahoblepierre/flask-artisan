import secrets
import shutil
from pathlib import Path

import click

SKELETON = Path(__file__).parent / "skeleton"


@click.group()
def main():
    """Flask-Artisan : création de projets."""


@main.command()
@click.argument("name")
def new(name: str):
    """Crée un nouveau projet Flask-Artisan dans le dossier NAME."""
    target = Path(name)
    if target.exists() and any(target.iterdir()):
        raise click.ClickException(f"Le dossier '{target}' existe et n'est pas vide.")

    shutil.copytree(
        SKELETON, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__")
    )
    env = (target / ".env.example").read_text()
    env = env.replace("APP_NAME=\n", f"APP_NAME={target.resolve().name}\n", 1)
    env = env.replace("APP_KEY=\n", f"APP_KEY={secrets.token_hex(32)}\n", 1)
    (target / ".env").write_text(env)

    click.echo(f"Projet créé dans {target}.\n\n  cd {name}\n  flask run\n")
