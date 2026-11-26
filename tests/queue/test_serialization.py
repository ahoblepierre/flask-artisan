from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from flask_artisan.database.query import ModelNotFound
from flask_artisan.queue.serialization import (
    class_path,
    dump,
    import_class,
    load,
    restore,
    serialize,
)

from .models import QPodcast


class Holder:
    def __init__(self, **values):
        self.__dict__.update(values)


class Exploding:
    def __init__(self):
        raise AssertionError("__init__ ne doit pas être appelé")


@pytest.mark.parametrize("value", [None, 1, 1.5, True, "é", [1, "a"], {"k": [1, {"n": None}]}])
def test_json_values_round_trip(value):
    assert load(dump(value, "x")) == value


def test_tuple_becomes_list():
    assert load(dump((1, 2), "x")) == [1, 2]


def test_datetime_date_decimal_round_trip():
    values = [
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        datetime(2026, 1, 2),
        date(2026, 1, 2),
    ]
    for value in [*values, Decimal("1.10")]:
        restored = load(dump(value, "x"))
        assert restored == value and type(restored) is type(value)
    assert load(dump(Decimal("1.10"), "x")).as_tuple() == Decimal("1.10").as_tuple()


def test_model_round_trip_reloads_fresh(queue_app):
    podcast = QPodcast.create(title="old")
    dumped = dump(podcast, "podcast")
    QPodcast.find(podcast.id).fill(title="new").save()
    queue_app.make("db").session.expire_all()
    restored = load(dumped)
    assert isinstance(restored, QPodcast) and restored.title == "new"


def test_deleted_model_raises_not_found(queue_app):
    podcast = QPodcast.create(title="a")
    dumped = dump(podcast, "podcast")
    podcast.delete()
    with pytest.raises(ModelNotFound):
        load(dumped)


def test_unsaved_model_rejected(queue_app):
    with pytest.raises(TypeError, match="id"):
        dump(QPodcast(title="a"), "podcast")


def test_unsupported_value_names_attribute():
    with pytest.raises(TypeError, match=r"Holder.*fh|fh.*Holder"):
        serialize(Holder(fh=object()))


def test_non_str_dict_keys_rejected():
    with pytest.raises(TypeError):
        dump({1: "a"}, "x")


def test_reserved_marker_dict_rejected():
    with pytest.raises(TypeError):
        dump({"__model__": "x", "id": 1}, "x")


def test_local_class_rejected():
    class Local:
        pass

    with pytest.raises(TypeError, match="Local"):
        class_path(Local)


def test_serialize_skips_private_and_restore_skips_init():
    obj = Exploding.__new__(Exploding)
    obj.word, obj._secret = "a", 1
    payload = serialize(obj)
    assert payload == {"class": f"{__name__}.Exploding", "data": {"word": "a"}}
    restored = restore(payload, Exploding)
    assert restored.word == "a" and not hasattr(restored, "_secret")


def test_restore_requires_base():
    with pytest.raises(TypeError):
        restore({"class": "os.path", "data": {}}, Holder)
    with pytest.raises(TypeError):
        restore({"class": f"{__name__}.Holder", "data": {}}, Exploding)


def test_import_class_rejects_non_class():
    with pytest.raises(TypeError):
        import_class("os.path.join", object)


def test_model_marker_must_be_model():
    with pytest.raises(TypeError):
        load({"__model__": "collections.OrderedDict", "id": 1})
