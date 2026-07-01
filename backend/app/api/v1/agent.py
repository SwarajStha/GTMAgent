import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.controller import AgentController
from app.core.config import get_settings
from app.core.rate_limit import llm_rate_limit

router = APIRouter()

# Generous cap on free-text input: large enough for any real goal/reply (a pasted
# tender description is well under this), small enough that a single request can't
# balloon the per-turn token cost. Over-limit → 422 (P1 — Unbounded Consumption).
_MAX_INPUT_CHARS = 8000


class AgentRequest(BaseModel):
    goal: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_INPUT_CHARS,
        description="The instruction or goal for the Agent.",
    )
    dry_run: bool = Field(
        default=True,
        description=(
            "When true (default), the caged write tools (ingest_tenders, "
            "ingest_awards) make NO live TED call and report what they would do. "
            "Set to false to allow bounded live ingestion as a fallback."
        ),
    )


class ContinueRequest(BaseModel):
    reply: str = Field(
        ...,
        min_length=1,
        max_length=_MAX_INPUT_CHARS,
        description="The user's answer to a pending ask_user question.",
    )


def _sse(event: dict[str, Any]) -> str:
    """Serialize one event as an SSE `data:` frame."""
    return f"data: {json.dumps(event)}\n\n"


# Disable proxy/server response buffering so events flush immediately.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("/run", dependencies=[Depends(llm_rate_limit)])
def run_agent(request: AgentRequest) -> StreamingResponse:
    """Run the agent for a goal, streaming progress as Server-Sent Events.

    Emits `status` / `step` / `awaiting_input` / `final` / `error` events. On
    `awaiting_input` the stream closes and the run can be resumed via
    `POST /run/{session_id}/continue`.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="Server is not configured with an ANTHROPIC_API_KEY.",
        )

    controller = AgentController(api_key=settings.anthropic_api_key, dry_run=request.dry_run)

    def gen():
        try:
            for event in controller.stream_run(request.goal):
                yield _sse(event)
        except Exception as e:  # noqa: BLE001 — surface as a stream event, don't 500 mid-stream
            yield _sse({"type": "error", "message": f"Agent execution failed: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/run/{session_id}/continue", dependencies=[Depends(llm_rate_limit)])
def continue_agent(session_id: str, request: ContinueRequest) -> StreamingResponse:
    """Resume a paused agent run with the user's answer (SSE, same event shape)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="Server is not configured with an ANTHROPIC_API_KEY.",
        )

    # dry_run is restored from the persisted session inside stream_continue.
    controller = AgentController(api_key=settings.anthropic_api_key)

    def gen():
        try:
            for event in controller.stream_continue(session_id, request.reply):
                yield _sse(event)
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "message": f"Agent execution failed: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


class ReflectResponse(BaseModel):
    id: str
    metrics: dict[str, Any]
    actions: dict[str, Any]
    narrative: str


@router.post(
    "/reflect", response_model=ReflectResponse, dependencies=[Depends(llm_rate_limit)]
)
def run_reflection(act: bool = True):
    """Run one reflection cycle (G9): compute operational metrics, optionally
    retrain the matching LR from accumulated feedback (the weights lever), and
    persist a `reflections` row.

    `act=true` (default) actuates the feedback-driven retrain; `act=false` only
    observes + narrates. Needs no ANTHROPIC_API_KEY — falls back to a
    deterministic narrative when none is configured.
    """
    from app.agent.reflector import Reflector

    try:
        result = Reflector().reflect(act=act)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reflection failed: {str(e)}")
    return ReflectResponse(**result)
