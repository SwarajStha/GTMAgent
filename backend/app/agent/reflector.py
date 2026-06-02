"""Reflection loop for self-improvement.

This script queries the latest AgentRuns and feedback scores,
passes them to Claude, and asks for a diagnostic summary of
the agent's operational quality (e.g. drift in matches).
"""
from __future__ import annotations

import anthropic
from app.db.session import SessionLocal
from app.db.models import AgentRun, Feedback

REFLECTION_PROMPT = """You are the GTM Agent Reflection mechanism.
Your job is to review the logs of recent Agent Runs and the latest email feedback from users.
Given the following JSON blob of recent activity, provide a brief operational summary:
1. What tasks were executed today?
2. Are there any anomalies in matching or parsing?
3. What is the average feedback score?
4. Are there concrete suggestions to improve the LR weights or CPV filters?
"""

class Reflector:
    def __init__(self, model: str = "claude-3-5-sonnet-20241022", api_key: str | None = None) -> None:
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key)

    def run_daily_summary(self) -> str:
        """Fetch recent DB state and ask Claude to reflect."""
        with SessionLocal() as db:
            recent_runs = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(10).all()
            runs_data = [{"goal": r.goal, "steps": r.steps, "output": r.output} for r in recent_runs]
            
            recent_feedback = db.query(Feedback).order_by(Feedback.created_at.desc()).limit(50).all()
            feedback_data = [{"rating": f.rating, "comment": f.comment} for f in recent_feedback]

        activity_json = {
            "runs": runs_data,
            "feedback": feedback_data
        }

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=REFLECTION_PROMPT,
            messages=[
                {"role": "user", "content": f"Here is the recent activity data:\n{activity_json}"}
            ]
        )
        return response.content[0].text

if __name__ == "__main__":
    reflector = Reflector()
    print("Running reflection loop...")
    summary = reflector.run_daily_summary()
    print("=== Daily Summary ===")
    print(summary)
