# Changelog

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
