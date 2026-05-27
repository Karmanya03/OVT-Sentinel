from config import Settings, validate_config, ConfigError


def _make_settings(**overrides):
    defaults = dict(
        discord_token="token123",
        database_url="sqlite:///tmp/test.db",
        agent_ws="ws://127.0.0.1:7331",
        sentinel_token="securesecret",
        data_dir="/tmp/data",
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_valid_ollama():
    validate_config(_make_settings())


def test_valid_gemini():
    validate_config(_make_settings(
        llm_provider="gemini",
        gemini_api_key="AIza...",
    ))


def test_missing_discord_token():
    try:
        validate_config(_make_settings(discord_token=""))
        assert False, "expected ConfigError"
    except ConfigError:
        pass


def test_no_provider_configured():
    try:
        validate_config(_make_settings(
            llm_provider="gemini",
            gemini_api_key=None,
            ollama_base_url="",
        ))
        assert False, "expected ConfigError"
    except ConfigError as e:
        assert "No LLM provider configured" in str(e)


def test_placeholder_token():
    try:
        validate_config(_make_settings(sentinel_token="token-placeholder"))
        assert False, "expected ConfigError"
    except ConfigError:
        pass


def test_missing_database_url():
    try:
        validate_config(_make_settings(database_url=""))
        assert False, "expected ConfigError"
    except ConfigError as e:
        assert "DATABASE_URL" in str(e)


def test_bad_timeout():
    try:
        validate_config(_make_settings(command_timeout_secs=99999))
        assert False, "expected ConfigError"
    except ConfigError:
        pass
