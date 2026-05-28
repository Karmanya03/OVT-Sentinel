import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    discord_token: str
    database_url: str
    agent_ws: str
    sentinel_token: str
    data_dir: str

    allowed_guild_ids: list[int] = field(default_factory=list)
    allowed_user_ids: list[int] = field(default_factory=list)
    allowed_channel_ids: list[int] = field(default_factory=list)

    llm_provider: str = "gemini"
    llm_provider_explicit: bool = False
    gemini_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    gemini_model: str = "models/gemini-2.5-flash"

    groq_api_key: Optional[str] = None
    groq_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    sambanova_api_key: Optional[str] = None
    sambanova_model: str = "Meta-Llama-3.1-70B-Instruct"

    cerebras_api_key: Optional[str] = None
    # Default Cerebras model (set via CEREBRAS_MODEL env var if you want to override)
    cerebras_model: str = "Qwen-3-235B-Instruct"

    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    nvidia_api_key: Optional[str] = None
    nvidia_model: str = "mistralai/mistral-large-3-675b-instruct-2512"
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    minimax_model: str = "minimaxai/minimax-m2.7"

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
    bot_public_url: str = ""
    agent_ws_port: int = 8002

    # Preferred provider fallback order: try Cerebras first, then Groq, then Gemini, then others
    PROVIDER_PRIORITY = ["cerebras", "groq", "gemini", "nvidia", "minimax", "openai", "sambanova", "ollama"]

    def provider_candidates(self) -> list[str]:
        key_map = {
            "gemini": self.gemini_api_key or self.google_api_key,
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
            "sambanova": self.sambanova_api_key,
            "cerebras": self.cerebras_api_key,
            "nvidia": self.nvidia_api_key,
            "minimax": self.nvidia_api_key,
            "ollama": self.ollama_base_url if self._ollama_enabled() else None,
        }
        return [p for p in self.PROVIDER_PRIORITY if key_map.get(p)]

    def configured_providers(self) -> list[str]:
        configured = self.provider_candidates()
        preferred = self.llm_provider.strip().lower() if self.llm_provider else ""
        if preferred and preferred in configured:
            # If the preferred provider is available, use only that one.
            return [preferred]
        return configured

    def _ollama_enabled(self) -> bool:
        base_url = (self.ollama_base_url or "").strip()
        if not base_url:
            return False
        enabled_env = os.getenv("OLLAMA_ENABLED")
        if enabled_env is not None:
            return enabled_env.lower() == "true"
        return not base_url.startswith(("http://localhost", "http://127.0.0.1", "https://localhost", "https://127.0.0.1"))


def _parse_int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


class ConfigError(RuntimeError):
    pass


def validate_config(s: Settings) -> None:
    errors: list[str] = []

    if not s.discord_token:
        errors.append("DISCORD_TOKEN is required")
    if not s.database_url:
        errors.append("DATABASE_URL is required")
    if not s.agent_ws:
        errors.append("AGENT_WS is required")

    configured = s.provider_candidates()
    if not configured:
        errors.append(
            "No LLM provider configured. Set at least one of: "
                "GEMINI_API_KEY or GOOGLE_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, "
            "SAMBANOVA_API_KEY, CEREBRAS_API_KEY, NVIDIA_API_KEY"
        )
    elif s.llm_provider_explicit and s.llm_provider.strip().lower() not in configured:
        errors.append(
            f"LLM_PROVIDER is set to '{s.llm_provider}', but that provider has no configured API key or endpoint."
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
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{data_dir}/sentinel.db")

    llm_provider_env = os.getenv("LLM_PROVIDER")
    llm_provider_explicit = bool(llm_provider_env and llm_provider_env.strip())
    default_llm_provider = "gemini"
    if os.getenv("GROQ_API_KEY"):
        default_llm_provider = "groq"
    elif os.getenv("NVIDIA_API_KEY"):
        default_llm_provider = "nvidia"
    elif os.getenv("OPENAI_API_KEY"):
        default_llm_provider = "openai"
    elif os.getenv("CEREBRAS_API_KEY"):
        default_llm_provider = "cerebras"
    elif os.getenv("SAMBANOVA_API_KEY"):
        default_llm_provider = "sambanova"
    elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        default_llm_provider = "gemini"

    raw_guilds = os.getenv("ALLOWED_GUILD_IDS", "")
    raw_users = os.getenv("ALLOWED_USER_IDS", "")
    raw_channels = os.getenv("ALLOWED_CHANNEL_IDS", "")

    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        database_url=database_url,
        agent_ws=os.getenv("AGENT_WS", "ws://127.0.0.1:7331"),
        sentinel_token=os.getenv("SENTINEL_TOKEN", ""),
        data_dir=data_dir,
        allowed_guild_ids=_parse_int_list(raw_guilds) if raw_guilds else [],
        allowed_user_ids=_parse_int_list(raw_users) if raw_users else [],
        allowed_channel_ids=_parse_int_list(raw_channels) if raw_channels else [],
        llm_provider=llm_provider_env or default_llm_provider,
        llm_provider_explicit=llm_provider_explicit,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
        sambanova_api_key=os.getenv("SAMBANOVA_API_KEY"),
        sambanova_model=os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.1-70B-Instruct"),
        cerebras_api_key=os.getenv("CEREBRAS_API_KEY"),
        cerebras_model=os.getenv("CEREBRAS_MODEL", "llama3.1-70b"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
        nvidia_model=os.getenv("NVIDIA_MODEL", "mistralai/mistral-large-3-675b-instruct-2512"),
        nvidia_base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        minimax_model=os.getenv("NVIDIA_MINIMAX_MODEL", "minimaxai/minimax-m2.7"),
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
        bot_public_url=os.getenv("BOT_PUBLIC_URL", ""),
        agent_ws_port=int(os.getenv("AGENT_WS_PORT", "8002")),
    )
