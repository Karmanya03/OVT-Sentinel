import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_client import AgentClient, AgentDisconnected


@pytest.fixture
def client():
    c = AgentClient(ws_url="ws://localhost:7331", token="test_token", name="test_agent")
    c._ws = AsyncMock()
    c._ws.close_code = None
    c._ws.send = AsyncMock()
    yield c
    c._connected = False
    if c._listener_task:
        c._listener_task.cancel()


@pytest.mark.asyncio
async def test_init():
    c = AgentClient(ws_url="ws://localhost:7331", token="test_token", name="agent1")
    assert c.ws_url == "ws://localhost:7331"
    assert c.token == "test_token"
    assert c.name == "agent1"
    assert c.hostname == ""
    assert c._ws is None
    assert c._connected is False
    assert c._request_queues == {}
    assert c._general_queue is not None


@pytest.mark.asyncio
async def test_is_connected_false_when_no_ws():
    c = AgentClient(ws_url="ws://test", token="t")
    assert c.is_connected is False


@pytest.mark.asyncio
async def test_is_connected_true(client):
    client._connected = True
    assert client.is_connected is True


@pytest.mark.asyncio
async def test_is_connected_false_when_ws_closed(client):
    client._connected = True
    client._ws.close_code = 1001
    assert client.is_connected is False


@pytest.mark.asyncio
async def test_connect_success(client):
    client._connected = False
    client._ws = None
    mock_ws = AsyncMock()
    mock_ws.close_code = None
    mock_ws.recv = AsyncMock(return_value=json.dumps({"type": "auth_success", "success": True}))
    mock_ws.send = AsyncMock()

    with patch("core.agent_client.websockets.connect", AsyncMock(return_value=mock_ws)), \
         patch("asyncio.create_task") as mock_create_task:
        mock_create_task.return_value = asyncio.create_task(asyncio.sleep(0))
        await client.connect()

    assert client._connected is True
    assert client._ws is mock_ws


@pytest.mark.asyncio
async def test_connect_auth_failure(client):
    client._connected = False
    client._ws = None
    mock_ws = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=json.dumps({"type": "auth_success", "success": False, "reason": "bad token"}))
    mock_ws.send = AsyncMock()

    with patch("core.agent_client.websockets.connect", AsyncMock(return_value=mock_ws)):
        with pytest.raises(RuntimeError, match="agent auth failed"):
            await client.connect(max_retries=1)


@pytest.mark.asyncio
async def test_connect_retry_then_fail(client):
    client._connected = False
    client._ws = None

    with patch("core.agent_client.websockets.connect", AsyncMock(side_effect=OSError("connection refused"))):
        with pytest.raises(OSError):
            await client.connect(max_retries=2, retry_delay=0.01)
    assert client._connected is False
    assert client._ws is None


@pytest.mark.asyncio
async def test_ensure_connected_already_connected(client):
    client._connected = True
    await client.ensure_connected()
    assert client._connected is True


@pytest.mark.asyncio
async def test_send_raises_when_not_connected(client):
    client._ws = None
    with pytest.raises(AgentDisconnected):
        await client._send({"type": "test"})


@pytest.mark.asyncio
async def test_send_sends_json(client):
    client._connected = True
    payload = {"type": "ping"}
    await client._send(payload)
    client._ws.send.assert_awaited_once()
    sent = json.loads(client._ws.send.call_args[0][0])
    assert sent["type"] == "ping"


@pytest.mark.asyncio
async def test_close(client):
    client._connected = True
    ws = client._ws
    listener = asyncio.create_task(asyncio.Event().wait())
    client._listener_task = listener
    await client.close()
    assert client._connected is False
    ws.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_already_closed(client):
    client._connected = False
    await client.close()


@pytest.mark.asyncio
async def test_get_status(client):
    mock_resp = MagicMock(type="status_snapshot", payload={"cpu_percent": 42.0})
    client._wait_for_type = AsyncMock(return_value=mock_resp)
    client._connected = True
    result = await client.get_status()
    assert result.type == "status_snapshot"
    assert result.payload["cpu_percent"] == 42.0


@pytest.mark.asyncio
async def test_get_loot(client):
    mock_resp = MagicMock(type="loot_listing", payload={"files": []})
    client._wait_for_type = AsyncMock(return_value=mock_resp)
    client._connected = True
    result = await client.get_loot()
    assert result.type == "loot_listing"


@pytest.mark.asyncio
async def test_read_loot_file(client):
    mock_resp = MagicMock(type="loot_file_content", payload={"content": "file data"})
    client._wait_for_type = AsyncMock(return_value=mock_resp)
    client._connected = True
    result = await client.read_loot_file("output.txt")
    assert result.payload["content"] == "file data"


@pytest.mark.asyncio
async def test_take_screenshot(client):
    mock_resp = MagicMock(type="screenshot", payload={"path": "screen.png"})
    client._wait_for_type = AsyncMock(return_value=mock_resp)
    client._connected = True
    result = await client.take_screenshot()
    assert result.type == "screenshot"


@pytest.mark.asyncio
async def test_browse_url(client):
    mock_resp = MagicMock(type="screenshot", payload={"path": "browse.png", "url": "https://example.com"})
    client._wait_for_type = AsyncMock(return_value=mock_resp)
    client._connected = True
    result = await client.browse_url("https://example.com")
    assert result.type == "screenshot"


@pytest.mark.asyncio
async def test_kill_command(client):
    client._connected = True
    await client.kill_command("target_req")
    client._ws.send.assert_awaited_once()
    sent = json.loads(client._ws.send.call_args[0][0])
    assert sent["type"] == "kill_command"
    assert sent["request_id"] == "target_req"


@pytest.mark.asyncio
async def test_wait_for_type_timeout(client):
    client._general_queue = asyncio.Queue()
    with pytest.raises(asyncio.TimeoutError):
        await client._wait_for_type("command_complete", timeout=0.05)
