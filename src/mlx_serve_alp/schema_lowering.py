"""Conservative MLX grammar lowering; canonical validation remains authoritative."""
from __future__ import annotations

import copy
from typing import Any

from .catalog import schema_children
from .errors import ALPError

_ANNOTATIONS = {
    "$schema",
    "$id",
    "title",
    "description",
    "default",
    "examples",
    "deprecated",
    "readOnly",
    "writeOnly",
    "$comment",
}
_SCHEMA_MAPS = {"properties", "patternProperties", "$defs"}
_SCHEMA_LISTS = {"anyOf", "oneOf", "prefixItems"}
_SCHEMA_VALUES = {"items", "additionalProperties"}
_SCALARS = {
    "type",
    "$ref",
    "enum",
    "const",
    "required",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "x-alp-together",
    "x-alp-required-items",
    "x-alp-any-items",
    "x-alp-prefix-unique",
}
_RESIDUAL = {
    "uniqueItems",
    "format",
    "multipleOf",
    "allOf",
    "if",
    "then",
    "else",
    "not",
    "contains",
    "minContains",
    "maxContains",
    "dependentRequired",
    "dependentSchemas",
    "propertyNames",
    "minProperties",
    "maxProperties",
    "unevaluatedProperties",
    "unevaluatedItems",
}
_IDENTIFIER_PATTERNS = {
    ("^[A-Za-z0-9][A-Za-z0-9_-]*$", 1, 128): "^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    ("^[a-z][a-z0-9_.-]*$", 1, 128): "^[a-z][a-z0-9_.-]{0,127}$",
    ("^[a-z][a-z0-9_]{2,63}$", 3, 64): "^[a-z][a-z0-9_]{2,63}$",
    ("^[0-9][A-Za-z0-9_.+-]*$", 1, 128): "^[0-9][A-Za-z0-9_.+-]{0,127}$",
}


def lower_schema(schema: dict | bool, path: str = "") -> tuple[dict | bool, list[dict[str, str]]]:
    """Conservative XGrammar projection; the original schema remains authoritative.

    Traverse schema positions, not arbitrary const/enum data or property names.
    Every intentionally relaxed assertion is reported and rechecked at completion.
    """
    if isinstance(schema, bool):
        return schema, []
    output: dict[str, Any] = {}
    residual: list[dict[str, str]] = []
    for key, value in schema.items():
        pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
        if key in _ANNOTATIONS:
            continue
        if key == "uniqueItems" and isinstance(schema.get("items"), dict) and "enum" in schema["items"]:
            output[key] = value
            continue
        if key in _RESIDUAL:
            # Even deferred assertions must not hide unknown schema keywords.
            for child in schema_children({key: value}):
                lower_schema(child, pointer)
            residual.append({"path": pointer, "rule": key})
            continue
        if key in _SCHEMA_MAPS:
            output[key] = {}
            for name, child in value.items():
                lowered, checks = lower_schema(child, pointer + "/" + name)
                output[key][name] = lowered
                residual.extend(checks)
        elif key in _SCHEMA_LISTS:
            lowered_children = []
            for index, child in enumerate(value):
                lowered, checks = lower_schema(child, pointer + f"/{index}")
                lowered_children.append(lowered)
                residual.extend(checks)
            # XGrammar implements the union; jsonschema checks exclusivity.
            if key != "oneOf" or "anyOf" not in schema:
                output["anyOf" if key == "oneOf" else key] = lowered_children
            if key == "oneOf":
                residual.append({"path": pointer, "rule": "oneOf_exclusivity"})
        elif key in _SCHEMA_VALUES:
            output[key], checks = lower_schema(value, pointer)
            residual.extend(checks)
        elif key in _SCALARS:
            output[key] = copy.deepcopy(value)
        else:
            raise ALPError(
                "UNSUPPORTED_SCHEMA",
                "A schema keyword has no supported lowering.",
                details=[{"path": pointer, "rule": key}],
            )
    pattern = _IDENTIFIER_PATTERNS.get(
        (schema.get("pattern"), schema.get("minLength"), schema.get("maxLength"))
    )
    if pattern is not None:
        output["pattern"] = pattern
        output.pop("minLength", None)
        output.pop("maxLength", None)
    else:
        # Bounded strings are compiled by strict_json_grammar with complete
        # JSON escapes. Generic regex semantics remain a final check.
        for key in ("pattern",):
            if key in output:
                residual.append({"path": path + "/" + key, "rule": key})
                del output[key]
    return output, residual
