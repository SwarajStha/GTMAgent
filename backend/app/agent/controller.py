"""Agent Controller — Claude tool-use orchestrator."""
from __future__ import annotations

from typing import Any

import anthropic

from app.agent.tools import AGENT_TOOLS, dispatch_tool
from app.db.models import AgentRun
from app.db.session import SessionLocal

SYSTEM_PROMPT = """You are the GTM Agent Orchestrator.
Your goal is to fulfill user requests related to public procurement matching
by executing a sequence of tool calls.
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

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        dry_run: bool = True,
        max_turns: int = 20,
    ) -> None:
        self.model = model
        self.client = anthropic.Anthropic(
            api_key=api_key
        )
        # Safety default: write-capable tools (ingest_*, download_dossiers)
        # run in dry-run mode unless the caller explicitly opts in to live
        # writes. This prevents a casual chat goal ("find me a tender") from
        # silently triggering a live TED poll / dossier download / DB write.
        self.dry_run = dry_run
        self.max_turns = max_turns

    def run(self, user_goal: str) -> dict[str, Any]:
        """Runs the planner-executor tool loop for a given user goal."""
        messages = [
            {"role": "user", "content": user_goal}
        ]

        steps_taken: list[dict[str, Any]] = []
        final_output = ""
        truncated = False

        # Main tool-use loop
        turns = 0
        with SessionLocal() as db_session:
            while True:
                turns += 1
                if turns > self.max_turns:
                    # Don't blow up the request — return whatever the agent
                    # accomplished so far, with a note explaining why it
                    # stopped early. The caller can inspect `steps` to see
                    # exactly how far the plan got.
                    truncated = True
                    final_output = (
                        f"[Agent stopped after {self.max_turns} turns without "
                        "reaching a final answer. Partial progress below.]\n"
                        + final_output
                    )
                    break

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
                            # The SDK types `block.input` as `object`; a tool
                            # input is always a JSON object, so normalise it to
                            # a dict for typed dispatch and a well-formed
                            # AgentStep in the response.
                            tool_args: dict[str, Any] = (
                                block.input if isinstance(block.input, dict) else {}
                            )

                            steps_taken.append({"tool": tool_name, "args": tool_args})

                            # Dispatch to our internal functions
                            result_str = dispatch_tool(
                                tool_name, tool_args, db_session, dry_run=self.dry_run
                            )

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

            # Save the run to db (including truncated runs — they're useful
            # for the reflection loop too)
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
            "output": final_output,
            "truncated": truncated,
        }
