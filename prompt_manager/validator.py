"""Build a Pydantic model at runtime from a JSON validation spec.

The validation schema lives inside the prompt's JSON file so each prompt
carries its own contract. Example schema for an email-extraction prompt:

    {
      "required_fields": ["broker", "product", "volume_mt", "price_usd", "trade_date"],
      "optional_fields": ["price_unit", "reference"],
      "field_types": {
        "broker": "str_nonempty",
        "product": "str_nonempty",
        "volume_mt": "float_positive",
        "price_usd": "float_positive",
        "trade_date": "iso_date",
        "price_unit": "str",
        "reference": "str"
      },
      "extra_forbidden": true
    }

Supported field types:
  str | str_nonempty | int | int_positive | float | float_positive |
  iso_date | iso_datetime | bool

If your prompt produces shapes outside this DSL you can fall back to writing
your own Pydantic model in your project — this DSL exists so that 90% of
prompts can be validated without writing any Python.
"""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

# (python type, default value or Field for required)
_TYPE_MAP_REQUIRED: dict[str, tuple[type, Any]] = {
    "str":           (str,   Field(...)),
    "str_nonempty":  (str,   Field(..., min_length=1)),
    "int":           (int,   Field(...)),
    "int_positive":  (int,   Field(..., gt=0)),
    "float":         (float, Field(...)),
    "float_positive":(float, Field(..., gt=0)),
    "iso_date":      (str,   Field(...)),     # post-check after model validation
    "iso_datetime":  (str,   Field(...)),
    "bool":          (bool,  Field(...)),
}

_TYPE_MAP_OPTIONAL: dict[str, tuple[type, Any]] = {
    "str":           (str | None,   None),
    "str_nonempty":  (str | None,   None),    # for optional we don't enforce non-empty
    "int":           (int | None,   None),
    "int_positive":  (int | None,   None),
    "float":         (float | None, None),
    "float_positive":(float | None, None),
    "iso_date":      (str | None,   None),
    "iso_datetime":  (str | None,   None),
    "bool":          (bool | None,  None),
}


class PromptValidator:
    """Translates a JSON schema spec into a Pydantic model + runs validation."""

    def __init__(self, schema_spec: dict[str, Any]):
        self.schema_spec = schema_spec or {}
        self._model = _build_model(self.schema_spec)
        # Field names typed as iso_date / iso_datetime — we run an extra check on these
        # after Pydantic accepts the dict, because dynamic Pydantic models can't
        # easily attach @field_validator hooks at construction time.
        self._iso_date_fields = [
            f for f, t in self.schema_spec.get("field_types", {}).items() if t == "iso_date"
        ]
        self._iso_datetime_fields = [
            f for f, t in self.schema_spec.get("field_types", {}).items() if t == "iso_datetime"
        ]

    def validate(self, parsed: dict) -> tuple[bool, list[str]]:
        """Validate a dict (the LLM's JSON output) against the spec."""
        if not self.schema_spec:
            return True, []

        errors: list[str] = []
        try:
            self._model.model_validate(parsed)
        except ValidationError as e:
            errors.extend(_format_pydantic_errors(e))

        # Extra date-format checks (Pydantic accepted the strings; we now check format).
        if not errors:
            for f in self._iso_date_fields:
                v = parsed.get(f)
                if v is not None and not _is_iso_date(v):
                    errors.append(f"Pole '{f}' nie jest poprawną datą YYYY-MM-DD (otrzymano: {v!r})")
            for f in self._iso_datetime_fields:
                v = parsed.get(f)
                if v is not None and not _is_iso_datetime(v):
                    errors.append(f"Pole '{f}' nie jest poprawnym datetime ISO 8601 (otrzymano: {v!r})")

        return len(errors) == 0, errors


def _build_model(schema_spec: dict[str, Any]) -> type[BaseModel]:
    required = schema_spec.get("required_fields", [])
    optional = schema_spec.get("optional_fields", [])
    types = schema_spec.get("field_types", {})
    forbid_extra = bool(schema_spec.get("extra_forbidden", False))

    fields: dict[str, tuple] = {}
    for name in required:
        t = types.get(name, "str")
        py_type, default = _TYPE_MAP_REQUIRED.get(t, _TYPE_MAP_REQUIRED["str"])
        fields[name] = (py_type, default)
    for name in optional:
        t = types.get(name, "str")
        py_type, default = _TYPE_MAP_OPTIONAL.get(t, _TYPE_MAP_OPTIONAL["str"])
        fields[name] = (py_type, default)

    config = ConfigDict(extra="forbid") if forbid_extra else ConfigDict(extra="allow")
    return create_model("DynamicPromptSchema", __config__=config, **fields)


def _is_iso_date(v: str) -> bool:
    try:
        datetime.strptime(v, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def _is_iso_datetime(v: str) -> bool:
    try:
        datetime.fromisoformat(v)
        return True
    except (ValueError, TypeError):
        return False


def _format_pydantic_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "(root)"
        etype = err["type"]
        raw = err.get("input")
        if etype == "missing":
            out.append(f"Brak wymaganego pola: '{loc}'")
        elif etype == "extra_forbidden":
            out.append(f"Nieoczekiwane pole w odpowiedzi LLM: '{loc}' (model halucynował?)")
        elif etype.startswith("greater_than"):
            out.append(f"Pole '{loc}' musi być dodatnie (otrzymano: {raw!r})")
        elif etype.startswith(("float_parsing", "int_parsing", "float_type", "int_type")):
            out.append(f"Pole '{loc}' nie jest liczbą (otrzymano: {raw!r})")
        elif etype == "string_type":
            out.append(f"Pole '{loc}' nie jest tekstem (otrzymano: {raw!r})")
        elif etype == "string_too_short":
            out.append(f"Pole '{loc}' jest puste")
        elif etype == "bool_type":
            out.append(f"Pole '{loc}' nie jest typu bool (otrzymano: {raw!r})")
        else:
            out.append(f"Walidacja pola '{loc}' nie powiodła się: {err['msg']}")
    return out
