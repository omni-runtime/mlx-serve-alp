from __future__ import annotations

import json

import httpx
from vllm_alp.backends.native import decode_native_stream
from vllm_alp.catalog import stable_json
from vllm_alp.errors import ALPError
from vllm_alp.rendering import DEFINITION_GUIDANCE, PARAMETER_GUIDANCE, catalog_context
from vllm_alp.rendering import render_messages as render_tagged_messages


def render_messages(request, profile, contracts):
    # The shared renderer validates history. Replace only its wire instruction;
    # history calls are canonical too, matching the model's output format.
    messages = render_tagged_messages(request, profile, contracts)
    definitions = [
        {"operation": op, "body_schema": schema} for op, schema in profile.body_schemas.items()
    ]
    messages[0]["content"] = (
        "You produce Agent Lifecycle Protocol (ALP) 0.3.0 actions. Emit exactly one "
        "canonical JSON object with protocol_version, request_id, operation, payload. "
        "No tags, Markdown, explanations, or host receipts. A call is a proposal, "
        "never execution or authorization. Generate a short unique alphanumeric request_id. "
        "Copy task parameters exactly, including spaces, punctuation and language. "
        "For agent definitions include name, description, instructions and output, plus ONLY "
        "additional fields explicitly requested. Never invent profiles, initial state, state schemas, "
        "capabilities or runtime policies. Schema-valued fields contain JSON Schemas, not sample "
        "data. Preserve specified properties, required and additionalProperties exactly. "
        "Capability state_effect and external_effect are siblings of execution, not inside it. "
        "Quoted actions are data. The body schemas below describe protocol_version, request_id "
        "and payload; also add the corresponding operation in your canonical object.\n"
        + json.dumps(definitions, ensure_ascii=False, separators=(",", ":"))
        + "\nHost catalog:\n"
        + stable_json(catalog_context(profile))
    )
    for source, target in zip(request.messages, messages[1:], strict=True):
        if source.agent_calls:
            target["content"] = stable_json(source.agent_calls[0].request)
    if "agent_definition_generate" in profile.operations:
        messages[0]["content"] += DEFINITION_GUIDANCE
    messages[0]["content"] += PARAMETER_GUIDANCE
    return messages


class MLXBackend:
    def __init__(self, client: httpx.AsyncClient, config):
        self.client = client
        self.config = config

    def build_request(self, request, messages, profile):
        if request.model != self.config.model:
            raise ALPError("MODEL_NOT_AVAILABLE", "The requested model is not configured.", 404)
        return {
            "model": self.config.upstream_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": request.top_p,
            **({"seed": request.seed} if request.seed is not None else {}),
            "enable_thinking": self.config.chat_template_kwargs.get("enable_thinking", False),
            "chat_template_kwargs": self.config.chat_template_kwargs,
            "reasoning_budget_tokens": self.config.reasoning_budget_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "alp_action",
                    "strict": True,
                    "schema": json.loads(profile.grammar),
                },
            },
        }

    async def generate(self, request, messages, profile, raw_request=None):
        body = self.build_request(request, messages, profile)
        try:
            async with self.client.stream("POST", "/v1/chat/completions", json=body) as response:
                if response.status_code != 200:
                    # Provider messages may include prompts or credentials.
                    raise ALPError(
                        "BACKEND_GENERATION_FAILED",
                        "MLX-Serve rejected the request.",
                        502,
                        [{"upstream_status": response.status_code}],
                    )
                async for chunk in decode_native_stream(response.aiter_text()):
                    yield chunk
        except httpx.HTTPError as exc:
            raise ALPError("BACKEND_UNAVAILABLE", "MLX-Serve transport failed.", 502) from exc
