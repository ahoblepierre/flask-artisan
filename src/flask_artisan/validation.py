"""Validation façon Laravel : règles en chaîne, `Validator`, `validate()`, erreur 422 JSON."""

import io
import json
import math
import re
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlparse

from flask import has_request_context, request
from sqlalchemy import column, literal, select, table
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response

__all__ = ["AuthorizationError", "FormRequest", "ValidationError", "Validator", "validate"]


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


class AuthorizationError(HTTPException):
    code = 403

    def get_response(self, environ=None, scope=None) -> Response:
        return _json_response({"message": "This action is unauthorized."}, self.code)


def _empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, FileStorage):
        return not value.filename  # champ fichier envoyé sans fichier choisi
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
        try:
            return math.isfinite(value)
        except OverflowError:  # entier JSON géant
            return False
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


def _size(value, field, v) -> float | None:
    """Taille selon le type : valeur (numeric/integer), nombre d'éléments, ou longueur."""
    if v.names(field) & {"numeric", "integer"}:
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
        except (TypeError, ValueError):
            return None  # la règle de type signale déjà l'erreur
    if isinstance(value, (list, dict)):
        return len(value)
    if isinstance(value, FileStorage):
        return math.ceil(_file_bytes(value) / 1024)  # en kilo-octets, comme Laravel
    return len(str(value))


def _file_bytes(file: FileStorage) -> int:
    stream = file.stream
    try:
        position = stream.tell()
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(position)
    except (OSError, AttributeError):  # flux sans seek : lu une fois, gardé en mémoire
        data = stream.read()
        file.stream = io.BytesIO(data)
        return len(data)
    return size


IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "avif"}


def _ext(file) -> str:
    name = file.filename or ""
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    return "jpg" if ext == "jpeg" else ext


def _is_file(value) -> bool:
    return isinstance(value, FileStorage) and bool(value.filename)


def _image(value, *_):
    # Extension et type MIME envoyés par le client (pas d'analyse du contenu) ; jamais svg.
    return (
        _is_file(value)
        and _ext(value) in IMAGE_EXTENSIONS
        and (value.mimetype or "").startswith("image/")
        and value.mimetype != "image/svg+xml"
    )


def _mimes(value, params, *_):
    allowed = {"jpg" if p.lower() == "jpeg" else p.lower() for p in params}
    return _is_file(value) and _ext(value) in allowed


def _min(value, params, field, v):
    size = _size(value, field, v)
    return size is None or size >= float(params[0])


def _max(value, params, field, v):
    size = _size(value, field, v)
    return size is None or size <= float(params[0])


def _between(value, params, field, v):
    size = _size(value, field, v)
    return size is None or float(params[0]) <= size <= float(params[1])


def _confirmed(value, params, field, v):
    key = f"{field}_confirmation"
    return key in v.data and v.data[key] == value


def _regex(value, params, field, v):
    return isinstance(value, str) and re.search(params[0], value) is not None


IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _db_column(params: list[str], field: str) -> str:
    return params[1] if len(params) > 1 and params[1] else field


def _row_exists(params, field, value, ignore=None) -> bool:
    """Requête Core paramétrée sur la session de la requête (voit les lignes non validées)."""
    from flask_artisan.facades import DB

    query = (
        select(literal(1))
        .select_from(table(params[0]))
        .where(column(_db_column(params, field)) == value)
    )
    if ignore is not None:
        query = query.where(column(ignore[1]) != ignore[0])
    return DB.session.execute(query.limit(1)).first() is not None


def _unique(value, params, field, v):
    if isinstance(value, (list, dict)):
        return False
    ignore = None
    if len(params) > 2 and params[2]:
        ignore = (params[2], params[3] if len(params) > 3 and params[3] else "id")
    return not _row_exists(params, field, value, ignore)


RULES = {
    "required": _required,
    "required_with": _required_with,
    "string": lambda value, *_: isinstance(value, str),
    "file": lambda value, *_: _is_file(value),
    "image": _image,
    "mimes": _mimes,
    "integer": _integer,
    "numeric": _numeric,
    "boolean": _boolean,
    "array": lambda value, *_: isinstance(value, (list, dict)),
    "email": _email,
    "url": _url,
    "date": _date,
    "min": _min,
    "max": _max,
    "between": _between,
    "in": lambda value, params, *_: str(value) in params,
    "not_in": lambda value, params, *_: str(value) not in params,
    "confirmed": _confirmed,
    "same": lambda value, params, field, v: params[0] in v.data and v.data[params[0]] == value,
    "regex": _regex,
    "unique": _unique,
    "exists": lambda value, params, field, v: (
        not isinstance(value, (list, dict)) and _row_exists(params, field, value)
    ),
}

# Paramètres attendus : (nombre minimal, numériques ?).
PARAMS = {
    "required_with": (1, False),
    "min": (1, True),
    "max": (1, True),
    "between": (2, True),
    "in": (1, False),
    "not_in": (1, False),
    "same": (1, False),
    "regex": (1, False),
    "mimes": (1, False),
    "unique": (1, False),
    "exists": (1, False),
}

SIZE_MESSAGES = {
    "min": {
        "numeric": "The :attribute field must be at least :min.",
        "string": "The :attribute field must be at least :min characters.",
        "array": "The :attribute field must have at least :min items.",
        "file": "The :attribute field must be at least :min kilobytes.",
    },
    "max": {
        "numeric": "The :attribute field must not be greater than :max.",
        "string": "The :attribute field must not be greater than :max characters.",
        "array": "The :attribute field must not have more than :max items.",
        "file": "The :attribute field must not be greater than :max kilobytes.",
    },
    "between": {
        "numeric": "The :attribute field must be between :min and :max.",
        "string": "The :attribute field must be between :min and :max characters.",
        "array": "The :attribute field must have between :min and :max items.",
        "file": "The :attribute field must be between :min and :max kilobytes.",
    },
}

PRESENCE = {"required", "required_with"}
MARKERS = {"nullable", "sometimes"}

MESSAGES = {
    "required": "The :attribute field is required.",
    "required_with": "The :attribute field is required when :values is present.",
    "string": "The :attribute field must be a string.",
    "file": "The :attribute field must be a file.",
    "image": "The :attribute field must be an image.",
    "mimes": "The :attribute field must be a file of type: :values.",
    "integer": "The :attribute field must be an integer.",
    "numeric": "The :attribute field must be a number.",
    "boolean": "The :attribute field must be true or false.",
    "array": "The :attribute field must be an array.",
    "email": "The :attribute field must be a valid email address.",
    "url": "The :attribute field must be a valid URL.",
    "date": "The :attribute field must be a valid date.",
    "in": "The selected :attribute is invalid.",
    "not_in": "The selected :attribute is invalid.",
    "confirmed": "The :attribute field confirmation does not match.",
    "same": "The :attribute field must match :other.",
    "regex": "The :attribute field format is invalid.",
    "unique": "The :attribute has already been taken.",
    "exists": "The selected :attribute is invalid.",
}


def _check_params(name: str, params: list[str], field: str) -> None:
    count, numeric = PARAMS.get(name, (0, False))
    if len(params) < count or not all(params[:count]):
        raise ValueError(f"La règle '{name}' du champ '{field}' attend {count} paramètre(s).")
    if numeric:
        try:
            [float(p) for p in params[:count]]
        except ValueError:
            raise ValueError(
                f"La règle '{name}' du champ '{field}' attend des nombres : {params}."
            ) from None
    if name in ("unique", "exists"):
        names = [params[0], _db_column(params, field)]
        if name == "unique" and len(params) > 3 and params[3]:
            names.append(params[3])
        for ident in names:
            if not IDENTIFIER.fullmatch(ident):
                raise ValueError(
                    f"La règle '{name}' du champ '{field}' : identifiant invalide '{ident}'."
                )


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
            for name, params in parsed:
                if name not in RULES and name not in MARKERS:
                    raise ValueError(f"Règle de validation inconnue '{name}' (champ '{field}').")
                _check_params(name, params, field)

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

    def names(self, field: str) -> set[str]:
        return {name for name, _ in self.rules[field]}

    def _run(self) -> dict[str, list[str]]:
        errors = {}
        for field, parsed in self.rules.items():
            names = self.names(field)
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
                    errors.setdefault(field, []).append(self._message(field, name, params, value))
        return errors

    def _message(self, field: str, rule: str, params: list[str], value) -> str:
        template = self.custom_messages.get(f"{field}.{rule}") or self.custom_messages.get(rule)
        if template is None and rule in SIZE_MESSAGES:
            if self.names(field) & {"numeric", "integer"}:
                kind = "numeric"
            else:
                kind = "array" if isinstance(value, (list, dict)) else "string"
                if isinstance(value, FileStorage):
                    kind = "file"
            template = SIZE_MESSAGES[rule][kind]
        template = template or MESSAGES[rule]
        low = params[0] if params else ""
        replacements = {
            ":attribute": field.replace("_", " "),
            ":values": ", ".join(params),
            ":other": low.replace("_", " "),
            ":min": low,
            ":max": params[-1] if params else "",
        }
        for key, text in replacements.items():
            template = template.replace(key, text)
        return template


def validate(data: Mapping, rules: dict, messages: dict | None = None) -> dict:
    return Validator(data, rules, messages).validated()


class FormRequest:
    """Requête validée : le conteneur la construit pour un paramètre de controller annoté
    par sa classe ; la construction autorise puis valide, avant l'appel du controller."""

    def __init__(self):
        if not has_request_context():
            raise RuntimeError(
                f"{type(self).__name__} lit la requête HTTP courante : "
                "construisez-la pendant une requête (ou utilisez validate())."
            )
        data = request.args.to_dict()
        body = request.get_json(silent=True)
        data.update(body if isinstance(body, dict) else request.form.to_dict())
        for key, file in request.files.items():  # le premier fichier par champ
            data.setdefault(key, file)  # un champ texte du même nom garde sa valeur
        self._data = data
        if not self.authorize():
            raise AuthorizationError()
        self._validated = Validator(data, self.rules(), self.messages()).validated()

    def rules(self) -> dict:
        raise NotImplementedError(f"{type(self).__name__} doit définir rules().")

    def authorize(self) -> bool:
        return True

    def messages(self) -> dict:
        return {}

    def validated(self) -> dict:
        return dict(self._validated)

    def all(self) -> dict:
        return dict(self._data)

    def input(self, key: str, default=None):
        return self._data.get(key, default)
