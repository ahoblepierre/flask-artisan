import pytest

from flask_artisan import Mail, Queue
from flask_artisan.queue.jobs import SendQueuedMailable

from .mailables import Hello


class Queued(Hello):
    queue = "mails"


def test_queue_sync_sends_now(mail_app):
    assert Mail.to("a@x.org").queue(Hello("A")) is None
    [msg] = Mail.transport("array").messages
    assert "Hello A" in msg.get_body(("plain",)).get_content()


def test_queue_pushes_job_under_queue_fake(mail_app):
    with Queue.fake() as fake:
        Mail.to("Alice <a@x.org>").bcc("b@x.org").queue(Hello("A"))
    fake.assert_pushed(SendQueuedMailable)
    [job] = fake.pushed(SendQueuedMailable)
    assert job.mailable_class.endswith("Hello") and job.mailable_data == {"name": "A"}
    assert job.envelope["to"] == [["Alice", "a@x.org"]] and job.envelope["bcc"] == [["", "b@x.org"]]
    assert Mail.transport("array").messages == []


def test_later_sets_delay(mail_app):
    with Queue.fake() as fake:
        Mail.to("a@x.org").later(30, Hello("A"))
    assert fake.pushed(SendQueuedMailable)[0].delay_seconds == 30


def test_mailable_queue_attribute(mail_app):
    with Queue.fake() as fake:
        Mail.to("a@x.org").queue(Queued("A"))
    fake.assert_pushed_on("mails", SendQueuedMailable)


def test_named_mailer_kept(mail_app):
    with Queue.fake() as fake:
        Mail.mailer("log").to("a@x.org").queue(Hello("A"))
    assert fake.pushed(SendQueuedMailable)[0].mailer == "log"


def test_recipients_validated_at_queue_time(mail_app):
    with pytest.raises(ValueError):
        Mail.to("nobody").queue(Hello("A"))
    with pytest.raises(ValueError):
        Mail.to([]).queue(Hello("A"))


def test_mail_fake_records_queued_separately(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").queue(Hello("A"))
    fake.assert_queued(Hello, lambda m: m.has_to("a@x.org") and m.name == "A")
    fake.assert_not_sent(Hello)
    fake.assert_nothing_sent()
    assert len(fake.queued(Hello)) == 1
    with pytest.raises(AssertionError, match="Hello mis en file 1 fois"):
        fake.assert_not_queued(Hello)
    with pytest.raises(AssertionError, match="Hello"):
        fake.assert_nothing_queued()
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(Hello("A"))
    fake.assert_sent(Hello)
    fake.assert_nothing_queued()
    with pytest.raises(AssertionError, match="Hello mis en file 0 fois"):
        fake.assert_queued(Hello)


def test_forged_mailable_class_rejected(mail_app):
    job = SendQueuedMailable.__new__(SendQueuedMailable)
    job.mailable_class, job.mailable_data = "os.path", {}
    job.envelope, job.mailer = {"to": [["", "a@x.org"]], "cc": [], "bcc": []}, None
    with pytest.raises(TypeError):
        mail_app.call(job.handle)


def test_worker_sends_queued_mail(mail_app, monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    from rq import Queue as RqQueue
    from rq import SimpleWorker
    from rq.serializers import JSONSerializer

    redis = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    monkeypatch.setattr("flask_artisan.queue.worker.connect", lambda url: redis)
    config = mail_app.make("config")
    config.set("queue.default", "redis")
    config.set("queue.connections", {"redis": {"driver": "rq", "url": "redis://x"}})
    Mail.to("a@x.org").queue(Hello("A"))
    assert Mail.transport("array").messages == []
    queue = RqQueue("default", connection=redis, serializer=JSONSerializer)
    SimpleWorker([queue], connection=redis, serializer=JSONSerializer).work(burst=True)
    [msg] = Mail.transport("array").messages
    assert msg["To"] == "a@x.org" and "Hello A" in msg.get_body(("plain",)).get_content()


def test_mail_fake_still_serializes_queued_mail(mail_app):
    bad = Hello("A")
    bad.handle = object()
    with Mail.fake() as fake, pytest.raises(TypeError, match="handle"):
        Mail.to("a@x.org").queue(bad)
    fake.assert_nothing_queued()
