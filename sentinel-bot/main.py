import argparse
import asyncio
import importlib.util
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

    llm = LLMBrain(config=settings, memory=memory)

    init_tools(agent_manager, memory, use_web_search=settings.use_web_search)

    await check_extras()

    bot = SentinelBot(agent_manager=agent_manager, memory=memory, llm=llm, config=settings)
    log.info("Starting Discord bot...")
    await bot.start(settings.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
        sys.exit(0)
