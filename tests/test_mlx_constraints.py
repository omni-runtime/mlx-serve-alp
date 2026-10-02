
import httpx
import pytest
from jsonschema import Draft202012Validator
from vllm_alp.errors import ALPError

from mlx_serve_alp.app import MLXConfig
from mlx_serve_alp.backend import MLXBackend
from mlx_serve_alp.schema import project_schema


def test_finite_object_union_keeps_branch_pairs_in_native_enum():
    source = {"oneOf": [
        {"type": "object", "properties": {"kind": {"const": "read"}, "write": {"const": False}},
         "required": ["kind", "write"], "additionalProperties": False},
        {"type": "object", "properties": {"kind": {"const": "write"}, "write": {"const": True}},
         "required": ["kind", "write"], "additionalProperties": False},
    ]}
    projected, checks = project_schema(source)
    assert "anyOf" in projected
    validator = Draft202012Validator(projected)
    assert validator.is_valid({"kind": "read", "write": False})
    assert validator.is_valid({"kind": "write", "write": True})
    assert not validator.is_valid({"kind": "read", "write": True})
    assert not any(c["rule"] == "union_token_mask_relaxed" for c in checks)


def test_false_array_items_become_empty_array_mask():
    projected, checks = project_schema({"type": "array", "items": False, "maxItems": 64})
    assert projected["items"] is False
    assert Draft202012Validator(projected).is_valid([])
    assert not Draft202012Validator(projected).is_valid(["forbidden"])


def test_native_enum_capacity_is_not_silently_truncated():
    projected, _ = project_schema({"enum": list(range(65))})
    assert projected['enum'] == list(range(65))


def test_combined_union_capacity_is_checked_after_projection():
    branches = [
        {"type": "object", "properties": {f"{prefix}{i}": {"type": "string"} for i in range(40)},
         "additionalProperties": False}
        for prefix in ("left", "right")
    ]
    projected, _ = project_schema({"anyOf": branches})
    assert projected['anyOf'] == branches


@pytest.mark.parametrize("caps,allowed", [
    (["video"], False), (["embedding"], False), (["chat"], False),
    (["chat", "json_schema"], False),
    (["chat", "json_schema", "alp_strict_grammar_v1"], True),
])
async def test_model_capabilities_are_checked_before_generation(caps, allowed):
    config = MLXConfig(upstream_model="test-model", catalogs={"test": {
        "allowed_operations": ["agent_final"],
    }})
    async def respond(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "test-model", "capabilities": caps}]})
    async with httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(respond)) as client:
        backend = MLXBackend(client, config)
        if allowed:
            await backend.validate_model()
        else:
            with pytest.raises(ALPError) as error:
                await backend.validate_model()
            assert error.value.code in {"UNSUPPORTED_MODEL_CAPABILITIES", "STRICT_GRAMMAR_UNAVAILABLE"}
