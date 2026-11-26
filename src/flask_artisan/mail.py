"""Mail façon Laravel : `Mailable`, `Mail.to(user).send(...)`, transports, `Mail.fake()`."""

import copy
import mimetypes
import smtplib
from collections import Counter
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Any

from flask import current_app, has_app_context, render_template

__all__ = ["Attachment", "MailFake", "Mailable", "Mailer"]

DEFAULT_MAILERS = {
    "smtp": {"transport": "smtp", "host": "127.0.0.1", "port": 2525},
    "log": {"transport": "log"},
    "array": {"transport": "array"},
}


def _check_line(value: str, what: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError(f"Saut de ligne interdit dans {what} : {value!r}.")
    return value


def _address(value) -> tuple[str, str]:
    if isinstance(value, str):
        _check_line(value, "une adresse")
        name, address = parseaddr(value)
    elif isinstance(value, tuple) and len(value) == 2:
        address, name = value
    elif hasattr(value, "email"):
        address, name = value.email, getattr(value, "name", None)
    else:
        raise TypeError(
            f"Destinataire invalide : {value!r} (attendu : une adresse, (adresse, nom) "
            "ou un objet avec un attribut email)."
        )
    if not isinstance(address, str) or "@" not in address:
        raise ValueError(f"Adresse mail invalide : {address!r}.")
    name = str(name or "")
    return _check_line(name, "un nom"), _check_line(address, "une adresse")


def _addresses(value) -> list[tuple[str, str]]:
    """Normalise une ou plusieurs adresses en (nom, adresse)."""
    if isinstance(value, list):
        return [_address(item) for item in value]
    return [_address(value)]


class Attachment:
    """Une pièce jointe : `Attachment.from_path(...)` ou `Attachment.from_data(...)`."""

    def __init__(self, name: str, mime: str | None, reader):
        self.name = name
        self.mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._reader = reader

    @classmethod
    def from_path(cls, path, name: str | None = None, mime: str | None = None) -> "Attachment":
        path = Path(path)
        return cls(name or path.name, mime, path.read_bytes)

    @classmethod
    def from_data(cls, data: bytes | str, name: str, mime: str | None = None) -> "Attachment":
        raw = data.encode() if isinstance(data, str) else data
        return cls(name, mime, lambda: raw)

    def read(self) -> bytes:
        return self._reader()


class Mailable:
    """Un mail : sujet, template HTML (`view`) et/ou texte (`text`), pièces jointes."""

    subject: str = ""
    view: str | None = None
    text: str | None = None
    reply_to: Any = None

    def context(self) -> dict:
        """Variables des templates : les attributs publics de l'instance."""
        return {k: v for k, v in vars(self).items() if not k.startswith("_")}

    def attachments(self) -> list:
        return []

    def _has(self, kind: str, value) -> bool:
        wanted = {address.lower() for _, address in _addresses(value)}
        sent = {address.lower() for address in getattr(self, "_recipients", {}).get(kind, [])}
        return bool(wanted) and wanted <= sent

    def has_to(self, value) -> bool:
        return self._has("to", value)

    def has_cc(self, value) -> bool:
        return self._has("cc", value)

    def has_bcc(self, value) -> bool:
        return self._has("bcc", value)


class ArrayTransport:
    """Garde les messages en mémoire (tests)."""

    def __init__(self):
        self.messages: list[EmailMessage] = []
        self.recipients: list[list[str]] = []

    def send(self, message: EmailMessage, recipients: list[str]) -> None:
        self.messages.append(message)
        self.recipients.append(recipients)

    def flush(self) -> None:
        self.messages.clear()
        self.recipients.clear()


class LogTransport:
    """Écrit le mail dans les logs de l'application (développement)."""

    def __init__(self, logger):
        self.logger = logger

    def send(self, message: EmailMessage, recipients: list[str]) -> None:
        self.logger.info("Mail pour %s :\n%s", ", ".join(recipients), message.as_string())


class SmtpTransport:
    """Une connexion SMTP par envoi ; les erreurs de smtplib remontent telles quelles."""

    def __init__(self, host, port, username=None, password=None, encryption=None, timeout=10, **_):
        if encryption not in (None, "", "tls", "ssl"):
            raise ValueError(f"MAIL_ENCRYPTION inconnu : {encryption!r} (tls, ssl ou vide).")
        self.host, self.port, self.timeout = host, int(port), timeout
        self.username, self.password = username, password
        self.encryption = encryption or None

    def send(self, message: EmailMessage, recipients: list[str]) -> None:
        connect = smtplib.SMTP_SSL if self.encryption == "ssl" else smtplib.SMTP
        with connect(self.host, self.port, timeout=self.timeout) as smtp:
            if self.encryption == "tls":
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(message, to_addrs=recipients)


class PendingMail:
    """`Mail.to(...).cc(...).bcc(...).send(mailable)`."""

    def __init__(self, mailer: "Mailer", name: str | None = None):
        self._mailer = mailer
        self._name = name
        self._envelope: dict[str, list] = {"to": [], "cc": [], "bcc": []}

    def _add(self, kind: str, recipients) -> "PendingMail":
        for value in recipients:
            self._envelope[kind].extend(_addresses(value))
        return self

    def to(self, *recipients) -> "PendingMail":
        return self._add("to", recipients)

    def cc(self, *recipients) -> "PendingMail":
        return self._add("cc", recipients)

    def bcc(self, *recipients) -> "PendingMail":
        return self._add("bcc", recipients)

    def send(self, mailable: Mailable) -> None:
        if not self._envelope["to"]:
            raise ValueError(f"{type(mailable).__name__} : aucun destinataire (Mail.to(...)).")
        self._mailer._send(self._name, self._envelope, mailable)


class Mailer:
    """Le service `"mail"` (façade `Mail`). La config est relue à chaque envoi."""

    def __init__(self, app):
        self._app = app
        self._arrays: dict[str, ArrayTransport] = {}  # seuls les `array` gardent un état
        # Mode fake : un état du mailer, pour que les services qui le tiennent déjà le voient.
        self._faking = False
        self._recorded: list = []

    def _config(self, key: str, default=None):
        return self._app.make("config").get(f"mail.{key}", default)

    def _mailer_config(self, name: str | None) -> tuple[str, dict]:
        name = name or self._config("default", "log")
        mailers = self._config("mailers", DEFAULT_MAILERS)
        if name not in mailers:
            raise ValueError(f"Mailer inconnu : {name!r} (config mail.mailers).")
        return name, mailers[name]

    def to(self, *recipients) -> PendingMail:
        return PendingMail(self).to(*recipients)

    def mailer(self, name: str) -> PendingMail:
        self._mailer_config(name)
        return PendingMail(self, name)

    def transport(self, name: str | None = None):
        name, options = self._mailer_config(name)
        kind = options.get("transport")
        if kind == "array":
            return self._arrays.setdefault(name, ArrayTransport())
        if kind == "log":
            return LogTransport(self._app.logger)
        if kind == "smtp":
            return SmtpTransport(**{"host": "127.0.0.1", "port": 2525, **options})
        raise ValueError(f"Transport de mail inconnu : {kind!r} (mailer {name!r}).")

    def fake(self) -> "MailFake":
        """Enregistre les mails envoyés, sans les rendre ni les envoyer."""
        self._faking = True
        self._recorded = []
        return MailFake(self, self._recorded)

    def _send(self, name: str | None, envelope: dict, mailable: Mailable) -> None:
        if self._faking:
            name, _ = self._mailer_config(name)
            record = copy.copy(mailable)  # un même objet envoyé deux fois garde ses envois
            record._recipients = {k: [a for _, a in v] for k, v in envelope.items()}
            record._mailer = name
            self._recorded.append(record)
            return
        transport = self.transport(name)
        message = self._build(mailable, envelope)
        mailable._recipients = {k: [a for _, a in v] for k, v in envelope.items()}
        recipients = [a for kind in ("to", "cc", "bcc") for _, a in envelope[kind]]
        transport.send(message, recipients)

    def _render(self, template: str, context: dict) -> str:
        if has_app_context() and current_app._get_current_object() is self._app:
            return render_template(template, **context)
        with self._app.app_context():
            return render_template(template, **context)

    def _build(self, mailable: Mailable, envelope: dict) -> EmailMessage:
        cls = type(mailable).__name__
        if not mailable.view and not mailable.text:
            raise ValueError(f"{cls} : définissez `view` (HTML) et/ou `text`.")
        subject = _check_line(str(mailable.subject or ""), "le sujet")
        sender = _address(
            (
                self._config("from.address", "hello@example.com"),
                self._config(
                    "from.name", self._app.make("config").get("app.name") or "Flask-Artisan"
                ),
            )
        )
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr(sender)
        message["To"] = ", ".join(formataddr(a) for a in envelope["to"])
        if envelope["cc"]:
            message["Cc"] = ", ".join(formataddr(a) for a in envelope["cc"])
        if mailable.reply_to:
            message["Reply-To"] = ", ".join(formataddr(a) for a in _addresses(mailable.reply_to))
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=sender[1].rsplit("@", 1)[1])

        context = mailable.context()
        text = self._render(mailable.text, context) if mailable.text else None
        html = self._render(mailable.view, context) if mailable.view else None
        if text is not None:
            message.set_content(text)
            if html is not None:
                message.add_alternative(html, subtype="html")
        else:
            message.set_content(html, subtype="html")
        for attachment in mailable.attachments():
            maintype, subtype = attachment.mime.split("/", 1)
            message.add_attachment(
                attachment.read(), maintype=maintype, subtype=subtype, filename=attachment.name
            )
        return message


class MailFake:
    """Assertions sur les mails envoyés depuis `Mail.fake()`."""

    def __init__(self, mailer: Mailer, recorded: list):
        self._mailer = mailer
        self._recorded = recorded

    def restore(self) -> None:
        """Rend au mailer son fonctionnement normal ; les enregistrements restent lisibles."""
        if self._mailer._recorded is self._recorded:  # pas remplacé par un fake() plus récent
            self._mailer._faking = False

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.restore()

    def sent(self, mailable_class: type) -> list:
        return [m for m in self._recorded if isinstance(m, mailable_class)]

    def _matching(self, mailable_class: type, callback) -> list:
        mails = self.sent(mailable_class)
        return mails if callback is None else [m for m in mails if callback(m)]

    def assert_sent(self, mailable_class: type, callback=None) -> None:
        if not self._matching(mailable_class, callback):
            detail = " correspondant au callback" if callback else ""
            raise AssertionError(
                f"Mail {mailable_class.__name__}{detail} envoyé 0 fois, attendu au moins 1."
            )

    def assert_sent_times(self, mailable_class: type, times: int) -> None:
        count = len(self.sent(mailable_class))
        if count != times:
            raise AssertionError(
                f"Mail {mailable_class.__name__} envoyé {count} fois, attendu {times}."
            )

    def assert_not_sent(self, mailable_class: type, callback=None) -> None:
        count = len(self._matching(mailable_class, callback))
        if count:
            raise AssertionError(
                f"Mail {mailable_class.__name__} envoyé {count} fois, attendu aucun envoi."
            )

    def assert_nothing_sent(self) -> None:
        counts = Counter(type(m).__name__ for m in self._recorded)
        if counts:
            sent = ", ".join(f"{name} envoyé {n} fois" for name, n in counts.items())
            raise AssertionError(f"Aucun mail attendu, mais : {sent}.")
