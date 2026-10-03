from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from .catalog import CatalogRegistry
from .constraints import CompiledProfile
from .errors import ALPError
from .parser import ALPParser
from .protocol import AgentCall, ALPChatRequest, ALPChatResponse, AssistantMessage, Choice
from .rendering import render_messages
from .streaming import GenerationBackend
from .task_context import bind_task_constraints

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedRequest:
    request: ALPChatRequest
    profile: CompiledProfile
    messages: list[dict]
    response_id: str
    call_id: str


class ALPServing:
    def __init__(
        self,
        backend: GenerationBackend,
        registry: CatalogRegistry,
        compiler,
        *,
        parser_factory=ALPParser,
        renderer=render_messages,
    ):
        self.backend = backend
        self.registry = registry
        self.parser_factory = parser_factory
        self.renderer = renderer
        self.compiler = compiler

    async def prepare(self, request: ALPChatRequest, raw_request=None) -> PreparedRequest:
        catalog = await self.registry.resolve(request.alp.catalog_ref, raw_request)
        catalog = bind_task_constraints(request, catalog, self.registry.config, raw_request)
        profile = await asyncio.to_thread(self.compiler.compile, request.alp, catalog)
        messages = self.renderer(request, profile, self.compiler.contracts)
        return PreparedRequest(
            request, profile, messages, "alpchat_" + uuid.uuid4().hex, "ac_" + uuid.uuid4().hex
        )

    async def events(self, prepared: PreparedRequest, raw_request=None):
        """A candidate becomes an accepted call only after the entire native stream."""
        parser = self.parser_factory(prepared.profile, self.compiler.contracts)
        yield {
            "type": "agent_call.started",
            "id": prepared.response_id,
            "call_id": prepared.call_id,
        }
        finish_reason = None
        usage = None
        source = self.backend.generate(
            prepared.request, prepared.messages, prepared.profile, raw_request
        )
        try:
            async for chunk in source:
                if chunk.reasoning and not self.registry.config.allow_reasoning:
                    raise ALPError(
                        "UNEXPECTED_REASONING",
                        "This ALP deployment has not enabled a separate reasoning channel.",
                        502,
                    )
                if chunk.text:
                    if finish_reason is not None:
                        raise ALPError(
                            "OUTPUT_AFTER_FINISH",
                            "The backend emitted action content after finishing.",
                            502,
                        )
                    parser.feed(chunk.text)
                    yield {
                        "type": "agent_call.arguments.delta",
                        "call_id": prepared.call_id,
                        "delta": chunk.text,
                        "provisional": True,
                    }
                if chunk.finish_reason is not None:
                    if finish_reason is not None:
                        raise ALPError(
                            "DUPLICATE_FINISH", "The backend finished the same choice twice.", 502
                        )
                    finish_reason = chunk.finish_reason
                if chunk.usage is not None:
                    usage = chunk.usage
            canonical = parser.finish(finish_reason)
            from .host_contracts import task_constraint_coverage, validation_scope

            response = ALPChatResponse(
                id=prepared.response_id,
                created=int(time.time()),
                model=prepared.request.model,
                choices=[
                    Choice(
                        message=AssistantMessage(
                            agent_calls=[AgentCall(id=prepared.call_id, request=canonical)]
                        )
                    )
                ],
                usage=usage,
                alp={
                    "protocol_version": "0.3.0",
                    "constraint_digest": prepared.profile.digest,
                    "validated": True,
                    "executed": False,
                    "authorized": False,
                    "residual_check_count": len(prepared.profile.residual_checks),
                    "validation_scope": validation_scope(canonical, prepared.profile.catalog),
                    "task_constraint_coverage": task_constraint_coverage(
                        canonical, prepared.profile.catalog,
                    ),
                },
                raw=parser.raw if prepared.request.include_raw else None,
            )
            yield {
                "type": "agent_call.completed",
                "call_id": prepared.call_id,
                "response": response.model_dump(exclude_none=True),
            }
        except ALPError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Do not log upstream exception strings, which may embed user data.
            logger.error("ALP native generation failed: %s", type(exc).__name__)
            raise ALPError(
                "BACKEND_GENERATION_FAILED", "The native generation failed.", 502
            ) from exc
        finally:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    async def complete(self, prepared: PreparedRequest, raw_request=None) -> dict:
        events = self.events(prepared, raw_request)
        try:
            async for event in events:
                if event["type"] == "agent_call.completed":
                    return event["response"]
        finally:
            await events.aclose()
        raise ALPError("INCOMPLETE_GENERATION", "No completed ALP call was produced.", 502)
