"""Compile opt-in ALP 0.4 response collections; no batch operation or envelope."""
from __future__ import annotations

import copy

from .schema_tools import generation_views
from .strict_grammar import strict_json_grammar


def response_grammar(compiler, operations, catalog, schemas, *, codec):
    import xgrammar as xgr
    if codec == "canonical":
        from .schema_lowering import lower_schema
    else:
        from .constraints import lower_schema

    def seq(*items):
        return {"type": "sequence", "elements": list(items)}

    def union(items):
        return items[0] if len(items) == 1 else {"type": "or", "elements": items}

    def const(text):
        return {"type": "const_string", "value": text}

    whitespace = {"type": "grammar", "grammar": r'root ::= [ \n\r\t]{0,16}'}
    residual = [{"path": "", "rule": "response_request_id_uniqueness"}]
    cache = {}
    plan = catalog.response_constraints
    minimum, maximum = (plan.min_calls, plan.max_calls) if plan else (1, 16)

    def members(observed=None, index=None):
        from .catalog import stable_json
        key = stable_json([observed or {}, index])
        if key in cache:
            return cache[key]
        ordinary, exclusive = [], []
        from .response_constraints import member_catalog
        local = member_catalog(catalog, index) if index is not None else catalog
        selected = [plan.members[index].operation] if plan and plan.members and index is not None else operations
        for operation in selected:
            schema = schemas[operation]
            if index is not None or observed and operation == "agent_definition_generate":
                nested = type(compiler)(compiler.contracts, compiler.cache_size, observed)
                schema = nested._specialize(operation, local)
            for variant in generation_views(
                schema, operation, codec=codec, flexible=catalog.definition_field_order == "flexible",
                explicit_output=catalog.explicit_definition_output,
                text_limit=catalog.generation_text_limit,
                instruction_limit=catalog.generation_instruction_limit,
            ):
                payload = variant["properties"]["payload"]
                # Separate the reserved management call before building repetitions.
                branches = payload.get("anyOf", [payload]) if operation == "tool_call" else [payload]
                for branch in branches:
                    item = copy.deepcopy(variant)
                    item["properties"]["payload"] = copy.deepcopy(branch)
                    single = operation == "agent_final" or (
                        operation == "tool_call" and branch.get("properties", {}).get("tool") == {"const": "resource.bindings.update"})
                    lowered, checks = lower_schema(item)
                    residual.extend({**check, "path": "/" + operation + check["path"]} for check in checks)
                    content = {"type": "grammar", "grammar": strict_json_grammar(lowered)}
                    if codec == "tagged":
                        tag = compiler.contracts.binding(operation)["tag"]
                        content = {"type": "tag", "begin": f"<{tag}>", "end": f"</{tag}>", "content": seq(whitespace, content, whitespace)}
                    (exclusive if single else ordinary).append(content)
        cache[key] = (ordinary, exclusive)
        return ordinary, exclusive

    from .errors import ALPError
    separator = seq(whitespace, const(","), whitespace) if codec == "canonical" else whitespace
    observed = compiler.observed_definition.get("actions", {})
    if plan and plan.members:
        sequence = []
        for index in range(len(plan.members)):
            ordinary, exclusive = members(observed.get(str(index)), index)
            choices = ordinary + exclusive if len(plan.members) == 1 else ordinary
            if not choices:
                raise ALPError("INVALID_TASK_CONSTRAINT", "No legal member satisfies the response plan.", 422)
            if sequence:
                sequence.append(separator)
            sequence.append(union(choices))
        alternatives = [seq(*sequence)]
    else:
        ordinary, exclusive = members()
        alternatives = list(exclusive) if minimum == 1 else []
        if ordinary:
            if observed:
                last = max(int(index) for index in observed)
                if last >= maximum:
                    raise ALPError("INVALID_TASK_CONSTRAINT", "Observed response exceeds host bounds.", 422)
                tail = None
                for index in range(last, -1, -1):
                    choices, _ = members(observed.get(str(index)))
                    member = union(choices)
                    if tail is None:
                        tail = seq(member, {"type": "repeat", "min": max(0, minimum - last - 1),
                                            "max": maximum - last - 1,
                                            "content": seq(separator, union(ordinary))}) if last < maximum - 1 else member
                    else:
                        following = seq(separator, tail)
                        tail = seq(member, {"type": "optional", "content": following}
                                   if index + 1 >= minimum else following)
                alternatives.append(tail)
            else:
                member = union(ordinary)
                alternatives.append(seq(member, {"type": "repeat", "min": minimum - 1, "max": maximum - 1,
                                                 "content": seq(separator, member)}) if maximum > 1 else member)
    if not alternatives:
        raise ALPError("INVALID_TASK_CONSTRAINT", "The response plan has no legal completion.", 422)
    root = union(alternatives)
    if codec == "canonical":
        root = seq(const("["), whitespace, root, whitespace, const("]"))
    root = seq(whitespace, root, whitespace)
    grammar = str(xgr.Grammar.from_structural_tag({"type": "structural_tag", "format": root}))
    xgr.Grammar.from_ebnf(grammar)
    unique = {tuple(sorted(check.items())): check for check in residual}
    return grammar, tuple(unique.values())
