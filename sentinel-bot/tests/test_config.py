from config import Settings, validate_config, ConfigError


def test_valid_ollama():
    s = Settings(
        discord_token="token123",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="securesecret",
        data_dir="/tmp/data",
        llm_provider="ollama",
    )
    validate_config(s)


def test_valid_gemini():
    s = Settings(
        discord_token="token123",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="securesecret",
        data_dir="/tmp/data",
        llm_provider="gemini",
        gemini_api_key="AIza...",
    )
    validate_config(s)


def test_missing_discord_token():
    s = Settings(
        discord_token="",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="securesecret",
        data_dir="/tmp/data",
        llm_provider="ollama",
    )
    try:
        validate_config(s)
        assert False, "expected ConfigError"
    except ConfigError:
        pass


def test_no_provider_configured():
    s = Settings(
        discord_token="token123",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="securesecret",
        data_dir="/tmp/data",
        llm_provider="gemini",
        gemini_api_key=None,
        ollama_base_url="",
    )
    try:
        validate_config(s)
        assert False, "expected ConfigError"
    except ConfigError as e:
        assert "No LLM provider configured" in str(e)


def test_placeholder_token():
    s = Settings(
        discord_token="token123",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="token-placeholder",
        data_dir="/tmp/data",
        llm_provider="ollama",
    )
    try:
        validate_config(s)
        assert False, "expected ConfigError"
    except ConfigError:
        pass


def test_bad_timeout():
    s = Settings(
        discord_token="token123",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="securesecret",
        data_dir="/tmp/data",
        llm_provider="ollama",
        command_timeout_secs=99999,
    )
    try:
        validate_config(s)
        assert False, "expected ConfigError"
    except ConfigError:
        pass
