import subprocess
import sys

import pytest

from flask_artisan.notifications import DatabaseNotification, Notification
from flask_artisan.queue.serialization import class_path

from .models import NTeam, NUser


class Stored(Notification):
    def __init__(self, n=1):
        self.n = n

    def via(self, notifiable):
        return ["database"]

    def to_database(self, notifiable):
        return {"n": self.n}


class Sms(Notification):
    def via(self, notifiable):
        return ["sms"]


class NoMethod(Notification):
    def via(self, notifiable):
        return ["database"]


def test_application_does_not_import_notifications(make_project):
    root = make_project()
    code = (
        "import sys\nfrom flask_artisan import Application\n"
        f"Application({str(root)!r})\n"
        "print('flask_artisan.notifications.models' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_notify_database(app):
    user = NUser.create(name="Ada", email="a@x.org")
    user.notify(Stored())
    assert user.notifications.count() == 1
    row = user.notifications.first()
    assert row.type == class_path(Stored)
    assert row.notifiable_type == class_path(NUser) and row.notifiable_id == user.id
    assert row.data == {"n": 1} and row.read_at is None and len(row.id) == 36


def test_polymorphic(app):
    user = NUser.create(name="Ada")
    team = NTeam.create(name="Core")
    assert user.id == team.id
    user.notify(Stored(1))
    team.notify(Stored(2))
    assert [n.data["n"] for n in user.notifications.get()] == [1]
    assert [n.data["n"] for n in team.notifications.get()] == [2]


def test_unread_and_mark(app):
    user = NUser.create(name="Ada")
    user.notify(Stored(1))
    user.notify(Stored(2))
    latest = user.notifications.first()
    assert latest.data["n"] == 2
    latest.mark_as_read()
    assert latest.read() and not latest.unread()
    assert user.unread_notifications.count() == 1
    latest.mark_as_unread()
    assert latest.read_at is None and user.unread_notifications.count() == 2


def test_database_data_must_be_json(app):
    user = NUser.create(name="Ada")

    class Bad(Stored):
        def to_database(self, notifiable):
            return {"u": notifiable}

    with pytest.raises(TypeError, match="Bad"):
        user.notify(Bad())
    assert DatabaseNotification.query().count() == 0


def test_unknown_channel(app):
    with pytest.raises(ValueError, match="sms"):
        NUser.create(name="Ada").notify(Sms())


def test_missing_to_method(app):
    with pytest.raises(NotImplementedError, match="to_database"):
        NUser.create(name="Ada").notify(NoMethod())


def test_hard_delete_removes_only_own_notifications(app):
    user = NUser.create(name="Ada")
    team = NTeam.create(name="Core")
    user.notify(Stored())
    team.notify(Stored())
    user.delete()
    assert DatabaseNotification.query().count() == 1
    assert team.notifications.count() == 1
