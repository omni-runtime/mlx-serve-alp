# Validation and known limits

This is an integration report, not a claim that every model solves every task.
All real-model runs use the original private producer suite. Prompts contain its
original instructions, task and context; operation selection is explicit per case.
No golden payload is inserted into prompts or constraints. Output is neither
repaired nor retried, and failures remain in the evidence. Runtime execution and
authorization tests RT01–RT12 were **not run** by these inference adapters.
The media-reference cases exercise fictional IDs, not actual media understanding.

## Revisions

- Protocol package: alp-schema-mcp 0.3.0, private source commit
  `c2ced6e565fe430ef7d3ccb9d9fe61dc4e45c1c8`.
- Shared adapter: vllm-alp 0.1.1, private source commit
  `cf65664da05176b0b6775a718edbc9bf5384073b`.
- macOS engine: native MLX-Serve 26.9.6, Apple M5 Pro, 48 GiB unified memory.
- MLX model: mlx-community/Qwen3-14B-4bit,
  `a4d9b2df59d2c150bef02fcbe0d91046b7ca33a4` (8,323,870,520 downloaded bytes).
- CUDA engine: vLLM / vLLM-Omni 0.28.0, RTX 3060 Laptop, 6 GiB VRAM.
- CUDA model: cyankiwi/Qwen3-4B-Instruct-2507-AWQ-4bit,
  `c46e2277ae3dee7d030f45c58987b291edc5c1d6`.
- CUDA container digest:
  `sha256:6f8be103eaf0055448cf7578cfd621405fd669079d4361bd58896326b2bf722a`.

Both model downloads were verified file by file against their pinned LFS SHA-256
or Git blob SHA-1 hashes. Weight licenses are separate from this package.

## Automated checks

- Original protocol unit suite: **415 passed**.
- Original producer fixture checker: **97/97 passed** (60 positive format checks,
  32 negative fixtures, 5 boundary fixtures). These are static, not inference.
- Shared plugin plus MLX adapter tests: **145 passed**, including 24 adapter tests.
- Ruff, source distribution and wheel builds passed.
- Real endpoint boundary checks cover authentication, unknown model/catalog/operation,
  forbidden client overrides, nonstream output, truncation and subsequent health.

## Real inference

See [validation-summary.json](validation-summary.json) for final per-engine totals and failed case IDs.
Full prompts, generated output and checker errors remain in private operator
reports. They are deliberately not redistributed from the private test package.
The live runner saves exact SSE deltas, terminal events and full raw output.
The acceptance count requires both the original scenario checker and a completed,
validated ALP response with executed=false and authorized=false.

Final fixed-version results (temperature 0, seed 42, max_tokens 2048):

| Engine | Protocol-valid raw outputs | Full task acceptance | Live boundaries |
|---|---:|---:|---:|
| MLX-Serve / Qwen3-14B 4-bit | 18/20 | 17/20 | 8/8 |
| vLLM / Qwen3-4B AWQ | 20/20 | 16/20 | 8/8 |
| vLLM-Omni / Qwen3-4B AWQ | 20/20 | 16/20 | 8/8 |

MLX failures include incomplete tool/resource declarations and an incorrect
resource slot. CUDA failures include missing definition fields and changed
punctuation in an exact-copy task. Some are valid ALP proposals that fail the
scenario; syntactically/semantically invalid protocol outputs are rejected.
**The requested complete task acceptance has not been achieved.** Smaller-model
baselines and rejected experiments are retained privately, rather than selecting
individual passing answers across runs. A larger model or further model-level
work is needed before claiming all-case task accuracy.

Public GitHub CI passed lint and package build. Its private-dependency unit-test
job was explicitly skipped; the 145-test result above was run locally with the
authorized dependency checkouts.

## Sampling constraints

MLX-Serve 26.9.6 parses more schema constructs than its incremental JSON mask
actually enforces. This adapter resolves local references and preserves common
object/array/enum structure. Union branch correlations, recursive schema values,
allOf outside the known ObjectSchema form, regex and numeric bounds are deferred.
Unspecified additionalProperties is explicitly restored to JSON Schema's true
default. A native untyped empty-schema edge case is avoided with an explicit
arbitrary-JSON type union. The original protocol and specialized catalog are
always validated at the end; the projection never replaces them.

The native engine can disable its mask after a decoding dead end. The adapter
cannot claim a fully constrained generation for every schema. A separate live
canary did force an exact schema constant despite a conflicting user instruction;
this proves the native mask is active, not that every constraint is implemented.
Invalid outputs are returned as failures, never as authorized or executed calls.

## Deployment scope

MLX-Serve uses a loopback engine plus an authenticated adapter. vLLM and Omni use
in-process endpoint plugins. The Omni validation uses a real single-stage Qwen3
text AR pipeline with a registered forward-interface adapter, not a full
multimodal foundation model. The 6 GiB GPU runs one engine at a time.

Existing gateway local text and local/cloud embedding routes were checked with
real requests and returned HTTP 200. Existing H3 service health also returned
HTTP 200; a fresh H3 video generation was not part of this ALP acceptance.
No ALP gateway routing or host Runtime action dispatcher is claimed here.

## Capacity caveat

The trial H3 weights occupy approximately 38 GiB on disk. Keeping its process
online while the 14B ALP engine is online is not proof that both can perform
full inference concurrently in 48 GiB. The health and text/embedding regression
checks did not include simultaneous H3 video generation. Avoid claiming that
capacity; choose an operator-controlled model switch or separate resources.
