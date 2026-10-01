# mlx-serve-alp

[简体中文](README.zh-CN.md)

Serve validated Agent Lifecycle Protocol (ALP) 0.3.0 actions with native
[MLX-Serve](https://github.com/ddalcu/mlx-serve) on Apple Silicon.

This package exposes `POST /v1/alp/chat/completions`, compiles deployment catalogs
into server-controlled JSON Schema, and returns one validated `message.agent_calls`
entry. It shares protocol compilation, request validation and completion lifecycle
with [vllm-alp](https://github.com/omni-runtime/vllm-alp); the authoritative protocol
comes from `alp-schema-mcp==0.3.0`. No tools or agents are executed.

Native MLX-Serve is a Zig binary without vLLM's Python endpoint-plugin interface.
This adapter uses its authenticated loopback HTTP interface. The inference engine
remains MLX-Serve; this package does not load model weights or select backends.

## Install

Requires Python 3.12+, MLX-Serve **26.9.6**, and a supported text-generation model.
**The two runtime dependencies, `alp_schema_mcp` and `vllm-alp`, are private
repositories. Obtain access or authorized wheels from their maintainers first.**
This public repository does not redistribute their code, contracts or test suite.
A public clone alone is therefore not sufficient to run the adapter.
See [dependency access](docs/dependencies.md).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install /path/to/alp_schema_mcp-0.3.0-py3-none-any.whl
python -m pip install /path/to/vllm_alp-0.1.1-py3-none-any.whl
python -m pip install -e '.[test]'
mlx-serve-alp check --config examples/config.json
```

The example uses a fictional demonstration catalog. Replace it with the actual
host-published agent/tool contracts before application use. Catalogs are scoped
to the deployment; they are not tenant authorization or execution grants.

## Run

Set `MLX_ALP_ENGINE_KEY` and `MLX_ALP_API_KEY` securely in the service environment.
Keep credentials out of command arguments and version control.

```bash
mlx-serve --model /path/to/Qwen3-4B-Instruct-2507-4bit --serve \
  --host 127.0.0.1 --port 11236 --ctx-size 32768 \
  --api-key-env MLX_ALP_ENGINE_KEY --api-key-strict --no-pld
mlx-serve-alp serve --config examples/config.json --host 127.0.0.1 --port 11237
```

The adapter requires both keys. Its `/health` checks the engine and reveals no
credentials; all other routes require the frontend Bearer key. Configure firewall
and TLS termination when exposing it outside a trusted network.

```bash
curl http://127.0.0.1:11237/v1/alp/chat/completions \
  -H "Authorization: Bearer $MLX_ALP_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"local/alp","messages":[{"role":"user","content":"Discover the capabilities of demo_assistant."}],"alp":{"allowed_operations":["list_agent_capabilities"],"catalog_ref":"demo-text"},"include_raw":true}'
```

## Output and constraints

The model emits **canonical JSON**, including `operation`. `raw` and provisional
SSE deltas preserve those exact bytes; `alp.raw_format` is `canonical`. The adapter
does not add missing fields, strip fences, convert raw output to tagged text, or
retry malformed generations. The final response API matches vllm-alp's
`alp.chat.completion` and `message.agent_calls` envelope.

`stream: true` emits `agent_call.started`, provisional `agent_call.arguments.delta`,
then exactly one `agent_call.completed` or `agent_call.failed`. A closed JSON
object is insufficient: normal completion of the entire provider stream is
required. Truncation, trailing content, duplicate keys, cancellation, bad catalog
arguments and multiple actions cannot become successful calls. Client cancellation
closes the HTTP generation stream.

MLX-Serve's JSON mask supports the envelope and a subset of nested schemas.
Its unions, patterns and number ranges are not fully enforced during sampling.
`alp.residual_checks` lists deferred constraints, all of which are checked against
the original protocol and catalog on completion. These limits differ from
XGrammar; this package never claims full grammar equivalence. Model quality,
resource existence, authorization and actual execution are separate concerns.

## Test

```bash
pytest -q
ruff check src tests scripts
python -m build
python scripts/run_producer.py --suite /path/to/alp_schema_mcp \
  --base-url http://127.0.0.1:11237 --model local/alp \
  --codec canonical --output reports/live
```

The live runner reads the supplied `examples/check_producer.py`, verifies the
contract digest, and runs the original 20 tasks. It saves raw model output and
separate protocol/scenario results; it never reads golden answers into prompts.
Supply the frontend key through `ALP_API_KEY`. Static fixture self-tests, model
generation scores and Runtime execution tests are distinct evidence.

Validate your chosen model against your application's tasks: schema-valid actions
can still contain incorrect arguments. Keep validation reports and raw evidence
locally; do not commit or push them to this repository.

See [security](SECURITY.md) and
[contributing](CONTRIBUTING.md). Licensed under [Apache-2.0](LICENSE).
Model weights and the separately installed engine retain their own licenses.
