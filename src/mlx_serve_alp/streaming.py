"""MLX text-stream decoding and generation interface."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from .constraints import CompiledProfile
from .errors import ALPError
from .protocol import ALPChatRequest


@dataclass(frozen=True)
class GenerationChunk:
    text: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    reasoning: str = ""


class GenerationBackend(Protocol):
    def generate(
        self,
        request: ALPChatRequest,
        messages: list[dict],
        profile: CompiledProfile,
        raw_request: Any = None,
    ) -> AsyncIterator[GenerationChunk]: ...


def _decode_event(value: dict) -> list[GenerationChunk]:
    if "error" in value or value.get("object") == "error":
        raise ALPError(
            "BACKEND_GENERATION_FAILED", "The native serving handler rejected the generation.", 502
        )
    chunks = []
    choices = value.get("choices", [])
    if len(choices) > 1:
        raise ALPError(
            "INVALID_BACKEND_RESPONSE", "ALP accepts exactly one completion choice.", 502
        )
    for choice in choices:
        if choice.get("index", 0) != 0:
            raise ALPError("INVALID_BACKEND_RESPONSE", "Unexpected completion index.", 502)
        delta = choice.get("delta", choice.get("message", {})) or {}
        if delta.get("tool_calls"):
            raise ALPError(
                "UNEXPECTED_TOOL_PROJECTION",
                "The backend returned tool_calls instead of ALP content.",
                502,
            )
        content = delta.get("content") or ""
        reasoning = delta.get("reasoning", delta.get("reasoning_content")) or ""
        if not isinstance(content, str) or not isinstance(reasoning, str):
            raise ALPError(
                "INVALID_BACKEND_RESPONSE", "The backend must return a text action channel.", 502
            )
        chunks.append(GenerationChunk(content, choice.get("finish_reason"), reasoning=reasoning))
    if value.get("usage") is not None:
        chunks.append(GenerationChunk(usage=value["usage"]))
    return chunks


async def decode_native_stream(stream: AsyncIterator[str]) -> AsyncIterator[GenerationChunk]:
    """Decode native handler SSE, even when a transport event is split/coalesced."""
    pending = ""
    done = False
    async for piece in stream:
        if not isinstance(piece, str):
            raise ALPError(
                "INVALID_BACKEND_RESPONSE", "The native SSE stream must contain strings.", 502
            )
        if done and piece.strip():
            raise ALPError(
                "OUTPUT_AFTER_DONE", "The backend emitted data after its completion marker.", 502
            )
        pending += piece
        if len(pending.encode()) > 2 * 1024 * 1024:
            raise ALPError("BACKEND_EVENT_TOO_LARGE", "The native stream event is too large.", 502)
        pending = pending.replace("\r\n", "\n")
        while "\n\n" in pending:
            event, pending = pending.split("\n\n", 1)
            data = "\n".join(
                line[5:].lstrip(" ") for line in event.splitlines() if line.startswith("data:")
            )
            if not data:
                continue
            if done:
                raise ALPError(
                    "OUTPUT_AFTER_DONE",
                    "The backend emitted data after its completion marker.",
                    502,
                )
            if data == "[DONE]":
                done = True
                continue
            try:
                value = json.loads(data)
            except ValueError as exc:
                raise ALPError(
                    "INVALID_BACKEND_RESPONSE", "The native stream contains invalid JSON.", 502
                ) from exc
            if not isinstance(value, dict):
                raise ALPError(
                    "INVALID_BACKEND_RESPONSE", "The native stream event is not an object.", 502
                )
            for chunk in _decode_event(value):
                yield chunk
    if pending.strip() or not done:
        raise ALPError(
            "INCOMPLETE_BACKEND_STREAM", "The native stream ended without a complete boundary.", 502
        )
