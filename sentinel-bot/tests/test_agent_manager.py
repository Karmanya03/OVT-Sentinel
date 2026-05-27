from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_manager import AgentManager, NoAgentError
from core.memory import SessionMemory


@pytest.fixture
def manager():
    mem = MagicMock(spec=SessionMemory)
    mem.get_agent = AsyncMock(return_value=None)
    mem.save_agent = AsyncMock()
    mem.delete_agent = AsyncMock()
    mem.list_agents = AsyncMock(return_value=[])
    return AgentManager(memory=mem)


class TestAgentManager:
    def test_init(self, manager):
        assert manager._agents == {}
        assert manager._active is None

    @pytest.mark.asyncio
    async def test_register_agent_success(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.is_connected = True
            instance.hostname = ""
            status_mock = MagicMock()
            status_mock.payload = {"hostname": "vm1"}
            instance.get_status = AsyncMock(return_value=status_mock)
            agent = await manager.register_agent("user1", "ws://host1:7331", "tok1", label="my vm")
            assert agent is instance
            assert "user1" in manager._agents
            assert manager._active == "user1"
            manager.memory.save_agent.assert_awaited_once_with("user1", "ws://host1:7331", "tok1", "my vm")
            instance.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_agent_replaces_existing(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            old = MockClient.return_value
            old.close = AsyncMock()
            manager._agents["user1"] = old
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.is_connected = True
            instance.hostname = ""
            instance.get_status = AsyncMock(return_value=MagicMock(payload={}))
            await manager.register_agent("user1", "ws://host2", "tok2")
            old.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_agent_in_memory_connected(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.is_connected = True
            manager._agents["user1"] = instance
            result = await manager.get_agent("user1")
            assert result is instance

    @pytest.mark.asyncio
    async def test_get_agent_in_memory_reconnects(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.is_connected = False
            instance.ensure_connected = AsyncMock()
            manager._agents["user1"] = instance
            result = await manager.get_agent("user1")
            assert result is instance
            instance.ensure_connected.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_agent_from_db(self, manager):
        manager.memory.get_agent = AsyncMock(return_value={
            "user_id": "user1", "ws_url": "ws://host1", "token": "tok1", "label": "my vm",
        })
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.is_connected = True
            instance.hostname = ""
            instance.get_status = AsyncMock(return_value=MagicMock(payload={}))
            result = await manager.get_agent("user1")
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, manager):
        result = await manager.get_agent("nobody")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_agent(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.close = AsyncMock()
            manager._agents["user1"] = instance
            manager._active = "user1"
            await manager.remove_agent("user1")
            assert "user1" not in manager._agents
            assert manager._active is None
            manager.memory.delete_agent.assert_awaited_once_with("user1")

    @pytest.mark.asyncio
    async def test_remove_agent_nonexistent(self, manager):
        await manager.remove_agent("ghost")
        assert True

    @pytest.mark.asyncio
    async def test_disconnect_agent(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.close = AsyncMock()
            manager._agents["user1"] = instance
            await manager.disconnect_agent("user1")
            instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_agent_from_db(self, manager):
        manager.memory.get_agent = AsyncMock(return_value={
            "user_id": "user1", "ws_url": "ws://host1", "token": "tok1", "label": "",
        })
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.ensure_connected = AsyncMock()
            result = await manager.connect_agent("user1")
            assert result is True
            assert "user1" in manager._agents

    @pytest.mark.asyncio
    async def test_connect_agent_no_db(self, manager):
        result = await manager.connect_agent("nobody")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_agent_for_user_found(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.is_connected = True
            manager._agents["user1"] = instance
            result = await manager.get_agent_for_user("user1")
            assert result is instance

    @pytest.mark.asyncio
    async def test_get_agent_for_user_raises(self, manager):
        with pytest.raises(NoAgentError):
            await manager.get_agent_for_user("nobody", default_fallback=False)

    @pytest.mark.asyncio
    async def test_get_active_raises_when_empty(self, manager):
        with pytest.raises(NoAgentError, match="no agents registered"):
            manager.get_active()

    @pytest.mark.asyncio
    async def test_get_active_returns_only(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            manager._agents["user1"] = instance
            result = manager.get_active()
            assert result is instance
            assert manager._active == "user1"

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
        manager._agents["user1"] = a1
        manager._agents["user2"] = a2
        result = manager.list_agents()
        assert len(result) == 2
        assert result[0]["name"] == "user1"
        assert result[1]["name"] == "user2"

    @pytest.mark.asyncio
    async def test_load_all_from_db(self, manager):
        manager.memory.list_agents = AsyncMock(return_value=[
            {"user_id": "u1", "ws_url": "ws://h1", "token": "t1", "label": "l1"},
            {"user_id": "u2", "ws_url": "ws://h2", "token": "t2", "label": "l2"},
        ])
        with patch("core.agent_manager.AgentClient") as MockClient:
            instance = MockClient.return_value
            instance.connect = AsyncMock()
            instance.is_connected = False
            await manager.load_all_from_db()
            assert "u1" in manager._agents
            assert "u2" in manager._agents

    @pytest.mark.asyncio
    async def test_connect_all_empty(self, manager):
        await manager.connect_all()
        assert True

    @pytest.mark.asyncio
    async def test_close_all(self, manager):
        with patch("core.agent_manager.AgentClient") as MockClient:
            a1 = MagicMock(spec=AsyncMock)
            a1.close = AsyncMock()
            a2 = MagicMock(spec=AsyncMock)
            a2.close = AsyncMock()
            manager._agents["u1"] = a1
            manager._agents["u2"] = a2
            manager._active = "u1"
            await manager.close_all()
            assert manager._agents == {}
            assert manager._active is None
            a1.close.assert_awaited_once()
            a2.close.assert_awaited_once()

    def test_len(self, manager):
        assert len(manager) == 0
        manager._agents["a"] = MagicMock()
        assert len(manager) == 1
