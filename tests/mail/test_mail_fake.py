import pytest

from flask_artisan import Mail
from flask_artisan.mail import Mailer, MailFake

from .mailables import Empty, Hello


class Welcome(Hello):
    pass


def test_fake_records_without_rendering_or_sending(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(Empty())  # Empty ne se rend pas : aucune erreur sous fake
    assert isinstance(fake, MailFake)
    fake.assert_sent(Empty)
    assert Mail.transport("array").messages == []


def test_assert_sent_with_callback_and_recipients(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").cc("c@x.org").bcc("b@x.org").send(Hello("A"))
    fake.assert_sent(
        Hello,
        lambda m: m.name == "A" and m.has_to("A@X.org") and m.has_cc("c@x.org"),
    )
    assert fake.sent(Hello)[0].has_bcc("b@x.org")
    with pytest.raises(AssertionError, match="Hello"):
        fake.assert_sent(Hello, lambda m: m.has_to("z@x.org"))


def test_same_instance_two_recipients(mail_app):
    m = Hello("A")
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(m)
        Mail.to("b@x.org").send(m)
    first, second = fake.sent(Hello)
    assert first.has_to("a@x.org") and not first.has_to("b@x.org")
    assert second.has_to("b@x.org")


def test_assert_sent_times(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(Hello("A"))
        Mail.to("b@x.org").send(Hello("B"))
    fake.assert_sent_times(Hello, 2)
    with pytest.raises(AssertionError, match="Hello envoyé 2 fois, attendu 1"):
        fake.assert_sent_times(Hello, 1)


def test_assert_not_sent(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(Hello("A"))
    fake.assert_not_sent(Empty)
    fake.assert_not_sent(Hello, lambda m: m.name == "Z")
    with pytest.raises(AssertionError, match="Hello envoyé 1 fois"):
        fake.assert_not_sent(Hello)


def test_assert_nothing_sent(mail_app):
    with Mail.fake() as fake:
        fake.assert_nothing_sent()
        Mail.to("a@x.org").send(Hello("A"))
    with pytest.raises(AssertionError, match="Hello envoyé 1 fois"):
        fake.assert_nothing_sent()


def test_subclass_counts(mail_app):
    with Mail.fake() as fake:
        Mail.to("a@x.org").send(Welcome("A"))
    fake.assert_sent(Hello)
    fake.assert_not_sent(Empty)


def test_mailer_name_recorded(mail_app):
    with Mail.fake() as fake:
        Mail.mailer("log").to("a@x.org").send(Hello("A"))
    assert fake.sent(Hello)[0]._mailer == "log"


def test_invalid_recipient_still_raises(mail_app):
    with Mail.fake(), pytest.raises(ValueError):
        Mail.to("nobody").send(Hello("A"))


def test_injected_mailer_is_faked(mail_app):
    held = mail_app.make(Mailer)
    with Mail.fake() as fake:
        held.to("a@x.org").send(Hello("A"))
    fake.assert_sent(Hello)
    assert Mail.transport("array").messages == []


def test_restore_and_superseded_fake(mail_app):
    old = Mail.fake()
    new = Mail.fake()
    old.restore()  # remplacé : ne touche pas au fake récent
    Mail.to("a@x.org").send(Hello("A"))
    new.assert_sent(Hello)
    new.restore()
    Mail.to("a@x.org").send(Hello("A"))
    assert len(Mail.transport("array").messages) == 1


def test_original_mailable_gets_recipients_under_fake(mail_app):
    m = Hello("A")
    with Mail.fake():
        Mail.to("a@x.org").send(m)
    assert m.has_to("a@x.org")
