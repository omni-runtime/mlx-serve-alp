# Strict native decoding

The adapter sends server-compiled EBNF and request-local catalog context through
`response_format.json_schema.schema.x-alp-ebnf`. A patched native MLX text engine
connects to `MLX_ALP_MASK_SOCKET`. The Python worker uses the engine's exact token
bytes to return a vocabulary-sized mask before each sample. Sampled tokens advance
that request's matcher. Socket errors, compilation failures, invalid samples and
empty masks terminate generation; they never restore unrestricted sampling.

The socket is local, mode 0600, and must be in an operator-owned directory.
It is not a remote API or an authorization boundary against other processes
running as the same user. Each connection owns its matcher; bounded compiler
caches are shared. The bridge adds CPU/IPC work per token; benchmark the actual
model vocabulary and expected definition sizes before sizing a deployment.

Generation first emits resource and tool declarations, including explicit empty
arrays. Their completed values specialize later capability domains. Masks enforce
finite tool-array uniqueness, knowledge-tool pairing, declared resource subsets,
capability/resource dependencies, duplicate capability names/resource slots, and
the agent-run read-state relationship. Generated resources are limited to 8 slots;
finite unique arrays support at most 12 candidate values. Larger domains fail
explicitly because enumerating their combinations is expensive.

Union branches, typed additional properties, tuple prefixes and escaped bounded
strings retain their structural constraints. Generic regular expressions,
nonfinite unique arrays, general conditionals and other reported residual checks
still require final validation. This does not assert equivalence for arbitrary
JSON Schema or every semantic relationship inside a newly generated schema.
Task matching, resource availability, authorization and execution are separate.

`generation_text_limit` limits ALP descriptions and `generation_instruction_limit`
independently limits ALP instructions (0 means protocol limits). Neither applies
to same-named business fields in input/output schemas. It does not
truncate fixed host values, task inputs or output after generation. Record this
policy when comparing model runs. The native ALP path injects no generic schema
prompt; shared context consists of the structured schema/catalog JSON plus the
original caller messages. There are no repaired answers or automatic retries.

Once a generated `state_schema` is complete, its schema constrains the following
`initial_state` before sampling. If the default empty state is invalid, that
field becomes required. Inconsistent fixed state/schema values fail compilation.
This covers the supported schema lowering; residual assertions still apply.


## Trusted catalog relationships

Definition generation requires `external_effect` (`none`, `read`, `write`) for
nonreserved tools. Knowledge-tool classifications come from the protocol and
cannot be overridden. Missing classifications fail with `UNCLASSIFIED_TOOL`.
Agent-run capabilities exclude tools with `state_effect=write`; their external
effect is constrained to the highest selected tool effect, including `none` for
an empty subset. Final validation independently checks this relationship.

A request-scoped `Catalog` can supply `environment_profiles`, `resource_bindings`
(kind/slot/profile/version/tool allowlist), `evidence_bindings` (evidence ID to
knowledge slot), and `handlers` (exact interface/state/effect/required-tool
contracts). Resource tuples and evidence-slot pairs are correlated, not independent
enums. Unknown handlers are unavailable. None means a domain was not provided;
an empty list/map has no choices. `validation_scope` reports the checks actually
applicable and provided, without claiming runtime authorization or execution.
A host requiring strict availability checks must provide these domains through
its trusted `CatalogRegistry.resolve`; signing a task does not grant access or
make model-authored resource names trustworthy. Use tenant/run-specific snapshots;
all catalog content participates in the compiler digest and cache separation.

Resources, tools and optional state schemas precede capabilities in generated
wire output. Host constants are reapplied after dependency specialization and
independently checked against their original values at completion.

`PayloadConstraints.capabilities` maps desired capability names to exact
`input_schema`, `output_schema`, `state_effect`, and/or `external_effect` values.
When supplied, it defines the complete capability-name set; unspecified prose
remains generated. It is supported in static configuration and signed task
contexts. A signed request can narrow a static contract but cannot add names to
an already fixed capability set. Conflicting requirements fail before inference.
Schema equality for these exact contracts and registered handlers preserves
annotations; no approximate semantic-equivalence comparison is used.

Keep original natural-language conformance tasks separate from trusted host-task
tests. Do not derive constraints from golden outputs. Record prose limits and
output-token budgets with scores; JSON validity does not assess free-text quality.

Generated JSON permits at most 16 formatting whitespace characters per grammar
boundary. This prevents unbounded whitespace loops before a closing delimiter;
whitespace inside strings and fixed values remains data. The final parser still
accepts protocol-valid JSON formatting. Incomplete output is rejected, never
completed or repaired after generation.
