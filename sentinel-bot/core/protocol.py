from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class AgentMessage:
    type: str
    payload: Dict[str, Any]


def parse_agent_message(raw: str) -> AgentMessage:
    import json

    obj = json.loads(raw)
    msg_type = obj.get("type", "unknown")
    return AgentMessage(type=msg_type, payload=obj)


def make_bot_message(msg_type: str, **kwargs: Any) -> Dict[str, Any]:
    payload = {"type": msg_type}
    payload.update(kwargs)
    return payload
