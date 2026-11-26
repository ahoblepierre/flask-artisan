import pytest

from flask_artisan import Event, event
from flask_artisan.application import Application
from flask_artisan.events import Dispatcher


class Shipped:
    pass


class Express(Shipped):
    pass


class Other:
    pass


log = []


@pytest.fixture
def app(make_project):
    log.clear()
    return Application(make_project())


def test_provider_listen_map(make_project):
    from flask_artisan.events import EventServiceProvider

    log.clear()

    class Provider(EventServiceProvider):
        listen = {Shipped: [lambda e: log.append("provider")]}

    app = Application(make_project())
    app.register(Provider)
    event(Shipped())
    assert log == ["provider"]


def test_full_fake_runs_no_listener_and_records(app):
    Event.listen(Shipped, lambda e: log.append("x"))
    fake = Event.fake()
    e = Shipped()
    assert Event.dispatch(e) == []
    assert log == []
    fake.assert_dispatched(Shipped)
    assert fake.dispatched(Shipped) == [e]


def test_partial_fake_simulates_subclasses_and_forwards_others(app):
    Event.listen(Express, lambda e: log.append("express"))
    Event.listen(Other, lambda e: log.append("other"))
    fake = Event.fake(Shipped)
    event(Express())
    event(Other())
    assert log == ["other"]
    fake.assert_dispatched(Express)
    fake.assert_dispatched(Other)


def test_service_holding_dispatcher_before_fake_sees_it(app):
    class Notifier:
        def __init__(self, events: Dispatcher):
            self.events = events

    app.singleton(Notifier)
    notifier = app.make(Notifier)
    Event.listen(Shipped, lambda e: log.append("x"))
    fake = Event.fake()
    notifier.events.dispatch(Shipped())
    assert log == []
    fake.assert_dispatched_times(Shipped, 1)


def test_nested_dispatch_recorded_in_order(app):
    Event.listen(Other, lambda e: event(Shipped()))
    fake = Event.fake(Shipped)
    event(Other())
    assert [type(e) for e in fake.dispatched(object)] == [Other, Shipped]


def test_second_fake_replaces_and_clears(app):
    Event.fake()
    event(Shipped())
    fake = Event.fake(Other)
    Event.listen(Shipped, lambda e: log.append("x"))
    event(Shipped())
    assert log == ["x"]
    fake.assert_dispatched_times(Shipped, 1)


def test_callback_assertions(app):
    fake = Event.fake()
    event(Shipped())
    fake.assert_dispatched(Shipped, lambda e: isinstance(e, Shipped))
    fake.assert_not_dispatched(Shipped, lambda e: False)
    with pytest.raises(AssertionError, match="Shipped"):
        fake.assert_dispatched(Shipped, lambda e: False)


@pytest.mark.parametrize(
    "check",
    [
        lambda f: f.assert_dispatched(Other),
        lambda f: f.assert_dispatched_times(Shipped, 2),
        lambda f: f.assert_not_dispatched(Shipped),
        lambda f: f.assert_nothing_dispatched(),
    ],
)
def test_failing_assertions_name_event_and_count(app, check):
    fake = Event.fake()
    event(Shipped())
    with pytest.raises(AssertionError, match=r"(Shipped|Other).*\d"):
        check(fake)


def test_listen_and_forget_still_work_in_fake_mode(app):
    Event.fake(Other)
    Event.listen(Shipped, lambda e: log.append("x"))
    event(Shipped())
    Event.forget(Shipped)
    event(Shipped())
    assert log == ["x"]


def test_restore_runs_listeners_again_and_keeps_records(app):
    Event.listen(Shipped, lambda e: log.append("x"))
    fake = Event.fake()
    event(Shipped())
    fake.restore()
    event(Shipped())
    assert log == ["x"]
    fake.assert_dispatched_times(Shipped, 1)


def test_fake_as_context_manager_restores_on_exit(app):
    Event.listen(Shipped, lambda e: log.append("x"))
    with Event.fake() as fake:
        event(Shipped())
        assert log == []
    event(Shipped())
    assert log == ["x"]
    fake.assert_dispatched_times(Shipped, 1)


def test_context_manager_restores_even_on_error(app):
    Event.listen(Shipped, lambda e: log.append("x"))
    with pytest.raises(RuntimeError), Event.fake():
        raise RuntimeError
    event(Shipped())
    assert log == ["x"]
