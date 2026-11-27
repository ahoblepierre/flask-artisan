import logging
import math

import pytest

from flask_artisan import Mail
from flask_artisan.database import Mapped, Model
from flask_artisan.mail import Mailable
from flask_artisan.notifications import DatabaseNotification, Notifiable, Notification
from flask_artisan.queue import ShouldQueue

from .models import NUser


class Paid(Mailable):
    subject = "Payé"


class QMail(Notification, ShouldQueue):
    def via(self, notifiable):
        return ["mail"]

    def to_mail(self, notifiable):
        return Paid()


class Db(Notification):
    def __init__(self, data=None):
        self.data = {} if data is None else data

    def via(self, notifiable):
        return ["database"]

    def to_database(self, notifiable):
        return self.data


class QUnserializable(Notification, ShouldQueue):
    def __init__(self):
        self.thing = object()

    def via(self, notifiable):
        return ["database"]


class ViaFails(Notification):
    def via(self, notifiable):
        if notifiable.name == "bad":
            raise RuntimeError("via")
        return ["database"]


def test_queued_on_demand_with_name(app):
    with Mail.fake() as mail:
        Notification.route("mail", ("a@x.org", "Alice")).notify(QMail())
    mail.assert_sent(Paid, lambda m: m.has_to("a@x.org"))


def test_fake_checks_queued_serialization(app):
    with Notification.fake(), pytest.raises(TypeError, match="thing"):
        NUser.create(name="A").notify(QUnserializable())


def test_later_errors_are_logged(app, caplog):
    class BothFail(Notification):
        def via(self, notifiable):
            return ["mail", "database"]

        def to_mail(self, notifiable):
            raise RuntimeError("premier")

        def to_database(self, notifiable):
            raise RuntimeError("second")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="premier"):
        NUser.create(name="A", email="a@x.org").notify(BothFail())
    assert "second" in caplog.text


def test_notifiable_after_model_is_refused():
    with pytest.raises(TypeError, match="Notifiable"):

        class NWrongOrder(Model, Notifiable):
            name: Mapped[str]


def test_column_shadowing_notifiable_is_refused():
    with pytest.raises(TypeError, match="notifications"):

        class NShadow(Notifiable, Model):
            notifications: Mapped[bool]


def test_ties_on_created_at_follow_creation_order(app):
    user = NUser.create(name="A")
    for n in range(5):
        user.notify(Db({"n": n}))
    stamp = DatabaseNotification.query().first().created_at
    for row in DatabaseNotification.query().get():
        row.created_at = stamp
        row.save()
    assert [r.data["n"] for r in user.notifications.get()] == [4, 3, 2, 1, 0]


@pytest.mark.parametrize("data", [["a"], "texte", {"x": math.nan}, {1: "a"}])
def test_to_database_must_be_a_json_dict(app, data):
    with pytest.raises(TypeError):
        NUser.create(name="A").notify(Db(data))
    assert DatabaseNotification.query().count() == 0


def test_send_accepts_builder_set_and_generator(app):
    a, b = NUser.create(name="A"), NUser.create(name="B")
    Notification.send(NUser.where("name", "A"), Db())
    Notification.send({b}, Db())
    Notification.send((u for u in [a]), Db())
    assert a.notifications.count() == 2 and b.notifications.count() == 1


def test_fake_isolates_via_errors(app):
    users = [NUser.create(name="bad"), NUser.create(name="ok")]
    with Notification.fake() as fake, pytest.raises(RuntimeError, match="via"):
        Notification.send(users, ViaFails())
    fake.assert_sent_to(users[1], ViaFails)
