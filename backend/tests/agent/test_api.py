import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app

client = TestClient(app)

@patch("app.api.v1.agent.AgentController")
def test_post_agent_run(mock_agent_class):
    # Mocking the AgentController instance and its run method
    mock_instance = mock_agent_class.return_value
    mock_instance.run.return_value = {
        "goal": "Test API goal",
        "steps": [{"tool": "test_tool", "args": {"key": "val"}}],
        "output": "Mocked successful output"
    }

    # For this test, bypass API Key checks safely by using the env or 
    # we can just run the test and app behavior as config is loaded globally.

    response = client.post(
        "/api/v1/agent/run",
        json={"goal": "Test API goal"}
    )
    
    # If the environment does not have ANTHROPIC_API_KEY set, this would fail with 500
    # To handle that, we mock settings
    with patch("app.api.v1.agent.get_settings") as mock_settings:
        mock_settings.return_value.anthropic_api_key = "dummy_key_for_api_test"
        
        response = client.post(
            "/api/v1/agent/run",
            json={"goal": "Test API goal"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["goal"] == "Test API goal"
        assert data["output"] == "Mocked successful output"
        assert len(data["steps"]) == 1
        assert data["steps"][0]["tool"] == "test_tool"

