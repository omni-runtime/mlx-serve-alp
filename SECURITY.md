# Security

ALP output is a proposal. This adapter does not authorize or execute agents or
tools. The host Runtime must separately enforce identity, resource ACLs, budgets,
state versions, approvals and native tool schemas.

Both API keys are required. Keep the native engine on loopback and use secret
files/service environment variables rather than command-line credentials. Use
network access controls and TLS termination when exposing the frontend. A catalog
is deployment configuration, not a multi-tenant access-control mechanism.

Treat streaming deltas as untrusted provisional data. Only a completed, validated
response may be considered as a proposal for host policy evaluation. Invalid,
truncated or trailing output fails closed at the adapter. MLX-Serve 26.9.6 has a
partial JSON mask and may disable masking on a dead end; the final full validator
remains authoritative. Do not rely on the sampling mask as an authorization gate.

For sensitive reports, use GitHub's private vulnerability reporting when enabled.
Do not put live credentials or private prompts in public issues. Supported adapter
version: 0.1.x with the engine version documented in the validation report.
