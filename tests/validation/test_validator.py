import pytest

from flask_artisan.validation import ValidationError, Validator, validate


def errors(data, rules, messages=None):
    return Validator(data, rules, messages).errors()


@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_required_fails_on_empty(value):
    assert errors({"name": value}, {"name": "required"}) == {
        "name": ["The name field is required."]
    }


@pytest.mark.parametrize("value", [0, False, "0", "x", [1]])
def test_required_accepts_falsy_non_empty(value):
    assert errors({"name": value}, {"name": "required"}) == {}


def test_required_missing():
    assert errors({}, {"first_name": "required"}) == {
        "first_name": ["The first name field is required."]
    }


def test_absent_or_empty_skips_other_rules():
    assert errors({"a": ""}, {"a": "email", "b": "integer|string"}) == {}


def test_none_without_nullable_fails_each_rule():
    assert errors({"a": None}, {"a": "string|email"}) == {
        "a": ["The a field must be a string.", "The a field must be a valid email address."]
    }


def test_none_with_nullable_passes():
    v = Validator({"a": None}, {"a": "nullable|string"})
    assert v.passes()
    assert v.validated() == {"a": None}


def test_sometimes_skips_required_when_absent():
    assert errors({}, {"a": "sometimes|required|string"}) == {}
    assert errors({"a": ""}, {"a": "sometimes|required"}) == {"a": ["The a field is required."]}


def test_required_with():
    rules = {"password": "required_with:email"}
    assert errors({"email": "x"}, rules) == {
        "password": ["The password field is required when email is present."]
    }
    assert errors({"email": ""}, rules) == {}


@pytest.mark.parametrize(
    ("rule", "good", "bad"),
    [
        ("string", "x", 1),
        ("integer", "-3", True),
        ("integer", 42, "4.2"),
        ("numeric", "4.5", "nan"),
        ("numeric", 3, False),
        ("boolean", "false", "yes"),
        ("boolean", 0, 2),
        ("array", [1], "x"),
        ("array", {"k": 1}, 1),
        ("email", "a@b.co", "a@b"),
        ("email", "a.b@c.org", "a b@c.org"),
        ("url", "https://x.org/p", "ftp://x.org"),
        ("date", "2026-11-26", "26/11/2026"),
    ],
)
def test_type_rules(rule, good, bad):
    assert errors({"f": good}, {"f": rule}) == {}
    assert errors({"f": bad}, {"f": rule}) != {}


def test_validated_only_ruled_present_fields():
    data = {"a": "x", "b": "y", "is_admin": True}
    assert validate(data, {"a": "required", "c": "string"}) == {"a": "x"}


def test_list_form_rules():
    assert errors({"a": "x"}, {"a": ["required", "string"]}) == {}


def test_unknown_rule_is_developer_error():
    with pytest.raises(ValueError, match="nope.*a"):
        Validator({"a": 1}, {"a": "nope"}).fails()


def test_validation_error_response():
    with pytest.raises(ValidationError) as info:
        validate({}, {"email": "required|email", "name": "required", "age": "required"})
    resp = info.value.get_response()
    assert resp.status_code == 422
    assert resp.get_json() == {
        "message": "The email field is required. (and 2 more errors)",
        "errors": {
            "email": ["The email field is required."],
            "name": ["The name field is required."],
            "age": ["The age field is required."],
        },
    }


def test_validation_error_singular():
    with pytest.raises(ValidationError) as info:
        validate({}, {"a": "required", "b": "required"})
    assert info.value.get_response().get_json()["message"].endswith("(and 1 more error)")


def test_invalid_regex_at_construction():
    with pytest.raises(ValueError, match=r"regex.*code|code.*regex"):
        Validator({}, {"code": "regex:[a-"})
