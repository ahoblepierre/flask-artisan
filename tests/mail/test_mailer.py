import pytest

from flask_artisan import Mail
from flask_artisan.application import Application
from flask_artisan.mail import Attachment, Mailer

from .mailables import Empty, Hello, HtmlOnly, TextOnly


def test_registered_in_container(mail_app):
    assert mail_app.make("mail") is mail_app.make(Mailer)


def test_send_renders_html_and_text(mail_app):
    Mail.to("Alice <a@x.org>").send(Hello("A"))
    [msg] = Mail.transport("array").messages
    assert msg["Subject"] == "Hi"
    assert msg["From"] == "Shop <shop@x.org>"
    assert msg["To"] == "Alice <a@x.org>"
    assert msg["Message-ID"].endswith("@x.org>") and msg["Date"]
    assert msg.get_body(("plain",)).get_content().strip() == "Hello A"
    assert "<p>Hello A</p>" in msg.get_body(("html",)).get_content()


def test_html_escaped_text_not(mail_app):
    Mail.to("a@x.org").send(Hello("<b>"))
    [msg] = Mail.transport("array").messages
    assert "&lt;b&gt;" in msg.get_body(("html",)).get_content()
    assert "<b>" in msg.get_body(("plain",)).get_content()


def test_html_only_and_text_only(mail_app):
    Mail.to("a@x.org").send(HtmlOnly("A"))
    Mail.to("a@x.org").send(TextOnly("A"))
    html, text = Mail.transport("array").messages
    assert html.get_content_type() == "text/html"
    assert text.get_content_type() == "text/plain"


def test_without_view_or_text_raises(mail_app):
    with pytest.raises(ValueError, match="Empty"):
        Mail.to("a@x.org").send(Empty())


def test_bcc_not_in_headers_but_delivered(mail_app):
    transport = Mail.transport("array")
    Mail.to("a@x.org").cc("c@x.org").bcc("b@x.org").send(Hello("A"))
    msg = transport.messages[0]
    assert "Bcc" not in msg
    assert msg["Cc"] == "c@x.org"
    assert transport.recipients[0] == ["a@x.org", "c@x.org", "b@x.org"]


def test_reply_to_and_attachments(mail_app, tmp_path):
    invoice = tmp_path / "facture.pdf"
    invoice.write_bytes(b"%PDF")

    class WithFiles(Hello):
        reply_to = ("help@x.org", "Support")

        def attachments(self):
            return [Attachment.from_path(invoice), Attachment.from_data(b"a,b", "data.csv")]

    Mail.to("a@x.org").send(WithFiles("A"))
    [msg] = Mail.transport("array").messages
    assert msg["Reply-To"] == "Support <help@x.org>"
    files = [(p.get_filename(), p.get_content_type()) for p in msg.iter_attachments()]
    assert files == [("facture.pdf", "application/pdf"), ("data.csv", "text/csv")]


def test_subject_with_newline_raises_and_sends_nothing(mail_app):
    class Bad(Hello):
        subject = "Hi\nBcc: z@x.org"

    with pytest.raises(ValueError):
        Mail.to("a@x.org").send(Bad("A"))
    assert Mail.transport("array").messages == []


def test_no_recipient_raises(mail_app):
    with pytest.raises(ValueError):
        Mail.to([]).send(Hello("A"))


def test_send_outside_app_context(make_project):
    from .conftest import MAIL_CONFIG

    base = make_project()
    (base / "templates").mkdir()
    (base / "templates" / "t.txt").write_text("{{ config.SECRET_KEY }}")
    (base / "config" / "mail.py").write_text(MAIL_CONFIG)
    app = Application(base)

    class T(Hello):
        view = None
        text = "t.txt"

    app.make(Mailer).to("a@x.org").send(T("A"))
    [msg] = app.make(Mailer).transport("array").messages
    assert msg.get_content().strip() == "test-key"


def test_mailer_by_name_and_unknown(mail_app):
    Mail.mailer("array").to("a@x.org").send(Hello("A"))
    assert len(Mail.transport("array").messages) == 1
    with pytest.raises(ValueError, match="nope"):
        Mail.mailer("nope")


def test_config_read_on_each_send(mail_app):
    mail_app.make("config").set("mail.from.address", "new@x.org")
    Mail.to("a@x.org").send(Hello("A"))
    assert "new@x.org" in Mail.transport("array").messages[0]["From"]


def test_defaults_without_config_file(make_project):
    app = Application(make_project())
    with app.app_context():
        assert app.make("config").get("mail") is None
        assert type(Mail.transport()).__name__ == "LogTransport"


def test_flush(mail_app):
    transport = Mail.transport("array")
    Mail.to("a@x.org").send(Hello("A"))
    transport.flush()
    assert transport.messages == [] and transport.recipients == []


def test_invalid_sender_names_config_key(mail_app):
    mail_app.make("config").set("mail.from.address", "")
    with pytest.raises(ValueError, match="mail.from.address"):
        Mail.to("a@x.org").send(Hello("A"))


def test_subject_available_in_template(mail_app):
    (mail_app.base_path("resources/views/emails/subject.txt")).write_text("[{{ subject }}]")

    class WithSubject(TextOnly):
        text = "emails/subject.txt"

    Mail.to("a@x.org").send(WithSubject("A"))
    assert Mail.transport("array").messages[0].get_content().strip() == "[Hi]"


def test_original_mailable_gets_recipients(mail_app):
    m = Hello("A")
    Mail.to("a@x.org").send(m)
    assert m.has_to("a@x.org")
