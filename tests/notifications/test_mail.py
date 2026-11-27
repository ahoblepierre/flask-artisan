import logging

import pytest

from flask_artisan import Mail
from flask_artisan.database import Mapped, Model
from flask_artisan.mail import Mailable
from flask_artisan.notifications import DatabaseNotification, Notifiable, Notification

from .models import NUser


class Paid(Mailable):
    subject = "Payé"
    text = "emails/paid.txt"


class MailOnly(Notification):
    def via(self, notifiable):
        return ["mail"]

    def to_mail(self, notifiable):
        return Paid()


class Both(MailOnly):
    def via(self, notifiable):
        return ["mail", "database"]

    def to_database(self, notifiable):
        return {"ok": True}


class Boom(Both):
    def to_mail(self, notifiable):
        raise RuntimeError("boom")


class DbOnly(Both):
    def via(self, notifiable):
        return ["database"]


class NNamed(Notifiable, Model):
    name: Mapped[str]
    fillable = ["name"]

    def route_notification_for_mail(self):
        return ("ada@x.org", "Ada")


@pytest.fixture
def mail(app):
    NNamed.metadata.create_all(app.make("db").engine)
    with Mail.fake() as fake:
        yield fake


def test_notify_mail(mail):
    NUser.create(name="A", email="a@x.org").notify(MailOnly())
    mail.assert_sent(Paid, lambda m: m.has_to("a@x.org"))


def test_route_notification_for_mail_override(mail):
    NNamed.create(name="Ada").notify(MailOnly())
    mail.assert_sent(Paid, lambda m: m.has_to("ada@x.org"))


def test_mail_without_route_is_skipped(mail, caplog):
    with caplog.at_level(logging.WARNING):
        NUser.create(name="A", email=None).notify(MailOnly())
    mail.assert_nothing_sent()
    assert "MailOnly" in caplog.text


def test_send_many(mail):
    users = [NUser.create(name="A", email="a@x.org"), NUser.create(name="B", email="b@x.org")]
    Notification.send(users, Both())
    mail.assert_sent_times(Paid, 2)
    assert DatabaseNotification.query().count() == 2


def test_on_demand(mail):
    Notification.route("mail", "x@y.org").notify(MailOnly())
    mail.assert_sent(Paid, lambda m: m.has_to("x@y.org"))
    with pytest.raises(ValueError):
        Notification.route("mail", "x@y.org").notify(DbOnly())


def test_failing_channel_does_not_stop_others(mail):
    users = [NUser.create(name="A", email="a@x.org"), NUser.create(name="B", email="b@x.org")]
    with pytest.raises(RuntimeError, match="boom"):
        Notification.send(users, Boom())
    assert DatabaseNotification.query().count() == 2
