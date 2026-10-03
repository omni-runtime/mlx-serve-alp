# Changelog

## 0.3.0

- Add opt-in ALP 0.4 response collections with atomic validation and paired terminal results.
- Keep 0.3 as the default; isolate catalogs and private replay by protocol version.
- Enforce reserved resource management, exclusive actions and per-response IDs.
- Update the producer runner for the latest 0.3/0.4 suites and pin the authorized contract revision.
- Preserve native and protocol token-mask intersection, whole-response termination, and definition dependency constraints.
- Add configurable semantic rendering and trusted state-effect preconditions without inferring task answers.

## 0.2.2

- Maintain catalog, task binding, grammar, endpoint and stream helpers inside the MLX plugin.
- Remove the vllm-alp dependency; require only the unchanged alp-schema-mcp 0.3.0 protocol package.
- Preserve signed host requests and compiled generation constraints across the split.

## 0.2.1

- Use vllm-alp 0.2.1 compatibility imports backed by the shared alp_schema_mcp runtime.
- Keep cloud Function Calling in the separate semantic-router-alp project.

## 0.2.0

- Share configurable compact prompt rendering with vllm-alp 0.2.0.
- Support server-owned payload requirements and fixed values in catalogs.
- Preserve the original catalog in final validation after constraint narrowing.
- Offer optional explicit output contracts during definition generation, retaining legacy validation.
- Accept omitted Agent arguments when the target schema accepts the default empty object.
- Keep validation reports and raw evidence outside source distributions.

## 0.1.0

- Canonical ALP 0.3.0 endpoint backed by native MLX-Serve over authenticated loopback.
- Shared catalogs, lifecycle and full final validation with vllm-alp 0.1.1.
- Conservative native JSON Schema projection with explicit residual checks.
- Bearer authentication, stream cancellation and bounded inference concurrency.
- Original producer-suite runner with raw-output evidence and no answer repair.
- macOS service launcher and pinned model manifest.
