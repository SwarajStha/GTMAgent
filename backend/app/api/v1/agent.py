from typing import Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.controller import AgentController
from app.core.config import get_settings

router = APIRouter()

class AgentRequest(BaseModel):
    goal: str = Field(..., description="The instruction or goal for the Agent.")

class AgentStep(BaseModel):
    tool: str
    args: dict[str, Any]

class AgentResponse(BaseModel):
    goal: str
    steps: List[AgentStep]
    output: str

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

    agent = AgentController(api_key=settings.anthropic_api_key)
    
    try:
        # Run the tool-loop
        result = agent.run(user_goal=request.goal)
        
        return AgentResponse(
            goal=result["goal"],
            steps=[AgentStep(tool=step["tool"], args=step["args"]) for step in result["steps"]],
            output=result["output"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}")
