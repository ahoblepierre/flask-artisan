import json

import pytest

from flask_artisan import Mail, Queue
from flask_artisan.mail import Mailable
from flask_artisan.notifications import DatabaseNotification, Notification
from flask_artisan.notifications.sender import SendQueuedNotification
from flask_artisan.queue import Job, ShouldQueue
from flask_artisan.queue.serialization import class_path, restore, serialize

from .models import NTeam, NUser


class Paid(Mailable):
    subject = "Payé"
    text = "emails/paid.txt"


class Queued(Notification, ShouldQueue):
    queue = "notifs"
    tries = 3

    def __init__(self, team=None):
        self.team = team

    def via(self, notifiable):
        return ["mail", "database"]

    def to_mail(self, notifiable):
        return Paid()

    def to_database(self, notifiable):
        return {"team": self.team.name if self.team else None}


class QueuedBoom(Queued):
    def to_mail(self, notifiable):
        raise RuntimeError("boom")


def test_queued_one_job_per_channel_and_notifiable(app):
    users = [NUser.create(name="A", email="a@x.org"), NUser.create(name="B", email="b@x.org")]
    with Queue.fake() as fake:
        Notification.send(users, Queued())
    jobs = fake.pushed(SendQueuedNotification)
    assert len(jobs) == 4
    assert {job.channel for job in jobs} == {"mail", "database"}
    assert all(job.queue_name == "notifs" and job.tries == 3 for job in jobs)


def test_queued_sync_runs(app):
    with Mail.fake() as mail:
        NUser.create(name="A", email="a@x.org").notify(Queued())
    mail.assert_sent(Paid)
    assert DatabaseNotification.query().count() == 1


def test_queued_round_trip_json(app):
    user = NUser.create(name="A", email="a@x.org")
    team = NTeam.create(name="Core")
    job = SendQueuedNotification.wrap(Queued(team), user, "database")
    payload = json.loads(json.dumps(serialize(job)))
    assert payload["data"]["notifiable"] == {
        "__model__": class_path(NUser),
        "id": user.id,
    }
    rebuilt = restore(payload, Job)
    app.call(rebuilt.handle)
    assert user.notifications.first().data == {"team": "Core"}


def test_queued_sync_failure_does_not_stop_others(app):
    users = [NUser.create(name="A", email="a@x.org"), NUser.create(name="B", email="b@x.org")]
    with Mail.fake(), pytest.raises(RuntimeError, match="boom"):
        Notification.send(users, QueuedBoom())
    assert DatabaseNotification.query().count() == 2


def test_queued_payload_rejects_private_and_foreign_class(app):
    user = NUser.create(name="A", email="a@x.org")
    job = SendQueuedNotification.wrap(Queued(), user, "database")
    job.notification_data = {"_secret": 1}
    with pytest.raises(TypeError):
        app.call(job.handle)
    job = SendQueuedNotification.wrap(Queued(), user, "database")
    job.notification_class = "collections.OrderedDict"
    with pytest.raises(TypeError):
        app.call(job.handle)
    job = SendQueuedNotification.wrap(Queued(), user, "database")
    job.channel = "sms"
    with pytest.raises(TypeError):
        app.call(job.handle)


def test_queued_on_demand(app):
    with Mail.fake() as mail:
        Notification.route("mail", "x@y.org").notify(OnDemandMail())
    mail.assert_sent(Paid, lambda m: m.has_to("x@y.org"))


class OnDemandMail(Queued):
    def via(self, notifiable):
        return ["mail"]
