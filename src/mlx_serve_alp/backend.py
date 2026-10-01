from __future__ import annotations

import json

import httpx
from vllm_alp.backends.native import decode_native_stream
from vllm_alp.errors import ALPError
from vllm_alp.rendering import render_messages as render_alp_messages


def render_messages(request, profile, contracts):
    return render_alp_messages(request, profile, contracts, codec="canonical")


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
