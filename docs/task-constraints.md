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
prompt and final validation. On MLX, unsupported constraints remain final checks;
this feature does not upgrade the native engine's grammar implementation.
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

For vLLM, `definition_field_order` defaults to `contract`. The optional `flexible`
mode adds one late-output/environment ordering, compiling branches separately to
preserve required and unique object keys. It is not arbitrary key order and does
not apply to MLX's native mask. Broader sampling choices can reduce model accuracy;
evaluate these policies separately before enabling them in a deployment.
