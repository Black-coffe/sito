"""Turn pydantic models into HTML forms and back.

This is what lets plugin authors skip the frontend: a ``Config`` / ``Settings``
model is enough. Supported field types: ``str``, ``int``, ``float``, ``bool``,
``Literal[...]``, ``Enum``, ``list[str]`` (one item per line), ``SecretStr``
(password input, never sent back to the browser) and connection pickers
(``connection_field``).
"""

from __future__ import annotations

import os
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, SecretStr, ValidationError
from pydantic.fields import FieldInfo


@dataclass
class FormField:
    name: str
    label: str
    widget: str  # text | textarea | int | float | checkbox | select | list | password | connection
    value: Any = None
    help: str = ""
    required: bool = False
    options: list[tuple[str, str]] = field(default_factory=list)
    connection_kind: str | None = None
    secret_hint: str = ""


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _extra(info: FieldInfo) -> dict:
    return info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}


def _widget(annotation: Any, extra: dict) -> tuple[str, list[tuple[str, str]]]:
    if "sito_connection" in extra:
        return "connection", []
    if annotation is bool:
        return "checkbox", []
    if annotation is SecretStr:
        return "password", []
    if annotation is int:
        return "int", []
    if annotation is float:
        return "float", []
    if get_origin(annotation) is Literal:
        return "select", [(str(v), str(v)) for v in get_args(annotation)]
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return "select", [(str(m.value), str(getattr(m, "label", None) or m.value)) for m in annotation]
    if get_origin(annotation) in (list, tuple, set):
        return "list", []
    if extra.get("sito_widget") == "textarea":
        return "textarea", []
    return "text", []


_ACRONYMS = {
    "ai": "AI", "api": "API", "cpc": "CPC", "csv": "CSV", "http": "HTTP", "id": "ID", "json": "JSON",
    "kd": "KD", "llm": "LLM", "paa": "PAA", "serp": "SERP", "url": "URL", "xlsx": "XLSX",
}  # fmt: skip


def humanize(name: str) -> str:
    """Field name → label: ``api_key`` → "API key", ``max_kd`` → "Max KD"."""
    words = [_ACRONYMS.get(w.lower(), w.lower()) for w in name.split("_") if w]
    if words and words[0] not in _ACRONYMS.values():
        words[0] = words[0].capitalize()
    return " ".join(words)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith("env:"):
        return value
    return "••••" + value[-4:] if len(value) >= 12 else "••••"


def describe_model(model_cls: type[BaseModel], values: Mapping[str, Any] | None = None) -> list[FormField]:
    """Describe the fields of a model for rendering, filled with ``values`` or defaults."""
    values = values or {}
    fields: list[FormField] = []
    for name, info in model_cls.model_fields.items():
        annotation, _optional = _unwrap_optional(info.annotation)
        extra = _extra(info)
        widget, options = _widget(annotation, extra)
        default = None if info.is_required() else info.get_default(call_default_factory=True)
        value = values.get(name, default)
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        ff = FormField(
            name=name,
            label=info.title or humanize(name),
            widget=widget,
            value=value,
            help=info.description or "",
            required=info.is_required(),
            options=options,
            connection_kind=extra.get("sito_connection"),
        )
        if widget == "password":
            ff.secret_hint = mask_secret(str(value or ""))
            ff.value = ""
        elif widget == "list":
            ff.value = "\n".join(str(v) for v in (value or []))
        fields.append(ff)
    return fields


def parse_form(
    model_cls: type[BaseModel],
    form: Mapping[str, Any],
    existing: Mapping[str, Any] | None = None,
) -> BaseModel:
    """Validate submitted form data into ``model_cls``.

    Empty password fields keep the ``existing`` value, so a saved key is not
    wiped by re-saving the form. Raises ``pydantic.ValidationError``.
    """
    existing = existing or {}
    data: dict[str, Any] = {}
    for name, info in model_cls.model_fields.items():
        annotation, optional = _unwrap_optional(info.annotation)
        widget, _ = _widget(annotation, _extra(info))
        if widget == "checkbox":
            data[name] = name in form and str(form.get(name)).lower() not in ("", "0", "false", "off")
            continue
        raw = form.get(name)
        if raw is None:
            continue
        if isinstance(raw, str):
            raw = raw.strip()
        if widget == "password":
            if raw == "":
                if existing.get(name):
                    data[name] = existing[name]
                continue
            data[name] = raw
        elif widget == "list":
            data[name] = [line.strip() for line in str(raw).splitlines() if line.strip()]
        elif widget in ("int", "float", "connection"):
            if raw == "":
                if optional:
                    data[name] = None
                continue
            data[name] = raw
        else:
            data[name] = raw
    return model_cls.model_validate(data)


def _jsonable(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value


def dump_model(model: BaseModel) -> dict:
    """JSON-safe dict of a model, secrets revealed (for storing in the database)."""
    return _jsonable(model.model_dump(mode="python"))


def default_values(model_cls: type[BaseModel]) -> dict:
    try:
        return dump_model(model_cls())
    except ValidationError:
        return {}


def format_errors(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for err in exc.errors():
        key = ".".join(str(p) for p in err.get("loc", ())) or "__all__"
        errors.setdefault(key, err.get("msg", "Invalid value"))
    return errors


def first_error(exc: ValidationError) -> str:
    return "; ".join(f"{k}: {v}" for k, v in format_errors(exc).items())


def secret_fields(model_cls: type[BaseModel]) -> set[str]:
    return {name for name, info in model_cls.model_fields.items() if _unwrap_optional(info.annotation)[0] is SecretStr}


def resolve_env_refs(raw: Mapping[str, Any], model_cls: type[BaseModel] | None = None) -> dict:
    """Replace ``"env:VAR_NAME"`` values with the environment variable's value.

    With ``model_cls``, only its secret (``SecretStr``) fields are resolved, so an
    environment variable can never be smuggled into a URL or another plain field.
    """
    allowed = secret_fields(model_cls) if model_cls is not None else None
    resolved: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str) and value.startswith("env:") and (allowed is None or key in allowed):
            resolved[key] = os.environ.get(value[4:].strip(), "")
        else:
            resolved[key] = value
    return resolved
