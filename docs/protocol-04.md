# Opt-in ALP 0.4

ALP 0.3 remains the default. Set `alp.protocol_version` to `"0.4.0"` explicitly
for response collections. The private `alp_schema_mcp` dependency must be installed
from commit `459257275b29865d3f60facb67283c8bfab1262e` (see the dependency lock).
Its package version is still 0.3.0; the version number alone does not select this
contract revision. Obtain dependency access separately. No standalone core
package or service is required.

The six operations are unchanged. One completed model turn contains 1–16 ordinary
requests, with unique request IDs. Native constrained decoding generates ordinary ALP
requests; canonical responses are arrays even for one item, and tagged responses
concatenate ordinary frames. `agent_final` and the reserved
`resource.bindings.update` tool each require a singleton response. The reserved
management descriptor cannot be replaced or delegated by a generated definition.

The public completion retains `choices[0].message.agent_calls`, now with one entry
per member. All entries are published together after whole-response validation.
SSE deltas remain provisional text, never executable actions. Failure, cancellation,
truncation, duplicate IDs, trailing content or any invalid member rejects the whole
response. The complete ALP projection is limited to 128 KiB.

`alp.validation_scope` and `alp.task_constraint_coverage` are ordered per-member
arrays in 0.4; they retain their object shape in 0.3. Catalog task constraints still
apply to every member of the selected operation. Use response `members` for
different per-member requirements in one turn; they intersect the global
constraints. Protocol validation does not claim natural-language task matching.

Return one canonical terminal Result per accepted member, in original request
order, using that member's public call ID as `tool_call_id`. All results must be
available before requesting the next model turn. Count, request ID, operation and
successful target are checked by `validate_action_exchange` when rendering 0.4
conversation history. A final terminates that history and cannot be followed by
another generation; it does not create an ALP success Result. Provider-private
Function Calling replay and its local acknowledgment belong to
`semantic-router-alp`, not these local engine adapters.

The adapter does not execute tools, register agents, grant permissions, manage
Run/resource revisions, or schedule actions in parallel. These remain Runtime
responsibilities. Static protocol and producer tests do not validate those Runtime
features. No public batch operation or success envelope is introduced.

## Reproducible producer tests

Use the latest authorized `test-case` checkout. The runner supports both protocol
versions and no longer depends on the removed per-case `/operation` assertion.
Supply an operator-owned `--case-config` JSON map when cases require different
visible catalogs. Each entry contains `operations` and `catalog_ref`; expected
answers are used only by the suite scorer after generation.

```bash
export ALP_API_KEY=...  # use a private environment, never commit credentials
python scripts/run_producer.py --suite /path/to/test-case \
  --base-url http://your-endpoint --model your-model \
  --protocol-version 0.4.0 --case-config /private/cases.json \
  --output /private/reports/run-04
```

Reports distinguish endpoint acceptance from exact task matching, retain raw wire
output, and report failures without retries or output repair. Run again with
`--protocol-version 0.3.0` for the original 20-case regression. Testing does not
execute any generated call. Keep reports, endpoint keys and deployment catalogs
outside the public repository.

## Trusted response constraints

For ALP 0.4, a catalog may set `response_constraints` with `min_calls` and
`max_calls` (1–16), or an ordered `members` list. Each member names an operation
and supplies its own `PayloadConstraints`; its position is significant. A member
list fixes the response count. Global operation constraints remain in force.
`forbidden_fields` contains object JSON Pointers under payload and prevents
unsupplied host values such as `expected_state_version` from being invented.

Trusted callers can use `host_response_headers` to sign the same member plan
as task-context version 2. The signature covers the entire request and expires;
it cannot widen catalog limits, replace fixed values, or change the operation.
Existing version-1 operation constraints remain supported. ALP 0.3 rejects
response-level constraints. Neither mechanism grants permission or executes calls.

`DefinitionTask.output_from_capability` derives the final output schema from the
same capability contract. Use it with `capabilities` to avoid independently
generating two interface schemas. An omitted environment means the protocol
default environment; `default` is not an implicit catalog profile name.

Responses expose `response_constraint_coverage` plus per-call task coverage.
Protocol validity does not claim that unbound natural-language requirements were
met. Producer evaluations should report original prompt-only cases separately
from tests with trusted task inputs bound at the host. Tool execution is outside
the producer evaluation.

Native sampling compiles exact member order/count into the grammar, including
end-of-generation eligibility. Resource selection supports up to 16 slots using
incremental dependency and uniqueness checks instead of enumerating every subset.
Final authoritative validation is still required for the entire response.

### Signing an ordered host request

The catalog must already expose every referenced target. With an ALP 0.4
`ALPChatRequest` selecting `agent_call`, the trusted caller can sign a plan:

```python
from mlx_serve_alp.host_tasks import host_response_headers

headers = host_response_headers(
    request,
    members=[
        {"operation": "agent_call", "payload": {
            "fixed_values": {"/instance_id": target, "/input/task": task,
                             "/session_mode": "isolated"},
            "forbidden_fields": ["/expected_state_version"],
        }}
        for target, task in approved_tasks
    ],
    key=trusted_host_signing_key,
)
# Send request.model_dump() and these headers to /v1/alp/chat/completions.
```

`approved_tasks` is supplied by the host. Do not infer permission, target IDs, or
a signing key from model output. Counts and task values are enforced; descriptions
and other requirements left unbound remain the model's responsibility.

For native generation, resource selection is explicit (an empty selection retains
the ALP default) and precedes tools. The matcher narrows each capability's tool
domain before sampling tool names. Final parsing still accepts protocol-legal
omissions and arbitrary JSON object key order. Catalog objects are normalized
before compilation so a sorted context transport cannot change constant prefixes.

When `state_schema` is omitted, sampling constrains `initial_state` to the
protocol default `{}`, including definitions that omit exported capabilities.
An explicitly supplied state schema continues to constrain its own initial state.


## Framework semantic presentation and observed state

Native engines default to `local_render_profile: stable`, the tested body-schema
presentation. The optional `generation` profile uses the same generation view as
the grammar, including canonical operation and generation-required dependencies,
and enables protocol-derived hints when `semantic_rendering` is true. Live 4B
comparisons regressed with the expanded presentation; it is not enabled by default.
Neither mode supplies fixture answers or inferred task constraints.

`Capability.state_effect`/`external_effect`, `Agent.state_version` and
`Catalog.current_state_version` accept trusted Runtime metadata. A declared
state-writing tool/capability without an observed version fails preparation with
`MISSING_RUNTIME_CONTEXT`; with a version, generation and validation require that
exact precondition. Read calls retain optional explicit guards. Resolve fresh
request-scoped metadata; Runtime must still check versions atomically before
execution. The adapter neither invents state nor grants permissions.
