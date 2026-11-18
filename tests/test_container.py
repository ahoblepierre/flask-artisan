import threading
import time

import pytest

from flask_artisan.container import BindingResolutionError, Container


class A:
    pass


class B:
    def __init__(self, a: A):
        self.a = a


class Base:
    pass


class Impl(Base):
    pass


class WithDefault:
    def __init__(self, name: str = "x"):
        self.name = name


class C:
    def __init__(self, name: str):
        self.name = name


class X:
    def __init__(self, y: "Y"):
        self.y = y


class Y:
    def __init__(self, x: X):
        self.x = x


def test_make_unbound_class_autowires():
    assert isinstance(Container().make(B).a, A)


def test_bind_returns_new_instance_each_time():
    c = Container()
    c.bind(A)
    assert c.make(A) is not c.make(A)


def test_singleton_returns_same_instance():
    c = Container()
    c.singleton(A)
    assert c.make(A) is c.make(A)


def test_instance_registers_object():
    c = Container()
    obj = A()
    c.instance(A, obj)
    assert c.make(A) is obj


def test_closure_receives_container():
    c = Container()
    c.bind("x", lambda container: container)
    assert c.make("x") is c


def test_bind_interface_to_implementation():
    c = Container()
    c.bind(Base, Impl)
    assert isinstance(c.make(Base), Impl)


def test_params_override():
    sentinel = A()
    assert Container().make(B, a=sentinel).a is sentinel


def test_default_value_used_for_unresolvable():
    assert Container().make(WithDefault).name == "x"


def test_unresolvable_raises():
    with pytest.raises(BindingResolutionError, match=r"C.*name|name.*C"):
        Container().make(C)


def test_unknown_string_raises():
    with pytest.raises(BindingResolutionError):
        Container().make("nope")


def test_circular_dependency_raises():
    with pytest.raises(BindingResolutionError, match="circulaire"):
        Container().make(X)


def test_singleton_thread_safe():
    created = []

    class Slow:
        def __init__(self):
            time.sleep(0.01)
            created.append(1)

    c = Container()
    c.singleton(Slow)
    threads = [threading.Thread(target=c.make, args=(Slow,)) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(created) == 1


def test_bound():
    c = Container()
    c.bind("x", lambda container: 1)
    assert c.bound("x")
    assert not c.bound("y")
