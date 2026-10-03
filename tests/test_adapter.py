import json
from pathlib import Path

import httpx
import pytest
from alp_schema_mcp.catalog import ContractCatalog

from mlx_serve_alp.app import MLXConfig, create_app
from mlx_serve_alp.errors import ALPError
from mlx_serve_alp.parser import ALPParser
from mlx_serve_alp.protocol import ALPOptions
from mlx_serve_alp.schema import MLXConstraintCompiler, project_schema

ROOT = Path(__file__).resolve().parents[1]
ACTION = {
    "protocol_version": "0.3.0",
    "request_id": "req_test",
    "operation": "agent_final",
    "payload": {"output": {"format": "text", "value": '中文 \\" </agent_final>'}, "artifacts": []},
}


@pytest.mark.parametrize("mutation,expected", [(None, 200), ("punctuation", 502), ("session", 502)])
async def test_typed_host_task_reaches_native_mask_and_final_validator(config, monkeypatch, mutation, expected):
    from mlx_serve_alp.host_tasks import AgentCallTask, host_task_headers
    from mlx_serve_alp.protocol import ALPChatRequest

    key = b"mlx-host-task-test-signing-key-32bytes"
    config.task_signing_key_env = "MLX_TEST_HOST_KEY"
    monkeypatch.setenv(config.task_signing_key_env, key.decode())
    catalog = config.catalogs["demo-text"]
    name = next(iter(catalog.agents))
    task = AgentCallTask(instance_id=name, task='中文。\n原样“引号”', session_mode="isolated")
    body = ALPChatRequest(model=config.model, messages=[{"role": "user", "content": "Call this agent"}],
                         alp={"allowed_operations": ["agent_call"], "catalog_ref": "demo-text"})
    payload = task.payload()
    if mutation == "punctuation":
        payload["input"]["task"] = payload["input"]["task"].replace("。", ".")
    if mutation == "session":
        del payload["session_mode"]

    async def respond(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": config.upstream_model,
                "capabilities": ["chat", "json_schema", "alp_strict_grammar_v1"]}]})
        wire = json.loads(request.content)
        context = json.loads(wire["response_format"]["json_schema"]["schema"]["x-alp-ebnf"])["context"]
        assert context["catalog"]["payload_constraints"]["agent_call"]["fixed_values"]["/input/task"] == task.task
        raw = json.dumps({"protocol_version": "0.3.0", "request_id": "host_mlx", "operation": "agent_call", "payload": payload})
        event = {"choices": [{"index": 0, "delta": {"content": raw}, "finish_reason": "stop"}]}
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n")

    app = create_app(config, transport=httpx.MockTransport(respond))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            response = await client.post("/v1/alp/chat/completions", json=body.model_dump(),
                headers={"Authorization": "Bearer frontend-test-key", **host_task_headers(body, task, key=key)})
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()["alp"]["task_constraint_coverage"]["key_fields"]["/session_mode"] == "fixed"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("MLX_ALP_API_KEY", "frontend-test-key")
    monkeypatch.setenv("MLX_ALP_ENGINE_KEY", "engine-test-key")
    return MLXConfig.from_file(ROOT / "examples/config.json")


def profile(config, operation="agent_final"):
    return MLXConstraintCompiler().compile(
        ALPOptions(allowed_operations=[operation], catalog_ref="demo-text"),
        config.catalogs["demo-text"],
    )


def test_canonical_parser_preserves_raw_and_checks_catalog(config):
    p = ALPParser(profile(config), ContractCatalog(), codec="canonical")
    raw = json.dumps(ACTION, ensure_ascii=False)
    for char in raw:
        p.feed(char)
    assert p.finish("stop") == ACTION
    assert p.raw == raw
    with pytest.raises(ALPError):
        p.finish("stop")


@pytest.mark.parametrize("tail", ["extra", "{}", "\n" + json.dumps(ACTION)])
def test_trailing_output_rejected(config, tail):
    p = ALPParser(profile(config), ContractCatalog(), codec="canonical")
    p.feed(json.dumps(ACTION) + tail)
    with pytest.raises(ALPError, match="validation"):
        p.finish("stop")


@pytest.mark.parametrize("reason", [None, "length", "abort"])
def test_complete_json_does_not_override_truncation(config, reason):
    p = ALPParser(profile(config), ContractCatalog(), codec="canonical")
    p.feed(json.dumps(ACTION))
    with pytest.raises(ALPError) as e:
        p.finish(reason)
    assert e.value.code == "INCOMPLETE_GENERATION"


def test_schema_projection_resolves_refs_and_reports_limits(config):
    p = profile(config, "tool_call")
    import xgrammar as xgr
    xgr.Grammar.from_ebnf(p.grammar)
    assert not any(c["rule"] == "union_token_mask_relaxed" for c in p.residual_checks)
    output, residual = project_schema(
        {"type": "object", "properties": {"x": {"type": "string", "pattern": "x+"}}}
    )
    assert "additionalProperties" not in output  # JSON Schema default remains true.
    assert any(c["rule"] == "pattern" for c in residual)


def test_arbitrary_json_uses_explicit_types_for_native_mask():
    projected, _ = project_schema({"type": "object", "properties": {"value": {}}})
    assert projected["properties"]["value"] == {}


def test_union_projection_preserves_valid_branches_and_excludes_unknown_fields():
    import jsonschema

    branches = [
        {
            "type": "object",
            "properties": {"kind": {"const": "a"}, "value": {"type": "string"}},
            "required": ["kind", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"kind": {"const": "b"}, "value": {}},
            "required": ["kind"],
            "additionalProperties": False,
        },
    ]
    projected, checks = project_schema({"oneOf": branches})
    for value in [
        {"kind": "a", "value": "x"},
        {"kind": "b"},
        {"kind": "b", "value": {"nested": [1]}},
    ]:
        jsonschema.validate(value, projected)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"kind": "c"}, projected)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"kind": "b", "unknown": True}, projected)
    assert not any(c["rule"] == "union_token_mask_relaxed" for c in checks)


@pytest.mark.parametrize("mode", ["ok", "length", "trailing", "error", "no_done"])
@pytest.mark.parametrize("stream", [False, True])
async def test_actual_route_lifecycle(config, mode, stream):
    requests = []

    async def backend(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{
                "id": config.upstream_model, "capabilities": ["chat", "json_schema", "alp_strict_grammar_v1"],
            }]})
        requests.append(request)
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        envelope = json.loads(body["response_format"]["json_schema"]["schema"]["x-alp-ebnf"])
        assert envelope["context"]["operations"] == ["agent_final"]
        assert '::=' in envelope["grammar"]
        assert request.headers["authorization"] == "Bearer engine-test-key"
        assert "tools" not in body
        if mode == "error":
            return httpx.Response(500, json={"secret": "must not escape"})
        text = json.dumps(ACTION, ensure_ascii=False) + ("tail" if mode == "trailing" else "")
        events = [
            {"choices": [{"index": 0, "delta": {"content": text[:20]}, "finish_reason": None}]},
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": text[20:]},
                        "finish_reason": "length" if mode == "length" else "stop",
                    }
                ]
            },
            {"choices": [], "usage": {"completion_tokens": 10}},
        ]
        content = "".join("data: " + json.dumps(e) + "\n\n" for e in events)
        if mode != "no_done":
            content += "data: [DONE]\n\n"
        return httpx.Response(200, text=content, headers={"Content-Type": "text/event-stream"})

    app = create_app(config, transport=httpx.MockTransport(backend))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as c:
            body = {
                "model": config.model,
                "messages": [{"role": "user", "content": "Reply"}],
                "alp": {"allowed_operations": ["agent_final"], "catalog_ref": "demo-text"},
                "stream": stream,
                "include_raw": True,
            }
            assert (await c.post("/v1/alp/chat/completions", json=body)).status_code == 401
            assert not requests
            response = await c.post(
                "/v1/alp/chat/completions",
                json=body,
                headers={"Authorization": "Bearer frontend-test-key"},
            )
            assert "must not escape" not in response.text
            if stream:
                events = [
                    json.loads(line[6:])
                    for line in response.text.splitlines()
                    if line.startswith("data: ")
                ]
                assert events[0]["type"] == "agent_call.started"
                assert events[-1]["type"] == (
                    "agent_call.completed" if mode == "ok" else "agent_call.failed"
                )
                if mode == "ok":
                    result = events[-1]["response"]
                    assert "".join(e["delta"] for e in events if "delta" in e) == result["raw"]
            else:
                assert response.status_code == (200 if mode == "ok" else 502)
                if mode == "ok":
                    result = response.json()
            if mode == "ok":
                assert result["alp"]["raw_format"] == "canonical"
                assert result["choices"][0]["message"]["agent_calls"][0]["request"] == ACTION
                assert result["alp"]["executed"] is False


@pytest.mark.parametrize(
    "url",
    ["https://example.com", "http://10.0.0.1", "http://u:p@localhost", "http://localhost/path"],
)
def test_config_rejects_remote_or_credential_urls(config, url):
    with pytest.raises(ValueError):
        MLXConfig.model_validate({**config.model_dump(), "engine_url": url})


def test_trusted_constraints_survive_mlx_projection_and_final_validation(config):
    from mlx_serve_alp.catalog import PayloadConstraints

    catalog = config.catalogs["demo-text"].model_copy(deep=True)
    literal = "Exact Unicode text。"
    catalog.payload_constraints["agent_final"] = PayloadConstraints(
        fixed_values={"/output/value": literal}
    )
    compiler = MLXConstraintCompiler()
    compiled = compiler.compile(
        ALPOptions(allowed_operations=["agent_final"], catalog_ref="demo-text"), catalog
    )
    value = compiled.body_schemas['agent_final']["properties"]["payload"]["properties"]["output"]["properties"]["value"]
    assert value == {"const": literal}
    good = {**ACTION, "payload": {"output": {"format": "text", "value": literal}}}
    parser = ALPParser(compiled, compiler.contracts, codec="canonical")
    parser.feed(json.dumps(good))
    assert parser.finish("stop") == good
    bad = {**good, "payload": {"output": {"format": "text", "value": "changed"}}}
    parser = ALPParser(compiled, compiler.contracts, codec="canonical")
    parser.feed(json.dumps(bad))
    with pytest.raises(ALPError) as error:
        parser.finish("stop")
    assert error.value.code == "INVALID_CALL_ARGUMENTS"
