import argparse
import asyncio
import contextlib
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import websockets
from websockets.http11 import Response
from websockets.datastructures import Headers

from bot.client import SentinelBot
from config import load_settings, validate_config
from core.agent_manager import AgentManager
from core.llm_brain import LLMBrain
from core.memory import SessionMemory
from core.tools import init_tools

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
log = logging.getLogger("sentinel")


def _ensure_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    env_example = Path(__file__).resolve().parent / ".env.example"
    if not env_path.exists() and env_example.exists():
        log.info(".env not found — creating from .env.example")
        env_path.write_text(env_example.read_text())


async def check_extras() -> None:
    extras = {
        "playwright": "install playwright browsers with: playwright install chromium",
    }
    for mod, hint in extras.items():
        if importlib.util.find_spec(mod) is None:
            log.info("Optional dep '%s' not installed. %s", mod, hint)


async def _handle_register_query(params: dict, agent_manager: AgentManager, settings) -> tuple[int, bytes]:
    token = (params.get("token") or [""])[0]
    url = (params.get("url") or [""])[0]

    if not url or not url.startswith("ws"):
        return 400, json.dumps({"error": "missing or invalid 'url'"}).encode()

    if not token:
        return 401, json.dumps({"error": "missing token"}).encode()

    agent_row = None
    if settings.sentinel_token and token == settings.sentinel_token:
        user_id = "default"
    else:
        agent_row = await agent_manager.memory.get_agent_by_token(token)
        if not agent_row:
            return 401, json.dumps({"error": "invalid token"}).encode()
        user_id = agent_row["user_id"]

    try:
        label = agent_row.get("label", "") if agent_row else "auto-registered"
        await agent_manager.memory.save_agent(user_id, url, token, label=label)
        await agent_manager.register_agent(user_id, url, token, label=label, connect=settings.lazy_agent_connect is False)
        log.info("Agent for user %s registered tunnel URL: %s", user_id[:8], url)
        return 200, json.dumps({"status": "ok", "url": url}).encode()
    except Exception as e:
        log.error("Agent registration failed: %s", e)
        return 500, json.dumps({"error": str(e)}).encode()


async def _start_server(agent_manager, settings) -> None:
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8000"))

    async def ws_handler(websocket: Any) -> None:
        await agent_manager.handle_ws_connection(websocket)
        # Keep the handler alive so the WebSocket stays open
        # handle_ws_connection creates a background listener task
        await asyncio.Future()

    async def process_request(connection, request) -> Any:
        path = request.path if hasattr(request, "path") else "/"
        if path in ("/", "/health"):
            return Response(200, "OK", Headers(), b"ok")

        if path.startswith("/register"):
            qs = urlparse(path).query
            params = parse_qs(qs)
            status, body = await _handle_register_query(params, agent_manager, settings)
            headers = Headers([(b"Content-Type", b"application/json")])
            reason = "OK" if status == 200 else ("Bad Request" if status == 400 else "Unauthorized" if status == 401 else "Internal Server Error")
            return Response(status, reason, headers, body)

        if path == "/agent-ws":
            return None  # proceed with WebSocket upgrade

        return Response(404, "Not Found", Headers(), b"not found")

    async with websockets.serve(ws_handler, host, port, process_request=process_request):
        log.info("Server listening on http://%s:%s (WS at /agent-ws)", host, port)
        await asyncio.Future()


async def main() -> None:
    parser = argparse.ArgumentParser(prog="sentinel-bot", description="OVT-Sentinel Discord Bot")
    parser.add_argument("--validate", action="store_true", help="Validate configuration and exit")
    args = parser.parse_args()

    _ensure_env()

    settings = load_settings()
    validate_config(settings)

    if args.validate:
        print("Configuration OK")
        providers = settings.configured_providers()
        print(f"  LLM fallback chain: {' → '.join(providers)}")
        print(f"  Database: {settings.database_url[:50]}...")
        print(f"  Data dir: {settings.data_dir}")
        print(f"  Guild allowlist: {len(settings.allowed_guild_ids)} guilds")
        print(f"  User allowlist: {len(settings.allowed_user_ids)} users")
        print(f"  Channel allowlist: {len(settings.allowed_channel_ids)} channels")
        print(f"  Agent tools: {settings.use_agent_tools}")
        print(f"  Confirm destructive: {settings.require_confirm_destructive}")
        return

    os.makedirs(settings.data_dir, exist_ok=True)

    memory = SessionMemory(settings.database_url)

    agent_manager = AgentManager(memory)
    await agent_manager.load_all_from_db()
    if settings.agent_ws and settings.sentinel_token:
        try:
            await agent_manager.register_agent(
                "default", settings.agent_ws, settings.sentinel_token, label="default",
                connect=not settings.lazy_agent_connect,
            )
        except Exception as exc:
            if settings.lazy_agent_connect:
                log.info("Default agent registered (lazy connect)")
            else:
                log.warning("Default agent connection failed: %s", exc)
    elif settings.agent_ws:
        log.info("No SENTINEL_TOKEN configured; skipping default bootstrap agent registration")

    llm = LLMBrain(config=settings, memory=memory)

    init_tools(agent_manager, memory, use_web_search=settings.use_web_search)

    await check_extras()

    server_task = asyncio.create_task(_start_server(agent_manager, settings))
    try:
        bot = SentinelBot(agent_manager=agent_manager, memory=memory, llm=llm, config=settings)
        log.info("Starting Discord bot...")
        await bot.start(settings.discord_token)
    finally:
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
        sys.exit(0)
