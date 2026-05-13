"""Agent Controller — Claude tool-use orchestrator.

Exposes the ingestion, matching, and generation modules as Claude
tools and lets the model drive multi-step workflows ("find me top 5
matches for tender X and draft outreach for the best one").
"""
from __future__ import annotations


class AgentController:
    """Top-level orchestrator that turns user goals into tool calls."""

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model

    # TODO: Phase 6 — register tool schemas and run the tool-use loop
    def run(self, user_goal: str) -> dict:
        ...
