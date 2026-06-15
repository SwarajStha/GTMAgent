import pytest
from unittest.mock import MagicMock, patch
from app.db.models import AgentRun
from app.agent.controller import AgentController
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

# A dummy response mimicking what Anthropic might return when it wants to use a tool
def mock_anthropic_message_tool_use(*args, **kwargs):
    block = ToolUseBlock(
        id="toolu_123",
        name="query_db",
        input={"sql_query": "SELECT * FROM public.tenders LIMIT 1"},
        type="tool_use"
    )
    # The SDK creates message objects where content is a list of blocks
    return Message(
        id="msg_123",
        content=[block],
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        stop_reason="tool_use",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=10, output_tokens=10)
    )

# A dummy response mimicking Anthropic finishing the task
def mock_anthropic_message_final(*args, **kwargs):
    block = TextBlock(
        text="I have checked the database and found the information you need.",
        type="text"
    )
    return Message(
        id="msg_456",
        content=[block],
        model="claude-3-5-sonnet-20241022",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=Usage(input_tokens=15, output_tokens=20)
    )

class MockMessages:
    def __init__(self):
        self.call_count = 0

    def create(self, *args, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return mock_anthropic_message_tool_use()
        return mock_anthropic_message_final()

class MockClient:
    def __init__(self, *args, **kwargs):
        self.messages = MockMessages()


class EndlessToolUseMessages:
    """Always asks for another tool call — never reaches `end_turn`.

    Used to exercise the max_turns guard without a real multi-turn
    conversation.
    """

    def create(self, *args, **kwargs):
        return mock_anthropic_message_tool_use()


class EndlessToolUseClient:
    def __init__(self, *args, **kwargs):
        self.messages = EndlessToolUseMessages()


@patch("anthropic.Anthropic", new=MockClient)
@patch("app.agent.controller.dispatch_tool")
@patch("app.agent.controller.SessionLocal")
def test_agent_controller_tool_loop(mock_session_local, mock_dispatch):
    """
    Test the multi-step tool-use loop of the AgentController.
    """
    # Arrange
    mock_dispatch.return_value = "Mocked result from DB"
    
    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session
    
    agent = AgentController(api_key="dummy_key_for_test")
    goal = "Find me a tender"
    
    # Act
    result = agent.run(user_goal=goal)
    
    # Assert
    # 1. Check returned structure
    assert result["goal"] == goal
    assert result["output"] == "I have checked the database and found the information you need."
    
    # 2. Check that the steps were logged correctly
    assert len(result["steps"]) == 1
    assert result["steps"][0]["tool"] == "query_db"
    assert "sql_query" in result["steps"][0]["args"]
    
    # 3. Verify exactly one tool was dispatched
    mock_dispatch.assert_called_once()
    
    # 4. Verify it was correctly saved to the DB
    mock_db_session.add.assert_called_once()


@patch("anthropic.Anthropic", new=MockClient)
@patch("app.agent.controller.dispatch_tool")
@patch("app.agent.controller.SessionLocal")
def test_agent_controller_defaults_to_dry_run(mock_session_local, mock_dispatch):
    """
    AgentController must default to dry_run=True and forward it to
    dispatch_tool, so a casual chat goal can't trigger live writes
    (live TED polls / dossier downloads / DB writes) by accident.
    """
    mock_dispatch.return_value = "Mocked result from DB"

    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session

    agent = AgentController(api_key="dummy_key_for_test")
    assert agent.dry_run is True

    agent.run(user_goal="Find me a tender")

    mock_dispatch.assert_called_once()
    _, kwargs = mock_dispatch.call_args
    assert kwargs["dry_run"] is True


@patch("anthropic.Anthropic", new=MockClient)
@patch("app.agent.controller.dispatch_tool")
@patch("app.agent.controller.SessionLocal")
def test_agent_controller_forwards_explicit_live_mode(mock_session_local, mock_dispatch):
    """An explicit dry_run=False must reach dispatch_tool unchanged."""
    mock_dispatch.return_value = "Mocked result from DB"

    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session

    agent = AgentController(api_key="dummy_key_for_test", dry_run=False)
    agent.run(user_goal="Ingest today's tenders for real")

    _, kwargs = mock_dispatch.call_args
    assert kwargs["dry_run"] is False


@patch("anthropic.Anthropic", new=EndlessToolUseClient)
@patch("app.agent.controller.dispatch_tool")
@patch("app.agent.controller.SessionLocal")
def test_agent_controller_truncates_gracefully_after_max_turns(mock_session_local, mock_dispatch):
    """
    A plan that never reaches `end_turn` must stop after `max_turns` and
    return partial results — not raise and 500 the request.
    """
    mock_dispatch.return_value = "Mocked result from DB"

    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session

    agent = AgentController(api_key="dummy_key_for_test", max_turns=3)
    result = agent.run(user_goal="Loop forever")

    # Should not raise — returns partial progress with a truncation flag.
    assert result["truncated"] is True
    assert "max_turns" not in result["output"]  # human-readable note, not the raw attr name
    assert "stopped after 3 turns" in result["output"]
    assert len(result["steps"]) == 3

    # The (truncated) run is still persisted for the reflection loop.
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_called_once()
