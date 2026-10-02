# Server-owned task constraints

`Catalog.payload_constraints` optionally narrows an operation for a host-defined
task. It does not infer natural-language requirements. The host supplies the
requirements and chooses the catalog; caller requests cannot supply this object.
Constraints never grant permissions or execute actions.

Add this object to a catalog that allows `agent_definition_generate`:

```json
{
  "payload_constraints": {
    "agent_definition_generate": {
      "required_fields": ["/output", "/environment_profile_ref"],
      "fixed_values": {
        "/output": {"format": "text"},
        "/environment_profile_ref": "sandbox.reviewed_python"
      }
    }
  }
}
```

Paths are JSON Pointers relative to `payload`, through explicitly declared object
properties. Array indexes and undeclared/dynamic property paths are not supported.
Every ancestor and target of a constraint becomes required. Fixed values must
satisfy the existing field schema; unsupported paths and conflicting values fail
compilation. A fixed object must also satisfy separately configured child rules.
The original catalog schema remains a final assertion, including oneOf exclusivity.
Neither the protocol nor the tool/agent catalog can be expanded by these rules.

For an existing `agent_call` catalog, `/input/task` can bind host-supplied text
exactly. For a tool catalog, `/arguments/slot` can bind a known resource slot.
The host must provide legitimate task values; do not derive them from test golden
answers. Existing catalogs without `payload_constraints` retain their domains.

The compiler incorporates constraints into its cache digest, generation schema,
structured model context and final validation. On MLX, the strict native bridge
enforces the compiled grammar. Assertions outside the supported lowering still
remain final checks.
No missing output is repaired and no failed generation is silently retried.

Static catalogs remain deployment-scoped. Use the registry's host integration
for per-request or per-tenant catalogs and authorization. Keep catalog count
bounded; each distinct task value can require a new compiled grammar.

Evaluate unmodified task prompts separately from tasks with additional host
constraints. Keep reports and raw model outputs locally, outside the source tree.

## Optional generation policies

Catalogs also accept `compact_prompt` and `explicit_definition_output` (both false
by default). The first removes unused schema definitions while preserving field
descriptions; the second requires an explicit output contract during definition
sampling without rejecting legacy definitions during final protocol validation.

On both backends, `definition_field_order` defaults to `contract`. The optional `flexible`
mode adds one late-output/environment ordering, compiling branches separately to
preserve required and unique object keys. It is not arbitrary key order and applies
to both XGrammar backends. Broader sampling choices can reduce model accuracy;
evaluate these policies separately before enabling them in a deployment.

## Request-bound trusted host tasks

Set `task_signing_key_env` in the server config to an environment variable holding
an independent signing key of at least 32 bytes. Ordinary model/API clients must
not receive this key. The feature is disabled when the config field is absent.
The existing endpoint API key still controls access.

The host passes reviewed structured task values to
`vllm_alp.task_context.task_headers(request, constraints, key=key)`, then sends the
returned headers with that exact ALP request. The vllm-alp repository's
`scripts/host_call.py` is an executable client for reviewed request/constraint JSON files. It works with both
vLLM and MLX adapters. Constraints are never extracted from model text or tests.

The signed context expires after 60 seconds by default (maximum 300), binds the
complete validated request including model, messages, operation and catalog,
and can only narrow the deployment catalog. Conflicting fixed values, tampering,
expired contexts and duplicate headers fail before generation. Identical request
replay within the lifetime is possible; this token is not an execution idempotency
key or an authorization grant. The runtime remains responsible for both.

```python
from vllm_alp.catalog import PayloadConstraints
from vllm_alp.task_context import task_headers

headers = task_headers(request, {
    "agent_call": PayloadConstraints(fixed_values={
        "/input/task": reviewed_task_text,
    }),
}, key=host_signing_key)
# Send request.model_dump() and headers to /v1/alp/chat/completions.
```

Definition compilation also binds capability tool subsets to visible/fixed tools,
resource subsets to fixed declared slots, and compiles the `agent_run` read-state
rule into explicit branches. Inconsistent fixed resource/tool declarations are
rejected before inference. Unknown runtime relationships still require final
protocol validation and host authorization.
