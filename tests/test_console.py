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


@pytest.mark.parametrize(
    "name", ["", "1Foo", "Foo-Bar", "Admin/", "../Evil", "photo", "None", "True", "class/Foo"]
)
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


def test_make_model(artisan):
    from flask_artisan.database import Model

    app, run = artisan
    result = run("make:model", "ConsolePost")
    assert result.exit_code == 0, result.output
    module = load(app.base_path("app/models/console_post.py"))
    assert issubclass(module.ConsolePost, Model)
    assert 'flask make:migration "create console_posts"' in result.output
    assert not app.base_path("database/migrations").exists()


def test_make_middleware(artisan):
    app, run = artisan
    result = run("make:middleware", "BeforeMiddleware")
    assert result.exit_code == 0, result.output
    cls = load(app.base_path("app/http/middleware/before_middleware.py")).BeforeMiddleware
    assert cls().handle(object(), lambda r: "ok") == "ok"
    assert '"before_middleware": BeforeMiddleware' in result.output


def test_make_provider(artisan):
    from flask_artisan import ServiceProvider

    app, run = artisan
    result = run("make:provider", "PaymentServiceProvider")
    assert result.exit_code == 0, result.output
    module = load(app.base_path("app/providers/payment_service_provider.py"))
    assert issubclass(module.PaymentServiceProvider, ServiceProvider)
    assert "from app.providers.payment_service_provider import PaymentServiceProvider" in (
        result.output
    )


@pytest.mark.parametrize(
    ("name", "stem", "command"),
    [("SendEmails", "send_emails", "app:send-emails"), ("HTTPPing", "http_ping", "app:http-ping")],
)
def test_make_command_default_name(artisan, name, stem, command):
    import click

    app, run = artisan
    assert run("make:command", name).exit_code == 0
    cmd = getattr(load(app.base_path(f"app/console/commands/{stem}.py")), stem)
    assert isinstance(cmd, click.Command)
    assert cmd.name == command


def test_make_command_custom_name(artisan):
    app, run = artisan
    assert run("make:command", "SendEmails", "--command", "mail:send").exit_code == 0
    cmd = load(app.base_path("app/console/commands/send_emails.py")).send_emails
    assert cmd.name == "mail:send"


@pytest.mark.parametrize("command", ["make:model", "make:command"])
def test_model_and_command_refuse_subfolders(artisan, command):
    _, run = artisan
    result = run(command, "Billing/Invoice")
    assert result.exit_code != 0
    assert "sous-dossier" in result.output


@pytest.mark.parametrize(
    ("command", "name", "path"),
    [
        ("make:model", "Invoice", "app/models/invoice.py"),
        ("make:middleware", "EnsureJson", "app/http/middleware/ensure_json.py"),
        ("make:provider", "PaymentServiceProvider", "app/providers/payment_service_provider.py"),
        ("make:command", "SendEmails", "app/console/commands/send_emails.py"),
    ],
)
def test_generated_files_pass_ruff(artisan, command, name, path):
    app, run = artisan
    assert run(command, name).exit_code == 0
    assert_ruff_clean(app.base_path(path))


def test_make_command_rejects_keyword_function_name(artisan):
    app, run = artisan
    result = run("make:command", "Import")
    assert result.exit_code != 0
    assert "import" in result.output
    assert not app.base_path("app/console/commands/import.py").exists()


def test_subfolder_cannot_shadow_existing_module(artisan):
    app, run = artisan
    folder = app.base_path("app/http/controllers")
    folder.mkdir(parents=True)
    (folder / "admin.py").write_text("X = 1\n")
    result = run("make:controller", "Admin/UserController")
    assert result.exit_code != 0
    assert "admin.py" in result.output
    assert not (folder / "admin").exists()


def test_force_on_directory_is_a_clean_error(artisan):
    app, run = artisan
    app.base_path("app/http/controllers/photo_controller.py").mkdir(parents=True)
    result = run("make:controller", "PhotoController", "--force")
    assert result.exit_code == 1
    assert "dossier" in result.output
    assert not isinstance(result.exception, IsADirectoryError)


def test_make_request(artisan):
    from flask_artisan.validation import FormRequest

    app, run = artisan
    result = run("make:request", "StorePostRequest")
    assert result.exit_code == 0, result.output
    path = app.base_path("app/http/requests/store_post_request.py")
    assert issubclass(load(path).StorePostRequest, FormRequest)
    assert_ruff_clean(path)


def test_make_event(artisan):
    import dataclasses

    app, run = artisan
    assert run("make:event", "OrderShipped").exit_code == 0
    path = app.base_path("app/events/order_shipped.py")
    assert dataclasses.is_dataclass(load(path).OrderShipped)
    assert_ruff_clean(path)


def test_make_listener_without_event(artisan):
    app, run = artisan
    result = run("make:listener", "SendShipmentNotification")
    assert result.exit_code == 0, result.output
    assert "event_service_provider.py" in result.output
    path = app.base_path("app/listeners/send_shipment_notification.py")
    assert callable(load(path).SendShipmentNotification().handle)
    assert_ruff_clean(path)


def test_make_listener_with_event_in_subfolder(artisan):
    app, run = artisan
    assert run("make:event", "Billing/InvoicePaid").exit_code == 0
    assert run("make:listener", "MarkPaid", "--event", "Billing/InvoicePaid").exit_code == 0
    path = app.base_path("app/listeners/mark_paid.py")
    source = path.read_text()
    assert "from app.events.billing.invoice_paid import InvoicePaid" in source
    assert "event: InvoicePaid" in source
    assert_ruff_clean(path)


def test_make_listener_with_missing_event_writes_nothing(artisan):
    app, run = artisan
    result = run("make:listener", "MarkPaid", "--event", "Typo")
    assert result.exit_code != 0
    assert "app/events/typo.py" in result.output
    assert not app.base_path("app/listeners/mark_paid.py").exists()


def test_make_listener_with_event_prints_listen_line(artisan):
    _, run = artisan
    assert run("make:event", "InvoicePaid").exit_code == 0
    result = run("make:listener", "MarkPaid", "--event", "InvoicePaid")
    assert "from app.listeners.mark_paid import MarkPaid" in result.output
    assert "from app.events.invoice_paid import InvoicePaid" in result.output
    assert "InvoicePaid: [MarkPaid]" in result.output
