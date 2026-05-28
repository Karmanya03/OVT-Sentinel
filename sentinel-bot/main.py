import argparse
import asyncio
import contextlib
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

from bot.client import SentinelBot
from config import load_settings, validate_config
from core.agent_manager import AgentManager
from core.llm_brain import LLMBrain
from core.memory import SessionMemory
from core.tools import init_tools

log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
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


async def _start_health_server(agent_manager: AgentManager, settings) -> asyncio.AbstractServer:
    host = os.getenv("HEALTHCHECK_HOST", "0.0.0.0")
    port = int(os.getenv("HEALTHCHECK_PORT", "8000"))

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.read(4096)
            text = raw.decode("utf-8", errors="replace")
            lines = text.split("\r\n")
            first = lines[0] if lines else ""
            method, path, _ = first.split(" ", 2) if " " in first else ("", "", "")

            if method == "POST" and path == "/register":
                body_start = text.find("\r\n\r\n") + 4
                body_text = text[body_start:] if body_start > 3 else ""
                status, resp_body = await _handle_register(body_text, agent_manager, settings)
            else:
                status, resp_body = 200, b"ok"

            status_text = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 500: "Internal Server Error"}.get(status, "OK")
            response = (
                f"HTTP/1.1 {status} {status_text}\r\n"
                f"Content-Length: {len(resp_body)}\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n"
                "\r\n"
            ).encode("ascii") + (resp_body if isinstance(resp_body, bytes) else resp_body.encode())
            writer.write(response)
            await writer.drain()
        except Exception as e:
            log.error("Health server error: %s", e)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, host, port)
    log.info("Healthcheck server listening on %s:%s", host, port)
    return server


async def _handle_register(body: str, agent_manager: AgentManager, settings) -> tuple[int, bytes]:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return 400, json.dumps({"error": "invalid json"}).encode()

    token = data.get("token", "")
    url = data.get("url", "")

    if not url or not url.startswith("ws"):
        return 400, json.dumps({"error": "missing or invalid 'url'"}).encode()

    # Accept global sentinel_token OR any per-agent token from the DB
    if not token:
        return 401, json.dumps({"error": "missing token"}).encode()

    agent_row = None
    if settings.sentinel_token and token == settings.sentinel_token:
        # Global bootstrap token — map to "default" user
        user_id = "default"
    else:
        agent_row = await agent_manager.memory.get_agent_by_token(token)
        if not agent_row:
            return 401, json.dumps({"error": "invalid token"}).encode()
        user_id = agent_row["user_id"]

    try:
        label = agent_row.get("label", "") if agent_row else "auto-registered"
        await agent_manager.memory.save_agent(user_id, url, token, label=label)
        # Create or update the agent client and attempt connection
        await agent_manager.register_agent(user_id, url, token, label=label, connect=settings.lazy_agent_connect is False)
        log.info("Agent for user %s registered tunnel URL: %s", user_id[:8], url)
        return 200, json.dumps({"status": "ok", "url": url}).encode()
    except Exception as e:
        log.error("Agent registration failed: %s", e)
        return 500, json.dumps({"error": str(e)}).encode()


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
        print(f"  Agent WS: {settings.agent_ws}")
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

    server = await _start_health_server(agent_manager, settings)
    health_task = asyncio.create_task(server.serve_forever())
    try:
        bot = SentinelBot(agent_manager=agent_manager, memory=memory, llm=llm, config=settings)
        log.info("Starting Discord bot...")
        await bot.start(settings.discord_token)
    finally:
        health_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await health_task
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
        sys.exit(0)
