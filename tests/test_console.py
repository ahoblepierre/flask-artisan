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


def test_make_mail_creates_class_and_template(artisan):
    from flask_artisan.mail import Mailable

    app, run = artisan
    result = run("make:mail", "OrderShipped")
    assert result.exit_code == 0, result.output
    path = app.base_path("app/mail/order_shipped.py")
    cls = load(path).OrderShipped
    assert issubclass(cls, Mailable) and cls.view == "emails/order_shipped.html"
    assert app.base_path("resources/views/emails/order_shipped.html").is_file()
    assert "from app.mail.order_shipped import OrderShipped" in result.output
    assert "Mail.to(" in result.output
    assert_ruff_clean(path)


def test_make_mail_subfolder(artisan):
    app, run = artisan
    assert run("make:mail", "Admin/Invoice").exit_code == 0
    cls = load(app.base_path("app/mail/admin/invoice.py")).Invoice
    assert cls.view == "emails/admin/invoice.html"
    assert app.base_path("resources/views/emails/admin/invoice.html").is_file()


def test_make_mail_existing_template_writes_nothing(artisan):
    app, run = artisan
    tpl = app.base_path("resources/views/emails/order_shipped.html")
    tpl.parent.mkdir(parents=True)
    tpl.write_text("mine")
    result = run("make:mail", "OrderShipped")
    assert result.exit_code != 0
    assert "resources/views/emails/order_shipped.html" in result.output
    assert not app.base_path("app/mail/order_shipped.py").exists()
    assert tpl.read_text() == "mine"


def test_make_mail_existing_class_writes_no_template(artisan):
    app, run = artisan
    assert run("make:mail", "OrderShipped").exit_code == 0
    tpl = app.base_path("resources/views/emails/order_shipped.html")
    tpl.unlink()
    assert run("make:mail", "OrderShipped").exit_code != 0
    assert not tpl.exists()


def test_make_mail_force_overwrites_both(artisan):
    app, run = artisan
    assert run("make:mail", "OrderShipped").exit_code == 0
    py = app.base_path("app/mail/order_shipped.py")
    tpl = app.base_path("resources/views/emails/order_shipped.html")
    py.write_text("x")
    tpl.write_text("x")
    assert run("make:mail", "OrderShipped", "--force").exit_code == 0
    assert py.read_text() != "x" and tpl.read_text() != "x"


def test_make_job(artisan):
    from flask_artisan.queue import Job

    app, run = artisan
    result = run("make:job", "ProcessPodcast")
    assert result.exit_code == 0, result.output
    path = app.base_path("app/jobs/process_podcast.py")
    cls = load(path).ProcessPodcast
    assert issubclass(cls, Job) and callable(cls.handle)
    assert "ProcessPodcast.dispatch(" in result.output
    assert "from app.jobs.process_podcast import ProcessPodcast" in result.output
    assert_ruff_clean(path)


def test_make_job_subfolder(artisan):
    app, run = artisan
    assert run("make:job", "Media/Transcode").exit_code == 0
    assert app.base_path("app/jobs/media/transcode.py").is_file()


def test_make_notification(artisan):
    from flask_artisan.notifications import Notification

    app, run = artisan
    result = run("make:notification", "InvoicePaid")
    assert result.exit_code == 0, result.output
    path = app.base_path("app/notifications/invoice_paid.py")
    cls = load(path).InvoicePaid
    assert issubclass(cls, Notification)
    assert cls().via(None) == ["mail", "database"]
    assert "user.notify(InvoicePaid(" in result.output
    assert_ruff_clean(path)
    assert run("make:notification", "InvoicePaid").exit_code != 0


AUTH_FILES = [
    "routes/auth.py",
    "app/http/controllers/auth/__init__.py",
    "app/http/controllers/auth/registered_user_controller.py",
    "app/http/controllers/auth/password_reset_link_controller.py",
    "app/http/controllers/auth/new_password_controller.py",
    "app/http/controllers/auth/email_verification_controller.py",
    "app/http/requests/register_request.py",
    "app/http/requests/forgot_password_request.py",
    "app/http/requests/reset_password_request.py",
    "resources/views/auth/register.html",
    "resources/views/auth/forgot_password.html",
    "resources/views/auth/reset_password.html",
    "resources/views/auth/verify_email.html",
    "tests/test_auth_flows.py",
]


def test_auth_install_creates_files(artisan):
    app, run = artisan
    result = run("auth:install")
    assert result.exit_code == 0, result.output
    root = app.base_path()
    for name in AUTH_FILES:
        assert (root / name).is_file(), name
        assert f"Créé : {name}" in result.output
    assert not list(root.rglob("*.stub"))
    assert "MustVerifyEmail" in result.output
    assert "flask make:migration" in result.output
    for name in AUTH_FILES:
        if name.endswith(".py"):
            assert_ruff_clean(root / name)


def test_auth_install_conflict_writes_nothing(artisan):
    app, run = artisan
    existing = app.base_path("resources/views/auth/register.html")
    existing.parent.mkdir(parents=True)
    existing.write_text("mine")
    result = run("auth:install")
    assert result.exit_code == 1
    assert "resources/views/auth/register.html" in result.output
    assert existing.read_text() == "mine"
    assert not app.base_path("routes/auth.py").exists()
    assert not app.base_path("tests/test_auth_flows.py").exists()
