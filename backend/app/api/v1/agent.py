from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.controller import AgentController
from app.core.config import get_settings

router = APIRouter()

class AgentRequest(BaseModel):
    goal: str = Field(..., description="The instruction or goal for the Agent.")
    dry_run: bool = Field(
        default=True,
        description=(
            "When true (default), write-capable tools (ingest_tenders, "
            "ingest_awards, download_dossiers) validate inputs and report "
            "what would happen without hitting the live TED API or writing "
            "to the database. Set to false to allow live writes."
        ),
    )

class AgentStep(BaseModel):
    tool: str
    # Raw tool input as the model supplied it. Heterogeneous across tools
    # (e.g. find_matches → {"tender_id": int}, query_db → {"sql_query": str}),
    # so `dict[str, Any]` is the honest shape — the per-tool field types live in
    # the tool schemas in app/agent/tools.py, not here.
    args: dict[str, Any]

class AgentResponse(BaseModel):
    goal: str
    steps: list[AgentStep]
    output: str
    truncated: bool = False

@router.post("/run", response_model=AgentResponse)
def run_agent(request: AgentRequest):
    """
    Execute the Agent Controller with a user goal.
    This runs synchronously and returns the fully evaluated steps and final text.
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=500,
            detail="Server is not configured with an ANTHROPIC_API_KEY."
        )

    agent = AgentController(api_key=settings.anthropic_api_key, dry_run=request.dry_run)

    try:
        # Run the tool-loop
        result = agent.run(user_goal=request.goal)

        return AgentResponse(
            goal=result["goal"],
            steps=[AgentStep(tool=step["tool"], args=step["args"]) for step in result["steps"]],
            output=result["output"],
            truncated=result.get("truncated", False)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")
