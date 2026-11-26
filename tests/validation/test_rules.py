import pytest

from flask_artisan.validation import Validator


def errors(data, rules, messages=None):
    return Validator(data, rules, messages).errors()


def test_size_depends_on_type():
    assert errors({"n": "10"}, {"n": "numeric|max:9"}) == {
        "n": ["The n field must not be greater than 9."]
    }
    assert errors({"s": "abcd"}, {"s": "string|max:3"}) == {
        "s": ["The s field must not be greater than 3 characters."]
    }
    assert errors({"l": [1, 2]}, {"l": "array|min:3"}) == {
        "l": ["The l field must have at least 3 items."]
    }
    assert errors({"n": 5}, {"n": "integer|between:1,4"}) == {
        "n": ["The n field must be between 1 and 4."]
    }
    assert errors({"s": "100"}, {"s": "max:3"}) == {}  # sans numeric : longueur


def test_size_rule_on_non_numeric_value_fails_cleanly():
    assert errors({"n": "abc"}, {"n": "numeric|max:3"}) == {"n": ["The n field must be a number."]}


@pytest.mark.parametrize("rule", ["max", "max:x", "between:1"])
def test_size_bad_param_is_developer_error(rule):
    with pytest.raises(ValueError, match=r"(max|between).*s"):
        Validator({"s": "x"}, {"s": rule}).fails()


def test_in_and_not_in():
    assert errors({"r": "admin"}, {"r": "in:user,editor"}) == {"r": ["The selected r is invalid."]}
    assert errors({"r": 1}, {"r": "in:1,2"}) == {}
    assert errors({"r": "root"}, {"r": "not_in:root"}) == {"r": ["The selected r is invalid."]}


def test_confirmed_and_same():
    data = {"password": "a", "password_confirmation": "b"}
    assert errors(data, {"password": "confirmed"}) == {
        "password": ["The password field confirmation does not match."]
    }
    v = Validator({"password": "a", "password_confirmation": "a"}, {"password": "confirmed"})
    assert v.validated() == {"password": "a"}
    assert errors({"a": "x", "b": "y"}, {"a": "same:b"}) == {"a": ["The a field must match b."]}


def test_regex_with_pipe_and_comma_in_list_form():
    rules = {"c": ["regex:^(red|blue){1,2}$"]}
    assert errors({"c": "red"}, rules) == {}
    assert errors({"c": "green"}, rules) == {"c": ["The c field format is invalid."]}


def test_custom_messages_priority():
    msgs = {"required": "Need :attribute.", "email.required": "Email please."}
    assert errors({}, {"email": "required", "first_name": "required"}, msgs) == {
        "email": ["Email please."],
        "first_name": ["Need first name."],
    }


def test_custom_message_placeholders():
    assert errors({"s": "abcd"}, {"s": "max:3"}, {"max": ":attribute > :max"}) == {"s": ["s > 3"]}


@pytest.mark.parametrize("rules", ["numeric", "integer|max:10", "numeric|min:1"])
def test_huge_integer_is_an_error_not_a_crash(rules):
    assert errors({"n": 10**400}, {"n": rules}) != {}
