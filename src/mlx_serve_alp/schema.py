"""Compile full canonical ALP grammars for the native strict-mask bridge."""
from __future__ import annotations

import copy
import hashlib

from vllm_alp.constraints import ALPConstraintCompiler, CompiledProfile, lower_schema
from vllm_alp.schema_tools import generation_schemas
from vllm_alp.strict_grammar import strict_json_grammar


def project_schema(root: dict) -> tuple[dict, list[dict]]:
    """Keep unions, local references, typed properties and positional arrays.

    This schema targets XGrammar through the native ALP bridge, NOT the stock
    MLX-Serve JSON mask. No union hull or recursive-reference relaxation exists.
    """
    return lower_schema(root)


class MLXConstraintCompiler(ALPConstraintCompiler):
    def _compile(self, digest, operations, catalog):
        import xgrammar as xgr

        schemas, elements, residual = {}, [], []
        for operation in operations:
            schema = self._specialize(operation, catalog)
            schemas[operation] = schema
            for variant in generation_schemas(
                schema, operation, flexible=catalog.definition_field_order == "flexible",
                explicit_output=catalog.explicit_definition_output,
                text_limit=catalog.generation_text_limit,
                instruction_limit=catalog.generation_instruction_limit,
            ):
                canonical = copy.deepcopy(variant)
                props = canonical["properties"]
                canonical["properties"] = {
                    "protocol_version": props["protocol_version"],
                    "request_id": props["request_id"],
                    "operation": {"const": operation}, "payload": props["payload"],
                }
                canonical["required"] = list(canonical["properties"])
                lowered, checks = project_schema(canonical)
                elements.append({"type": "grammar", "grammar": strict_json_grammar(lowered)})
                residual.extend({**c, "path": "/" + operation + c["path"]} for c in checks)
        grammar = str(xgr.Grammar.from_structural_tag({
            "type": "structural_tag", "format": {"type": "or", "elements": elements},
        }))
        digest = hashlib.sha256((digest + "/mlx-strict-v1/" + grammar).encode()).hexdigest()
        return CompiledProfile(digest, operations, schemas, grammar, tuple(residual), catalog.model_copy(deep=True))
