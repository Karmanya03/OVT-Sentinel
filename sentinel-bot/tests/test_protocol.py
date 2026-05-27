import json
import pytest
from core.protocol import AgentMessage, parse_agent_message, make_bot_message


def test_agent_message_dataclass():
    msg = AgentMessage(type="test", payload={"key": "value"})
    assert msg.type == "test"
    assert msg.payload == {"key": "value"}


def test_parse_agent_message_standard():
    raw = json.dumps({"type": "command_output", "data": "hello"})
    msg = parse_agent_message(raw)
    assert msg.type == "command_output"
    assert msg.payload == {"type": "command_output", "data": "hello"}


def test_parse_agent_message_missing_type():
    raw = json.dumps({"data": "no type"})
    msg = parse_agent_message(raw)
    assert msg.type == "unknown"


def test_parse_agent_message_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        parse_agent_message("not json")


def test_parse_agent_message_empty_object():
    raw = json.dumps({})
    msg = parse_agent_message(raw)
    assert msg.type == "unknown"
    assert msg.payload == {}


def test_make_bot_message_basic():
    result = make_bot_message("status_snapshot", cpu_percent=42.5)
    assert result["type"] == "status_snapshot"
    assert result["cpu_percent"] == 42.5


def test_make_bot_message_type_override():
    result = make_bot_message("hello", type="world")
    assert result["type"] == "world"


def test_make_bot_message_no_extra():
    result = make_bot_message("ping")
    assert result == {"type": "ping"}
