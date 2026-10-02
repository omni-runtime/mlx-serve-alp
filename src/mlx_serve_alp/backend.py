from __future__ import annotations

import httpx
from vllm_alp.backends.native import decode_native_stream
from vllm_alp.catalog import stable_json
from vllm_alp.decoding_state import context_for
from vllm_alp.errors import ALPError
from vllm_alp.rendering import render_messages as render_alp_messages


def render_messages(request, profile, contracts):
    return render_alp_messages(request, profile, contracts, codec="canonical")


class MLXBackend:
    def __init__(self, client: httpx.AsyncClient, config):
        self.client = client
        self.config = config

    async def validate_model(self):
        """Check the currently loaded model, rather than treating engine health as text support."""
        try:
            response = await self.client.get("/v1/models")
            response.raise_for_status()
            models = response.json()["data"]
            if not isinstance(models, list) or any(not isinstance(m, dict) for m in models):
                raise ValueError("Invalid model list")
            model = next((m for m in models if m.get("id") == self.config.upstream_model), None)
            if model is None:
                raise ALPError("MODEL_NOT_AVAILABLE", "The configured MLX model is not advertised.", 404)
            capabilities = model.get("capabilities")
            if capabilities is not None and (
                not isinstance(capabilities, list) or any(not isinstance(c, str) for c in capabilities)
            ):
                raise ValueError("Invalid capabilities")
            if capabilities is not None and not {"chat", "json_schema"}.issubset(capabilities):
                raise ALPError(
                    "UNSUPPORTED_MODEL_CAPABILITIES",
                    "ALP generation requires a chat model with JSON-schema output support.", 422,
                )
            if capabilities is None or "alp_strict_grammar_v1" not in capabilities:
                raise ALPError(
                    "STRICT_GRAMMAR_UNAVAILABLE",
                    "This ALP adapter requires the native strict token-mask bridge.", 503,
                )
        except httpx.HTTPError as exc:
            raise ALPError("BACKEND_UNAVAILABLE", "Cannot inspect MLX model capabilities.", 502) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise ALPError("INVALID_BACKEND_RESPONSE", "Invalid MLX model capability response.", 502) from exc

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
                    "schema": {"type": "object", "x-alp-ebnf": stable_json({
                        "grammar": profile.grammar, "context": context_for(profile, "canonical"),
                    })},
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
