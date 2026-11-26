"""Validation façon Laravel : règles en chaîne, `Validator`, `validate()`, erreur 422 JSON."""

import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlparse

from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response

__all__ = ["ValidationError", "Validator", "validate"]


def _json_response(body: dict, status: int) -> Response:
    return Response(json.dumps(body), status=status, mimetype="application/json")


class ValidationError(HTTPException):
    """Données invalides : produit elle-même sa réponse 422, sans gestionnaire à enregistrer."""

    code = 422

    def __init__(self, errors: dict[str, list[str]]):
        super().__init__()
        self.errors = errors

    def get_response(self, environ=None, scope=None) -> Response:
        messages = [m for field in self.errors.values() for m in field]
        message = messages[0] if messages else "The given data was invalid."
        if rest := len(messages) - 1:
            message += f" (and {rest} more error{'s' if rest > 1 else ''})"
        return _json_response({"message": message, "errors": self.errors}, self.code)


def _empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, (list, dict, tuple)) and not value


def _is_bool(value) -> bool:
    return value is True or value is False


# --- Règles : (valeur, paramètres, champ, validator) -> bool. Jamais appelées avec None.


def _required(value, params, field, v):
    return not _empty(value)


def _required_with(value, params, field, v):
    if any(not _empty(v.data.get(other)) for other in params):
        return not _empty(value)
    return True


def _integer(value, params, field, v):
    if isinstance(value, int):
        return not _is_bool(value)
    return isinstance(value, str) and re.fullmatch(r"-?\d+", value) is not None


def _numeric(value, params, field, v):
    if _is_bool(value):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, str):
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False
    return False


def _boolean(value, params, field, v):
    if _is_bool(value):
        return True
    if isinstance(value, int):
        return value in (0, 1)
    return value in ("0", "1", "true", "false")


def _email(value, params, field, v):
    if not isinstance(value, str) or any(c.isspace() for c in value) or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    return bool(local) and "." in domain.strip(".")


def _url(value, params, field, v):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def _date(value, params, field, v):
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


RULES = {
    "required": _required,
    "required_with": _required_with,
    "string": lambda value, *_: isinstance(value, str),
    "integer": _integer,
    "numeric": _numeric,
    "boolean": _boolean,
    "array": lambda value, *_: isinstance(value, (list, dict)),
    "email": _email,
    "url": _url,
    "date": _date,
}

PRESENCE = {"required", "required_with"}
MARKERS = {"nullable", "sometimes"}

MESSAGES = {
    "required": "The :attribute field is required.",
    "required_with": "The :attribute field is required when :values is present.",
    "string": "The :attribute field must be a string.",
    "integer": "The :attribute field must be an integer.",
    "numeric": "The :attribute field must be a number.",
    "boolean": "The :attribute field must be true or false.",
    "array": "The :attribute field must be an array.",
    "email": "The :attribute field must be a valid email address.",
    "url": "The :attribute field must be a valid URL.",
    "date": "The :attribute field must be a valid date.",
}


def _parse(spec) -> list[tuple[str, list[str]]]:
    parsed = []
    for item in spec.split("|") if isinstance(spec, str) else spec:
        name, _, arg = item.partition(":")
        # Le motif d'une regex peut contenir des virgules : il reste entier.
        params = [arg] if name == "regex" else arg.split(",") if arg else []
        parsed.append((name, params))
    return parsed


class Validator:
    def __init__(self, data: Mapping, rules: dict, messages: dict | None = None):
        self.data = data
        self.rules = {field: _parse(spec) for field, spec in rules.items()}
        self.custom_messages = messages or {}
        self._errors: dict[str, list[str]] | None = None
        for field, parsed in self.rules.items():
            for name, _ in parsed:
                if name not in RULES and name not in MARKERS:
                    raise ValueError(f"Règle de validation inconnue '{name}' (champ '{field}').")

    def fails(self) -> bool:
        return bool(self.errors())

    def passes(self) -> bool:
        return not self.fails()

    def errors(self) -> dict[str, list[str]]:
        if self._errors is None:
            self._errors = self._run()
        return self._errors

    def validated(self) -> dict:
        if self.fails():
            raise ValidationError(self.errors())
        return {field: self.data[field] for field in self.rules if field in self.data}

    def _run(self) -> dict[str, list[str]]:
        errors = {}
        for field, parsed in self.rules.items():
            names = {name for name, _ in parsed}
            present = field in self.data
            if "sometimes" in names and not present:
                continue
            value = self.data.get(field)
            for name, params in parsed:
                if name in MARKERS:
                    continue
                if name not in PRESENCE:
                    if not present or (value is not None and _empty(value)):
                        continue
                    if value is None and "nullable" in names:
                        continue
                # None sans nullable échoue toute règle hors présence (comme Laravel).
                failed = value is None and name not in PRESENCE
                if failed or not RULES[name](value, params, field, self):
                    errors.setdefault(field, []).append(self._message(field, name, params))
        return errors

    def _message(self, field: str, rule: str, params: list[str]) -> str:
        template = MESSAGES[rule]
        return template.replace(":attribute", field.replace("_", " ")).replace(
            ":values", ", ".join(params)
        )


def validate(data: Mapping, rules: dict, messages: dict | None = None) -> dict:
    return Validator(data, rules, messages).validated()
