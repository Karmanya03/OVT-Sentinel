import asyncio
import logging
from typing import Optional

from .agent_client import AgentClient
from .memory import SessionMemory

log = logging.getLogger("sentinel.agent_manager")


class NoAgentError(Exception):
    pass


class AgentManager:
    def __init__(self, memory: SessionMemory):
        self.memory = memory
        self._agents: dict[str, AgentClient] = {}
        self._active: Optional[str] = None

    async def register_agent(
        self, user_id: str, ws_url: str, token: str, label: str = "", connect: bool = True
    ) -> AgentClient:
        await self.memory.save_agent(user_id, ws_url, token, label)

        existing = self._agents.get(user_id)
        if existing:
            await existing.close()

        client = AgentClient(ws_url, token, name=label or user_id[:8])
        self._agents[user_id] = client
        if not self._active:
            self._active = user_id

        if connect:
            try:
                await client.connect(max_retries=2, retry_delay=1.0)
                try:
                    status = await client.get_status()
                    hostname = status.payload.get("hostname", status.payload.get("os_hostname", ""))
                    if hostname:
                        client.hostname = hostname
                except Exception:
                    pass
                if client.tunnel_url and client.tunnel_url != ws_url:
                    log.info("Agent for user %s tunnel URL: %s", user_id[:8], client.tunnel_url)
                    await self.memory.save_agent(user_id, client.tunnel_url, token, label)
                    client.ws_url = client.tunnel_url
                log.info("Agent for user %s connected at %s", user_id[:8], client.ws_url)
            except Exception as exc:
                log.warning("Agent for user %s connection failed: %s", user_id[:8], exc)

        return client

    async def get_agent(self, user_id: str) -> Optional[AgentClient]:
        client = self._agents.get(user_id)
        if client and client.is_connected:
            return client
        if client:
            try:
                await client.ensure_connected()
                return client
            except Exception:
                pass

        row = await self.memory.get_agent(user_id)
        if not row:
            return None

        return await self.register_agent(
            user_id, row["ws_url"], row["token"], row.get("label", ""), connect=True,
        )

    async def remove_agent(self, user_id: str) -> None:
        client = self._agents.pop(user_id, None)
        if client:
            await client.close()
        await self.memory.delete_agent(user_id)
        if self._active == user_id:
            self._active = next(iter(self._agents)) if self._agents else None

    async def disconnect_agent(self, user_id: str) -> None:
        client = self._agents.get(user_id)
        if client:
            await client.close()

    async def connect_agent(self, user_id: str, max_retries: int = 3, retry_delay: float = 2.0) -> bool:
        client = self._agents.get(user_id)
        if not client:
            row = await self.memory.get_agent(user_id)
            if not row:
                return False
            client = AgentClient(row["ws_url"], row["token"], name=row.get("label", "") or user_id[:8])
            self._agents[user_id] = client
        try:
            await client.ensure_connected(max_retries=max_retries, retry_delay=retry_delay)
            return True
        except Exception:
            return False

    async def get_agent_for_user(self, user_id: str, default_fallback: bool = True) -> AgentClient:
        agent = await self.get_agent(user_id)
        if agent:
            return agent
        if default_fallback:
            return self.get_active()
        raise NoAgentError(f"no agent configured for user {user_id[:8]}")

    def get_active(self) -> AgentClient:
        if not self._agents:
            raise NoAgentError("no agents registered")
        if self._active is None or self._active not in self._agents:
            self._active = next(iter(self._agents))
        return self._agents[self._active]

    def get(self, name: str) -> AgentClient:
        if name not in self._agents:
            raise KeyError(f"agent '{name}' not found")
        return self._agents[name]

    def list_agents(self) -> list[dict]:
        return [
            {
                "name": uid,
                "ws_url": client.ws_url,
                "connected": client.is_connected,
                "hostname": getattr(client, "hostname", None),
            }
            for uid, client in self._agents.items()
        ]

    async def load_all_from_db(self) -> None:
        rows = await self.memory.list_agents()
        for row in rows:
            user_id = row["user_id"]
            try:
                client = AgentClient(row["ws_url"], row["token"], name=row.get("label", "") or user_id[:8])
                self._agents[user_id] = client
                if not self._active:
                    self._active = user_id
                try:
                    await client.connect(max_retries=1, retry_delay=1.0)
                    hostname = (await client.get_status()).payload.get("hostname", "")
                    if hostname:
                        client.hostname = hostname
                except Exception:
                    pass
            except Exception as exc:
                log.warning("Failed to load agent for user %s: %s", user_id[:8], exc)

    async def connect_all(self, max_retries: int = 1, retry_delay: float = 2.0) -> None:
        async def _connect_one(user_id: str, client: AgentClient) -> None:
            try:
                await client.connect(max_retries=max_retries, retry_delay=retry_delay)
                try:
                    status = await client.get_status()
                    hostname = status.payload.get("hostname", status.payload.get("os_hostname", ""))
                    if hostname:
                        client.hostname = hostname
                except Exception:
                    pass
                log.info("Agent '%s' connected at %s", user_id[:8], client.ws_url)
            except Exception as exc:
                log.warning("Agent '%s' connection failed: %s", user_id[:8], exc)

        tasks = [_connect_one(uid, client) for uid, client in self._agents.items()]
        await asyncio.gather(*tasks)

    async def close_all(self) -> None:
        for uid, client in self._agents.items():
            try:
                await client.close()
            except Exception:
                pass
        self._agents.clear()
        self._active = None

    def __len__(self) -> int:
        return len(self._agents)
