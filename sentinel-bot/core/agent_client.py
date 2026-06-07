import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

import websockets

from .protocol import AgentMessage, make_bot_message, parse_agent_message

log = logging.getLogger("sentinel.agent_client")


class AgentDisconnected(Exception):
    pass


class AgentClient:
    def __init__(self, ws_url: str = "", token: str = "", name: str = "") -> None:
        self.ws_url = ws_url
        self.token = token
        self.name = name
        self.hostname: str = ""
        self.tunnel_url: Optional[str] = None
        self._ws = None  # Will be set by connect() or from_incoming()
        self._listener_task: Optional[asyncio.Task] = None
        self._request_queues: Dict[str, asyncio.Queue] = {}
        self._general_queue: asyncio.Queue = asyncio.Queue()
        self.last_request_id: Optional[str] = None
        self._connected = False

    @classmethod
    def from_incoming(cls, websocket, token: str, name: str = "") -> "AgentClient":
        client = cls(token=token, name=name)
        client._ws = websocket
        client._connected = True
        return client

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None and not self._ws.close_code

    async def connect(self, max_retries: int = 1, retry_delay: float = 2.0) -> None:
        for attempt in range(max_retries):
            try:
                self._ws = await websockets.connect(self.ws_url)
                await self._send(make_bot_message("auth", token=self.token))
                auth_msg = await self._ws.recv()
                msg = parse_agent_message(auth_msg)
                if msg.payload.get("success") is not True:
                    reason = msg.payload.get("reason", "auth failed")
                    raise RuntimeError(f"agent auth failed: {reason}")

                tunnel = msg.payload.get("tunnel_url")
                if tunnel:
                    self.tunnel_url = tunnel
                    if self.ws_url != tunnel:
                        log.info("Agent published tunnel URL: %s (was %s)", tunnel, self.ws_url)

                self._connected = True
                self._listener_task = asyncio.create_task(self._listener())
                return
            except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    self._ws = None
                    raise

    async def ensure_connected(self, max_retries: int = 3, retry_delay: float = 2.0) -> None:
        if self.is_connected:
            return
        await self.close()
        await self.connect(max_retries=max_retries, retry_delay=retry_delay)

    async def close(self) -> None:
        self._connected = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None
        if self._ws:
            await self._ws.close()
        self._ws = None

    async def _send(self, payload: Dict[str, Any]) -> None:
        if not self._ws:
            raise AgentDisconnected("agent websocket not connected")
        await self._ws.send(json.dumps(payload))

    async def _listener(self) -> None:
        if not self._ws:
            return
        try:
            async for raw in self._ws:
                msg = parse_agent_message(raw)
                request_id = msg.payload.get("request_id")
                if request_id and request_id in self._request_queues:
                    await self._request_queues[request_id].put(msg)
                else:
                    await self._general_queue.put(msg)
        except websockets.WebSocketException:
            pass
        finally:
            self._connected = False

    async def run_command(self, command: str) -> AsyncGenerator[AgentMessage, None]:
        await self.ensure_connected()
        request_id = f"req-{uuid.uuid4()}"
        self.last_request_id = request_id
        q: asyncio.Queue = asyncio.Queue()
        self._request_queues[request_id] = q
        await self._send(make_bot_message("run_command", request_id=request_id, command=command))

        while True:
            msg = await q.get()
            yield msg
            if msg.type in ("command_complete", "command_killed", "error"):
                break

        self._request_queues.pop(request_id, None)

    async def run_shell_command(self, command: str) -> AsyncGenerator[AgentMessage, None]:
        await self.ensure_connected()
        request_id = f"req-{uuid.uuid4()}"
        self.last_request_id = request_id
        q: asyncio.Queue = asyncio.Queue()
        self._request_queues[request_id] = q
        await self._send(make_bot_message("run_shell_command", request_id=request_id, command=command))

        while True:
            msg = await q.get()
            yield msg
            if msg.type in ("command_complete", "command_killed", "error"):
                break

        self._request_queues.pop(request_id, None)

    async def kill_command(self, request_id: str) -> None:
        await self.ensure_connected()
        await self._send(make_bot_message("kill_command", request_id=request_id))

    async def get_status(self) -> AgentMessage:
        await self.ensure_connected()
        await self._send(make_bot_message("get_status"))
        return await self._wait_for_type("status_snapshot")

    async def get_loot(self) -> AgentMessage:
        await self.ensure_connected()
        await self._send(make_bot_message("get_loot"))
        return await self._wait_for_type("loot_listing")

    async def read_loot_file(self, path: str) -> AgentMessage:
        await self.ensure_connected()
        await self._send(make_bot_message("read_loot_file", path=path))
        return await self._wait_for_type("loot_file_content")

    async def take_screenshot(self) -> AgentMessage:
        await self.ensure_connected()
        await self._send(make_bot_message("take_screenshot"))
        return await self._wait_for_type("screenshot")

    async def browse_url(self, url: str) -> AgentMessage:
        await self.ensure_connected()
        await self._send(make_bot_message("browse_url", url=url))
        return await self._wait_for_type("screenshot")

    async def _wait_for_type(self, msg_type: str, timeout: float = 30.0) -> AgentMessage:
        while True:
            msg = await asyncio.wait_for(self._general_queue.get(), timeout=timeout)
            if msg.type == msg_type or msg.type == "error":
                return msg
