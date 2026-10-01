from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from functools import partial
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from vllm_alp.catalog import CatalogRegistry, ServerConfig
from vllm_alp.parser import ALPParser
from vllm_alp.serving import ALPServing
from vllm_alp.vllm_endpoint import ALPEndpointPlugin

from .backend import MLXBackend, render_messages
from .schema import MLXConstraintCompiler


class MLXConfig(ServerConfig):
    engine_url: str = "http://127.0.0.1:11236"
    model: str = "local/alp"
    upstream_model: str
    api_key_env: str = "MLX_ALP_API_KEY"
    upstream_api_key_env: str = "MLX_ALP_ENGINE_KEY"
    timeout_seconds: float = Field(default=300, gt=0, le=3600)
    max_concurrent: int = Field(default=1, ge=1, le=16)
    reasoning_budget_tokens: int = Field(default=512, ge=0, le=32768)

    @model_validator(mode="after")
    def local_engine(self):
        url = urlsplit(self.engine_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("MLX-Serve must be a loopback HTTP engine")
        if url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Use a loopback origin without embedded credentials")
        return self


class MLXServing(ALPServing):
    async def prepare(self, request, raw_request=None):
        if request.model != self.backend.config.model:
            from vllm_alp.errors import ALPError

            raise ALPError("MODEL_NOT_AVAILABLE", "The requested model is not configured.", 404)
        return await super().prepare(request, raw_request)

    async def events(self, prepared, raw_request=None):
        async for event in super().events(prepared, raw_request):
            if event["type"] == "agent_call.completed":
                event["response"]["alp"].update(
                    raw_format="canonical",
                    generation_constraint="mlx-serve-json-schema",
                    residual_checks=list(prepared.profile.residual_checks),
                )
            yield event


def create_app(config: MLXConfig, *, transport=None):
    import asyncio

    key = os.environ.get(config.api_key_env, "")
    engine_key = os.environ.get(config.upstream_api_key_env, "")
    if not key or not engine_key:
        raise ValueError("Both frontend and engine API key environment variables must be set")
    client = httpx.AsyncClient(
        base_url=config.engine_url,
        timeout=config.timeout_seconds,
        headers={"Authorization": "Bearer " + engine_key},
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )
    backend = MLXBackend(client, config)
    service = MLXServing(
        backend,
        CatalogRegistry(config),
        MLXConstraintCompiler(cache_size=config.compiler_cache_size),
        parser_factory=partial(ALPParser, codec="canonical"),
        renderer=render_messages,
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    app = FastAPI(title="MLX-Serve ALP", version="0.1.0", lifespan=lifespan)
    gate = asyncio.Semaphore(config.max_concurrent)

    # Pure ASGI wrapper keeps the semaphore held until the full stream closes.
    class Authentication:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http" or scope["path"] == "/health":
                return await self.app(scope, receive, send)
            values = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            if len(values) != 1 or not hmac.compare_digest(values[0], ("Bearer " + key).encode()):
                response = JSONResponse({"error": {"code": "UNAUTHORIZED"}}, status_code=401)
                return await response(scope, receive, send)
            async with gate:
                return await self.app(scope, receive, send)

    app.add_middleware(Authentication)

    class Endpoint(ALPEndpointPlugin):
        async def _service(self, state):
            return service

    Endpoint(config=config).attach_router(app)

    @app.get("/health")
    async def health():
        try:
            response = await client.get("/health", timeout=5)
            response.raise_for_status()
        except httpx.HTTPError:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok", "model": config.model, "raw_format": "canonical"}

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": config.model, "object": "model"}]}

    return app
