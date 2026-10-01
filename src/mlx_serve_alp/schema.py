from __future__ import annotations

import copy
import hashlib

from vllm_alp.catalog import stable_json
from vllm_alp.constraints import ALPConstraintCompiler, CompiledProfile, lower_schema


def project_schema(root: dict) -> tuple[dict, list[dict]]:
    """Project into MLX-Serve 26.9.6's supported subset; retain full final validation.

    MLX-Serve does not resolve $ref. Unions, regex and numeric bounds are relaxed
    by that engine, not enforced constraints. Never advertise them as token masks.
    """
    residual = []
    lowered, checks = lower_schema(root)
    residual.extend(checks)

    def any_json():
        # In 26.9.6 an untyped {} becomes Kind.any but leaves obj_additional
        # false. Nested arbitrary objects can then dead-end and trigger the
        # engine's mask fallback. An explicit type union selects anyNode(),
        # which correctly accepts arbitrary recursive JSON values.
        return {"type": ["object", "array", "string", "number", "boolean", "null"]}

    def union_hull(options):
        """A conservative superset that native masking can actually enforce."""
        if all(option == options[0] for option in options):
            return options[0]
        if all("const" in o or "enum" in o for o in options):
            values = []
            for option in options:
                for value in option.get("enum", [option.get("const")]):
                    if stable_json(value) not in [stable_json(v) for v in values]:
                        values.append(value)
            return {"enum": values}
        if all(o.get("type") == "object" for o in options):
            names = list(dict.fromkeys(k for o in options for k in o.get("properties", {})))
            additional = any(o.get("additionalProperties", True) for o in options)
            properties = {}
            for name in names:
                alternatives = [
                    o["properties"][name] for o in options if name in o.get("properties", {})
                ]
                if any(
                    name not in o.get("properties", {}) and o.get("additionalProperties", True)
                    for o in options
                ):
                    alternatives.append(any_json())
                properties[name] = union_hull(alternatives)
            required = [n for n in names if all(n in o.get("required", []) for o in options)]
            return {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": additional,
            }
        if all(o.get("type") == "array" for o in options):
            return {
                "type": "array",
                "items": union_hull([o.get("items", any_json()) for o in options]),
            }
        kinds = {o.get("type") for o in options if isinstance(o.get("type"), str)}
        if len(kinds) == 1 and all(
            isinstance(o.get("type"), str) and o["type"] in kinds for o in options
        ):
            return {"type": next(iter(kinds))}
        return any_json()

    def walk(node, path="", seen=()):
        if isinstance(node, bool):
            if not node:
                residual.append({"path": path, "rule": "false_schema"})
            return any_json()
        if "$ref" in node:
            ref = node["$ref"]
            if ref in seen:
                residual.append({"path": path, "rule": "recursive_reference"})
                return any_json()
            target = lowered
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                target = target[int(part)] if isinstance(target, list) else target[part]
            resolved = walk(target, path, (*seen, ref))
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            if siblings:
                residual.append({"path": path, "rule": "reference_siblings"})
            return resolved
        result = {}
        for key, value in node.items():
            pointer = path + "/" + key
            if key == "$defs":
                continue
            if key == "patternProperties":
                residual.append({"path": pointer, "rule": "pattern_properties"})
                continue
            if key in {"anyOf", "oneOf"}:
                options = [walk(v, pointer + f"/{i}", seen) for i, v in enumerate(value)]
                if len(options) == 1 and len(node) == 1:
                    return options[0]
                residual.append({"path": pointer, "rule": "union_token_mask_relaxed"})
                # Keep the common structure, but defer correlations between
                # discriminators and branch-specific properties to validation.
                return union_hull(options)
            elif key == "properties":
                result[key] = {k: walk(v, pointer + "/" + k, seen) for k, v in value.items()}
            elif key == "items":
                result[key] = walk(value, pointer, seen)
            elif key == "additionalProperties":
                result[key] = value if isinstance(value, bool) else True
                if isinstance(value, dict):
                    residual.append({"path": pointer, "rule": "additional_properties_schema"})
            elif key == "prefixItems":
                residual.append({"path": pointer, "rule": "tuple_items"})
            elif key in {"pattern", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}:
                residual.append({"path": pointer, "rule": key})
            else:
                result[key] = copy.deepcopy(value)
        # Upstream defaults unspecified additionalProperties to false; JSON
        # Schema defaults it to true. Preserve the actual contract explicitly.
        if result.get("type") == "object" and "additionalProperties" not in result:
            result["additionalProperties"] = True
        if not result:
            return any_json()
        return result

    return walk(lowered), residual


class MLXConstraintCompiler(ALPConstraintCompiler):
    def _compile(self, digest, operations, catalog):
        schemas = {op: self._specialize(op, catalog) for op in operations}
        projected, residual = {}, []
        for operation, schema in schemas.items():
            projected[operation], checks = project_schema(schema)
            residual.extend({**item, "path": "/" + operation + item["path"]} for item in checks)
        # Keep a constrained object even for a multi-operation union. Upstream
        # relaxes a root anyOf to arbitrary JSON, losing the envelope constraints.
        properties = {
            "protocol_version": {"const": "0.3.0"},
            "request_id": {"type": "string"},
            "operation": {"enum": list(operations)},
            "payload": projected[operations[0]]["properties"]["payload"]
            if len(operations) == 1
            else {"anyOf": [p["properties"]["payload"] for p in projected.values()]},
        }
        if len(operations) > 1:
            residual.append({"path": "/payload", "rule": "operation_payload_binding"})
        wire = {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
            "description": (
                "Sampling projection only; the complete ALP contract in the system message "
                "remains authoritative. Omit optional properties unless requested. "
                "Do not add empty placeholder values. Preserve exact Unicode task strings."
            ),
        }
        digest = hashlib.sha256(
            (digest + "/mlx-serve-26.9.6/canonical/" + stable_json(wire)).encode()
        ).hexdigest()
        return CompiledProfile(
            digest,
            operations,
            schemas,
            stable_json(wire),
            tuple(residual),
            catalog.model_copy(deep=True),
        )
