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


def test_registered_in_container(app):
    assert app.make("events") is app.make(Dispatcher)


def test_function_listener_and_return_values(app):
    Event.listen(Shipped, lambda e: log.append(("fn", e)) or "r1")
    e = Shipped()
    assert Event.dispatch(e) == ["r1"]
    assert log == [("fn", e)]


def test_class_listener_injected_and_fresh_each_time(app):
    class Service:
        pass

    app.singleton(Service)
    seen = []

    class Listener:
        def __init__(self, service: Service):
            self.service = service

        def handle(self, e):
            seen.append(self)

    Event.listen(Shipped, Listener)
    event(Shipped())
    event(Shipped())
    assert len(seen) == 2
    assert seen[0] is not seen[1]
    assert seen[0].service is app.make(Service)


def test_tuple_listener(app):
    class L:
        def on_ship(self, e):
            log.append("tuple")

    Event.listen(Shipped, (L, "on_ship"))
    event(Shipped())
    assert log == ["tuple"]


def test_parent_listeners_after_exact_class_in_declaration_order(app):
    Event.listen(Shipped, [lambda e: log.append("parent1"), lambda e: log.append("parent2")])
    Event.listen(Express, lambda e: log.append("child"))
    event(Express())
    assert log == ["child", "parent1", "parent2"]
    assert Event.has_listeners(Express)
    assert not Event.has_listeners(Other)


def test_false_stops_propagation(app):
    Event.listen(Shipped, [lambda e: False, lambda e: log.append("never")])
    assert event(Shipped()) == [False]
    assert log == []


def test_exception_propagates_and_stops(app):
    def boom(e):
        raise RuntimeError("boom")

    Event.listen(Shipped, [boom, lambda e: log.append("never")])
    with pytest.raises(RuntimeError, match="boom"):
        event(Shipped())
    assert log == []


@pytest.mark.parametrize(
    "bad",
    [object(), type("NoHandle", (), {}), ("x", "y"), (type("C", (), {}), "missing")],
)
def test_invalid_listener_rejected_at_listen(app, bad):
    with pytest.raises(TypeError, match="Shipped"):
        Event.listen(Shipped, bad)


@pytest.mark.parametrize("bad", [Shipped, "shipped"])
def test_dispatch_requires_instance(app, bad):
    with pytest.raises(TypeError):
        Event.dispatch(bad)


def test_listen_requires_a_class(app):
    with pytest.raises(TypeError):
        Event.listen("shipped", lambda e: None)


def test_forget(app):
    Event.listen(Shipped, lambda e: log.append("x"))
    Event.forget(Shipped)
    event(Shipped())
    assert log == []
    assert not Event.has_listeners(Shipped)


def test_dispatch_outside_request_and_app_context(app):
    Event.listen(Shipped, lambda e: log.append("ok"))
    app.make("events").dispatch(Shipped())
    assert log == ["ok"]


def test_same_listener_on_child_and_parent_runs_twice(app):
    def fn(e):
        log.append("x")

    Event.listen(Shipped, fn)
    Event.listen(Express, fn)
    event(Express())
    assert log == ["x", "x"]


def test_top_level_exports():
    import flask_artisan

    assert {"Event", "event"} <= set(flask_artisan.__all__)
