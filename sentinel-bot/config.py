import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    discord_token: str
    agent_ws: str
    sentinel_token: str
    data_dir: str

    allowed_guild_ids: list[int] = field(default_factory=list)
    allowed_user_ids: list[int] = field(default_factory=list)
    allowed_channel_ids: list[int] = field(default_factory=list)

    llm_provider: str = "gemini"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "models/gemini-2.0-flash"

    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"

    sambanova_api_key: Optional[str] = None
    sambanova_model: str = "Meta-Llama-3.1-70B-Instruct"

    cerebras_api_key: Optional[str] = None
    cerebras_model: str = "llama3.1-70b"

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:70b"

    use_agent_tools: bool = True
    use_web_search: bool = True
    max_output_chars: int = 4000
    command_timeout_secs: int = 300
    require_confirm_destructive: bool = True

    use_llm_cache: bool = True
    llm_cache_ttl_secs: int = 300
    llm_cache_max_size: int = 1000
    lazy_agent_connect: bool = True

    PROVIDER_PRIORITY = ["gemini", "groq", "openai", "sambanova", "cerebras", "ollama"]

    def configured_providers(self) -> list[str]:
        key_map = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
            "sambanova": self.sambanova_api_key,
            "cerebras": self.cerebras_api_key,
            "ollama": self.ollama_base_url,
        }
        return [p for p in self.PROVIDER_PRIORITY if key_map.get(p)]


def _parse_int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


class ConfigError(RuntimeError):
    pass


def validate_config(s: Settings) -> None:
    errors: list[str] = []

    if not s.discord_token:
        errors.append("DISCORD_TOKEN is required")
    if not s.sentinel_token or s.sentinel_token == "token-placeholder":
        errors.append("SENTINEL_TOKEN must be set to a secure random string")
    if not s.agent_ws:
        errors.append("AGENT_WS is required")

    configured = s.configured_providers()
    if not configured:
        errors.append(
            "No LLM provider configured. Set at least one of: "
            "GEMINI_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, "
            "SAMBANOVA_API_KEY, CEREBRAS_API_KEY"
        )

    if s.command_timeout_secs < 1 or s.command_timeout_secs > 3600:
        errors.append("COMMAND_TIMEOUT_SECS must be between 1 and 3600")
    if s.max_output_chars < 100 or s.max_output_chars > 100000:
        errors.append("MAX_OUTPUT_CHARS must be between 100 and 100000")

    if errors:
        raise ConfigError("Configuration errors:\n  " + "\n  ".join(errors))


def load_settings() -> Settings:
    load_dotenv()

    root = Path(__file__).resolve().parent
    data_dir = os.getenv("SENTINEL_DATA_DIR", str(root / "data"))

    raw_guilds = os.getenv("ALLOWED_GUILD_IDS", "")
    raw_users = os.getenv("ALLOWED_USER_IDS", "")
    raw_channels = os.getenv("ALLOWED_CHANNEL_IDS", "")

    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        agent_ws=os.getenv("AGENT_WS", "ws://127.0.0.1:7331"),
        sentinel_token=os.getenv("SENTINEL_TOKEN", "token-placeholder"),
        data_dir=data_dir,
        allowed_guild_ids=_parse_int_list(raw_guilds) if raw_guilds else [],
        allowed_user_ids=_parse_int_list(raw_users) if raw_users else [],
        allowed_channel_ids=_parse_int_list(raw_channels) if raw_channels else [],
        llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "models/gemini-2.0-flash"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        sambanova_api_key=os.getenv("SAMBANOVA_API_KEY"),
        sambanova_model=os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.1-70B-Instruct"),
        cerebras_api_key=os.getenv("CEREBRAS_API_KEY"),
        cerebras_model=os.getenv("CEREBRAS_MODEL", "llama3.1-70b"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:70b"),
        use_agent_tools=os.getenv("USE_AGENT_TOOLS", "true").lower() == "true",
        use_web_search=os.getenv("USE_WEB_SEARCH", "true").lower() == "true",
        max_output_chars=int(os.getenv("MAX_OUTPUT_CHARS", "4000")),
        command_timeout_secs=int(os.getenv("COMMAND_TIMEOUT_SECS", "300")),
        require_confirm_destructive=os.getenv("REQUIRE_CONFIRM_DESTRUCTIVE", "true").lower() == "true",
        use_llm_cache=os.getenv("USE_LLM_CACHE", "true").lower() == "true",
        llm_cache_ttl_secs=int(os.getenv("LLM_CACHE_TTL_SECS", "300")),
        llm_cache_max_size=int(os.getenv("LLM_CACHE_MAX_SIZE", "1000")),
        lazy_agent_connect=os.getenv("LAZY_AGENT_CONNECT", "true").lower() == "true",
    )
