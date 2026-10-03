from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from .errors import ALPError
from .protocol import ALPChatRequest
from .serving import ALPServing

ROUTE = "/v1/alp/chat/completions"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


async def read_request(request: Request, max_bytes: int) -> ALPChatRequest:
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > max_bytes:
            raise ALPError("REQUEST_TOO_LARGE", "The request exceeds the deployment limit.", 413)
        raw.extend(chunk)
    try:
        body = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")),
        )
        return ALPChatRequest.model_validate(body)
    except (ValueError, RecursionError) as exc:
        details = []
        if isinstance(exc, ValidationError):
            details = [
                {"path": "/" + "/".join(map(str, e["loc"])), "rule": e["type"]}
                for e in exc.errors()[:32]
            ]
        raise ALPError(
            "INVALID_REQUEST", "The request does not match the ALP calling API.", 422, details
        ) from exc


def _sse(event: dict) -> str:
    return (
        "event: "
        + event["type"]
        + "\ndata: "
        + json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n\n"
    )


def attach_alp_route(app: FastAPI, service: ALPServing) -> None:
    if any(getattr(route, "path", None) == ROUTE for route in app.routes):
        raise RuntimeError("ALP endpoint route collision")

    @app.post(ROUTE, tags=["ALP calling"])
    async def create_alp_completion(request: Request):
        try:
            body = await read_request(request, service.registry.config.max_request_bytes)
            prepared = await service.prepare(body, request)
            if not body.stream:
                return JSONResponse(await service.complete(prepared, request))

            async def stream():
                source = service.events(prepared, request)
                try:
                    async for event in source:
                        yield _sse(event)
                except ALPError as exc:
                    yield _sse(
                        {
                            "type": "agent_call.failed",
                            "call_id": prepared.call_id,
                            **exc.envelope(),
                        }
                    )
                finally:
                    await source.aclose()

            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        except ALPError as exc:
            return JSONResponse(exc.envelope(), status_code=exc.status)
