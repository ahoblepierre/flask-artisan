import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from flask_artisan.application import Application
from flask_artisan.console import class_to_file

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def artisan(make_project):
    app = Application(make_project())

    def run(*args):
        return app.test_cli_runner().invoke(args=list(args))

    return app, run


def load(path: Path, name: str = "generated"):
    spec = importlib.util.spec_from_file_location(f"{name}_{abs(hash(path))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_ruff_clean(path: Path):
    for args in (["check"], ["format", "--check"]):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", *args, "--config", str(REPO / "pyproject.toml"), path],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("UserController", "user_controller"),
        ("HTTPClient", "http_client"),
        ("EnsureJSONBody", "ensure_json_body"),
    ],
)
def test_class_to_file(name, expected):
    assert class_to_file(name) == expected


def test_make_controller_creates_importable_class(artisan):
    app, run = artisan
    result = run("make:controller", "PhotoController")
    assert result.exit_code == 0, result.output
    assert "Créé : app/http/controllers/photo_controller.py" in result.output
    module = load(app.base_path("app/http/controllers/photo_controller.py"))
    assert callable(module.PhotoController().index)


def test_make_controller_resource_has_seven_methods(artisan):
    app, run = artisan
    assert run("make:controller", "PhotoController", "--resource").exit_code == 0
    cls = load(app.base_path("app/http/controllers/photo_controller.py")).PhotoController
    for method in ("index", "create", "store", "show", "edit", "update", "destroy"):
        assert callable(getattr(cls, method)), method
    assert "id" in inspect.signature(cls.show).parameters


def test_make_controller_subfolder(artisan):
    app, run = artisan
    assert run("make:controller", "Admin/UserController").exit_code == 0
    folder = app.base_path("app/http/controllers/admin")
    assert (folder / "__init__.py").exists()
    assert hasattr(load(folder / "user_controller.py"), "UserController")


def test_existing_file_needs_force(artisan):
    app, run = artisan
    path = app.base_path("app/http/controllers/photo_controller.py")
    assert run("make:controller", "PhotoController").exit_code == 0
    path.write_text("# modifié\n")
    result = run("make:controller", "PhotoController")
    assert result.exit_code != 0
    assert "existe déjà" in result.output
    assert path.read_text() == "# modifié\n"
    assert run("make:controller", "PhotoController", "--force").exit_code == 0
    assert "class PhotoController" in path.read_text()


@pytest.mark.parametrize("name", ["", "1Foo", "Foo-Bar", "Admin/", "../Evil", "photo"])
def test_invalid_names_rejected(artisan, name):
    app, run = artisan
    result = run("make:controller", name)
    assert result.exit_code != 0
    created = [p for p in app.base_path().rglob("*") if "config" not in p.parts]
    assert not [p for p in created if p.is_file()], created
    assert not app.base_path().parent.joinpath("evil.py").exists()


@pytest.mark.parametrize("extra", [[], ["--resource"]])
def test_generated_controller_passes_ruff(artisan, extra):
    app, run = artisan
    assert run("make:controller", "PhotoController", *extra).exit_code == 0
    assert_ruff_clean(app.base_path("app/http/controllers/photo_controller.py"))
