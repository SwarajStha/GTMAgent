"""Agent Controller — Claude tool-use orchestrator."""
from __future__ import annotations

import json
from typing import Any
import anthropic
from app.db.session import SessionLocal
from app.db.models import AgentRun
from app.agent.tools import AGENT_TOOLS, dispatch_tool

SYSTEM_PROMPT = """You are the GTM Agent Orchestrator. 
Your goal is to fulfill user requests related to public procurement matching by executing a sequence of tool calls.
1. Formulate a plan.
2. Execute proper tools.
3. Review the outputs.
4. Summarise the results back to the user.
Always use tool calls to interact with data. Think step-by-step before invoking multiple tools.
"""

ANTHROPIC_TOOLS = [
    {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"]
    }
    for tool in AGENT_TOOLS
]

class AgentController:
    """Top-level orchestrator that turns user goals into tool calls."""

    def __init__(self, model: str = "claude-3-5-sonnet-20241022", api_key: str | None = None) -> None:
        self.model = model
        self.client = anthropic.Anthropic(
            api_key=api_key
        )

    def run(self, user_goal: str) -> dict[str, Any]:
        """Runs the planner-executor tool loop for a given user goal."""
        messages = [
            {"role": "user", "content": user_goal}
        ]
        
        steps_taken = []
        final_output = ""

        # Main tool-use loop
        with SessionLocal() as db_session:
            while True:
                response = self.client.messages.create(
                    model=self.model,
                    system=SYSTEM_PROMPT,
                    max_tokens=4096,
                    messages=messages,
                    tools=ANTHROPIC_TOOLS
                )
                
                # Append assistant's response to messages to maintain conversation context
                messages.append(
                    {"role": "assistant", "content": response.content}
                )
                
                if response.stop_reason == "tool_use":
                    # Assistant wants to call one or more tools
                    tool_results = []
                    
                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_args = block.input
                            
                            steps_taken.append({"tool": tool_name, "args": tool_args})
                            
                            # Dispatch to our internal functions
                            result_str = dispatch_tool(tool_name, tool_args, db_session)
                            
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_str
                            })
                            
                    # Append tool results as a single user message
                    messages.append({
                        "role": "user",
                        "content": tool_results
                    })
                else:
                    # Agent is done
                    for block in response.content:
                        if block.type == "text":
                            final_output += block.text
                    break
            
            # Save the run to db
            run_record = AgentRun(
                goal=user_goal,
                steps=steps_taken,
                output=final_output
            )
            db_session.add(run_record)
            db_session.commit()
            
        return {
            "goal": user_goal,
            "steps": steps_taken,
            "output": final_output
        }
