import asyncio
import logging
from typing import Optional

from .agent_client import AgentClient


log = logging.getLogger("sentinel.agent_manager")


class NoAgentError(Exception):
    pass


class AgentManager:
    def __init__(self, uri: str, token: str):
        self._uri = uri
        self._token = token
        self._agents: dict[str, AgentClient] = {}
        self._active: Optional[str] = None

    async def add_agent(self, name: str = "default") -> AgentClient:
        agent = AgentClient(self._uri, self._token, name=name)
        await agent.connect()
        self._agents[name] = agent
        log.info("Agent '%s' connected", name)
        return agent

    async def get_agent(self, name: str = "default") -> Optional[AgentClient]:
        agent = self._agents.get(name)
        if agent is None:
            return None
        if not agent.is_connected:
            try:
                await agent.connect()
            except Exception:
                return None
        return agent

    async def remove_agent(self, name: str) -> None:
        agent = self._agents.pop(name, None)
        if agent:
            asyncio.create_task(agent.close())
        if self._active == name:
            self._active = next(iter(self._agents)) if self._agents else None

    def get(self, name: str) -> AgentClient:
        if name not in self._agents:
            raise KeyError(f"agent '{name}' not found")
        return self._agents[name]

    def get_active(self) -> AgentClient:
        if not self._agents:
            raise NoAgentError("no agents registered")
        if self._active is None:
            self._active = next(iter(self._agents))
        return self._agents[self._active]

    def set_active(self, name: str) -> None:
        if name not in self._agents:
            raise KeyError(f"agent '{name}' not found")
        self._active = name

    @property
    def active_name(self) -> Optional[str]:
        return self._active

    def list_agents(self) -> list[dict]:
        return [
            {
                "name": name,
                "ws_url": client.ws_url,
                "connected": client.is_connected,
                "hostname": getattr(client, "hostname", None),
                "active": name == self._active,
            }
            for name, client in self._agents.items()
        ]

    async def connect_all(self, max_retries: int = 1, retry_delay: float = 2.0) -> None:
        async def _connect_one(name: str, client: AgentClient) -> None:
            try:
                await client.connect(max_retries=max_retries, retry_delay=retry_delay)
                try:
                    status = await client.get_status()
                    hostname = status.payload.get("hostname", status.payload.get("os_hostname", ""))
                    if hostname:
                        client.hostname = hostname
                except Exception:
                    pass
                log.info("Agent '%s' connected at %s", name, client.ws_url)
            except Exception as exc:
                log.warning("Agent '%s' connection failed: %s", name, exc)

        tasks = [_connect_one(name, client) for name, client in self._agents.items()]
        await asyncio.gather(*tasks)

    async def close_all(self) -> None:
        for name, client in self._agents.items():
            try:
                await client.close()
            except Exception:
                pass
        self._agents.clear()
        self._active = None

    def __len__(self) -> int:
        return len(self._agents)
