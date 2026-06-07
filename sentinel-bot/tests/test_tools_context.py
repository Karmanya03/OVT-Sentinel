import pytest

from core import tools as tools_module


class _Msg:
    def __init__(self, msg_type, payload=None):
        self.type = msg_type
        self.payload = payload or {}


class _DummyClient:
    async def run_command(self, command):
        yield _Msg("command_output", {"data": f"ran:{command}"})
        yield _Msg("command_complete", {})


class _DummyAgentManager:
    def __init__(self):
        self.requested_user = None
        self.client = _DummyClient()

    async def get_agent_for_user(self, user_id, default_fallback=True):
        self.requested_user = user_id
        return self.client

    def get_active(self):
        raise AssertionError("get_active should not be used when tool user context is set")


@pytest.mark.asyncio
async def test_tools_execute_against_calling_user_connected_vm():
    agent_manager = _DummyAgentManager()
    tools_module.init_tools(agent_manager, memory=None)
    tools_module.set_tool_user_context("user-123")

    all_tools = tools_module.build_langchain_tools()
    run_bash = next(t for t in all_tools if t.name == "run_bash_command")

    result = await run_bash.ainvoke({"command": "whoami"})

    assert "ran:whoami" in result
    assert agent_manager.requested_user == "user-123"