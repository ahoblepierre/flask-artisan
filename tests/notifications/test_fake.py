import pytest

from flask_artisan import Mail, Queue
from flask_artisan.mail import Mailable
from flask_artisan.notifications import DatabaseNotification, Notification
from flask_artisan.queue import ShouldQueue

from .models import NUser


class Paid(Mailable):
    subject = "Payé"


class Both(Notification):
    def via(self, notifiable):
        return ["mail", "database"]

    def to_mail(self, notifiable):
        return Paid()

    def to_database(self, notifiable):
        return {}


class QueuedBoth(Both, ShouldQueue):
    pass


class Other(Both):
    pass


def test_fake_records_without_sending(app):
    user = NUser.create(name="A", email="a@x.org")
    other = NUser.create(name="B", email="b@x.org")
    with Mail.fake() as mail, Queue.fake() as queue, Notification.fake() as fake:
        user.notify(Both())
        user.notify(QueuedBoth())
    assert DatabaseNotification.query().count() == 0
    mail.assert_nothing_sent()
    queue.assert_nothing_pushed()
    fake.assert_sent_to(user, Both)
    fake.assert_sent_to(user, QueuedBoth)
    with pytest.raises(AssertionError, match="Both"):
        fake.assert_sent_to(other, Both)
    fake.assert_not_sent_to(other, Both)
    with pytest.raises(AssertionError):
        fake.assert_not_sent_to(user, Both)


def test_fake_matches_reloaded_model(app):
    user = NUser.create(name="A", email="a@x.org")
    with Notification.fake() as fake:
        user.notify(Both())
    fake.assert_sent_to(NUser.find(user.id), Both)


def test_fake_callback_and_times(app):
    users = [NUser.create(name="A"), NUser.create(name="B")]
    with Notification.fake() as fake:
        Notification.send(users, Both())
    fake.assert_sent_to(users[0], Both, lambda n, channels: channels == ["mail", "database"])
    with pytest.raises(AssertionError):
        fake.assert_sent_to(users[0], Both, lambda n, channels: False)
    fake.assert_sent_times(Both, 2)
    with pytest.raises(AssertionError, match="2"):
        fake.assert_sent_times(Both, 3)
    assert len(fake.sent(Both)) == 2


def test_fake_on_demand(app):
    with Notification.fake() as fake:
        Notification.route("mail", "x@y.org").notify(Both())
    fake.assert_sent_on_demand(Both, lambda n, channels: channels == ["mail", "database"])
    with pytest.raises(AssertionError):
        fake.assert_sent_on_demand(Other)


def test_fake_restore(app):
    user = NUser.create(name="A")
    with Notification.fake():
        pass
    with Mail.fake():
        user.notify(Both())
    assert DatabaseNotification.query().count() == 1


def test_assert_nothing_sent(app):
    with Notification.fake() as fake:
        pass
    fake.assert_nothing_sent()
    with Notification.fake() as fake:
        NUser.create(name="A").notify(Both())
    with pytest.raises(AssertionError):
        fake.assert_nothing_sent()
