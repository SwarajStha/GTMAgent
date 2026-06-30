"""API-level tests for the agent SSE endpoints.

The controller is mocked; these assert the endpoints stream the controller's
events as `text/event-stream` and guard on the missing API key.
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@patch("app.api.v1.agent.AgentController")
def test_post_agent_run_streams_sse(mock_agent_class):
    mock_instance = mock_agent_class.return_value
    mock_instance.stream_run.return_value = iter(
        [
            {"type": "status", "message": "Reading your request…", "session_id": "s1"},
            {"type": "step", "tool": "find_tender", "args": {"query": "school"}},
            {
                "type": "final",
                "session_id": "s1",
                "goal": "Test goal",
                "steps": [{"tool": "find_tender", "args": {"query": "school"}}],
                "output": "Resolved the tender and ranked suppliers.",
                "truncated": False,
            },
        ]
    )

    with patch("app.api.v1.agent.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = "dummy_key"
        response = client.post("/api/v1/agent/run", json={"goal": "Test goal"})

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    body = response.text
    assert '"type": "status"' in body
    assert '"type": "final"' in body
    assert "Resolved the tender" in body


@patch("app.api.v1.agent.AgentController")
def test_post_agent_continue_streams_sse(mock_agent_class):
    mock_instance = mock_agent_class.return_value
    mock_instance.stream_continue.return_value = iter(
        [
            {
                "type": "final",
                "session_id": "s1",
                "goal": "g",
                "steps": [],
                "output": "done",
                "truncated": False,
            }
        ]
    )

    with patch("app.api.v1.agent.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = "dummy_key"
        response = client.post(
            "/api/v1/agent/run/s1/continue", json={"reply": "5"}
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "done" in response.text
    mock_instance.stream_continue.assert_called_once_with("s1", "5")


def test_post_agent_run_requires_api_key():
    with patch("app.api.v1.agent.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = ""
        response = client.post("/api/v1/agent/run", json={"goal": "Test goal"})
    assert response.status_code == 500
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
