from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_manager import AgentManager, NoAgentError


@pytest.fixture
def manager():
    return AgentManager(uri="ws://localhost:7331", token="test_token")


class TestAgentManager:
    def test_init(self, manager):
        assert manager._uri == "ws://localhost:7331"
        assert manager._token == "test_token"
        assert manager._agents == {}
        assert manager._active is None

    @pytest.mark.asyncio
    async def test_add_agent_success(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.name = "agent1"
            agent = await manager.add_agent("agent1")
            assert agent is instance
            assert "agent1" in manager._agents
            instance.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_agent_default_name(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            agent = await manager.add_agent()
            assert agent is instance
            assert "default" in manager._agents

    @pytest.mark.asyncio
    async def test_add_agent_failure(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock(side_effect=ConnectionError("refused"))
            with pytest.raises(ConnectionError):
                await manager.add_agent("agent1")
            assert "agent1" not in manager._agents

    @pytest.mark.asyncio
    async def test_get_agent_found_connected(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.is_connected = True
            manager._agents["agent1"] = instance
            result = await manager.get_agent("agent1")
            assert result is instance

    @pytest.mark.asyncio
    async def test_get_agent_found_reconnects(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.is_connected = False
            manager._agents["agent1"] = instance
            result = await manager.get_agent("agent1")
            assert result is instance
            instance.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, manager):
        result = await manager.get_agent("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_agent(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.close = AsyncMock()
            manager._agents["agent1"] = instance
            manager._active = "agent1"
            await manager.remove_agent("agent1")
            assert "agent1" not in manager._agents
            assert manager._active is None

    @pytest.mark.asyncio
    async def test_remove_agent_nonexistent(self, manager):
        await manager.remove_agent("ghost")
        assert True

    def test_get_success(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            manager._agents["agent1"] = instance
            result = manager.get("agent1")
            assert result is instance

    def test_get_key_error(self, manager):
        with pytest.raises(KeyError):
            manager.get("ghost")

    def test_get_active_raises_when_empty(self, manager):
        with pytest.raises(NoAgentError, match="no agents registered"):
            manager.get_active()

    def test_get_active_returns_first(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            manager._agents["agent1"] = instance
            result = manager.get_active()
            assert result is instance
            assert manager._active == "agent1"

    def test_get_active_returns_active(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            a1 = MockClient.return_value
            a2 = MagicMock()
            manager._agents["agent1"] = a1
            manager._agents["agent2"] = a2
            manager._active = "agent2"
            result = manager.get_active()
            assert result is a2

    def test_set_active_success(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            manager._agents["agent1"] = instance
            manager.set_active("agent1")
            assert manager._active == "agent1"

    def test_set_active_key_error(self, manager):
        with pytest.raises(KeyError):
            manager.set_active("ghost")

    def test_active_name_property(self, manager):
        assert manager.active_name is None
        manager._active = "agent1"
        assert manager.active_name == "agent1"

    def test_list_agents_empty(self, manager):
        assert manager.list_agents() == []

    def test_list_agents_with_entries(self, manager):
        from core.agent_client import AgentClient
        a1 = MagicMock(spec=AgentClient)
        a1.ws_url = "ws://host1"
        a1.is_connected = True
        a1.hostname = "host1"
        a2 = MagicMock(spec=AgentClient)
        a2.ws_url = "ws://host2"
        a2.is_connected = False
        a2.hostname = ""
        manager._agents["agent1"] = a1
        manager._agents["agent2"] = a2
        manager._active = "agent1"
        result = manager.list_agents()
        assert len(result) == 2
        assert result[0]["name"] == "agent1"
        assert result[0]["active"] is True
        assert result[1]["name"] == "agent2"
        assert result[1]["active"] is False

    @pytest.mark.asyncio
    async def test_connect_all_empty(self, manager):
        await manager.connect_all()
        assert True

    @pytest.mark.asyncio
    async def test_connect_all(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            a1 = MockClient.return_value
            a1.connect = AsyncMock()
            a1.get_status = AsyncMock(return_value=MagicMock(payload={"hostname": "host1"}))
            a2 = MockClient.return_value
            a2.connect = AsyncMock()
            a2.get_status = AsyncMock(return_value=MagicMock(payload={"hostname": "host2"}))
            manager._agents["agent1"] = a1
            manager._agents["agent2"] = a2
            await manager.connect_all(max_retries=1, retry_delay=0.01)

    @pytest.mark.asyncio
    async def test_connect_all_partial_failure(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            a1 = MockClient.return_value
            a1.connect = AsyncMock()
            a2 = MockClient.return_value
            a2.connect = AsyncMock(side_effect=ConnectionError("fail"))
            manager._agents["agent1"] = a1
            manager._agents["agent2"] = a2
            await manager.connect_all(max_retries=1, retry_delay=0.01)

    @pytest.mark.asyncio
    async def test_close_all(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            a1 = MagicMock(spec=AsyncMock)
            a1.close = AsyncMock()
            a2 = MagicMock(spec=AsyncMock)
            a2.close = AsyncMock()
            manager._agents["agent1"] = a1
            manager._agents["agent2"] = a2
            manager._active = "agent1"
            await manager.close_all()
            assert manager._agents == {}
            assert manager._active is None
            a1.close.assert_awaited_once()
            a2.close.assert_awaited_once()

    def test_len(self, manager):
        assert len(manager) == 0
        manager._agents["a"] = MagicMock()
        assert len(manager) == 1
