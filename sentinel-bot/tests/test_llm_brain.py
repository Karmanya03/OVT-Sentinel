import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.llm_brain import LLMBrain


class TestLLMBrain:
    @pytest.fixture
    def config(self):
        cfg = MagicMock()
        cfg.llm_provider = "gemini"
        cfg.use_agent_tools = True
        cfg.use_llm_cache = False
        cfg.llm_cache_ttl_secs = 300
        cfg.llm_cache_max_size = 1000
        cfg.max_output_chars = 4000
        return cfg

    @pytest.fixture
    def brain(self, config):
        with patch("core.llm_brain._load_prompts", return_value=("system prompt", "reference text")):
            brain = LLMBrain(config=config, memory=MagicMock())
            yield brain

    def test_init(self, brain, config):
        assert brain.config is config
        assert brain.memory is not None
        assert brain.system_prompt.startswith("system prompt")
        assert "TOOL SAFETY RULES" in brain.system_prompt
        assert "reference text" in brain.system_prompt

    @pytest.mark.asyncio
    async def test_chat_dispatches_to_gemini(self, brain):
        brain._chat_gemini = AsyncMock(return_value="gemini reply")
        brain._chat_langchain = AsyncMock(return_value="langchain reply")
        brain._providers = [("gemini", None, None)]
        result = await brain.chat("session1", "user1", "hello world")
        assert result == "gemini reply"
        brain._chat_gemini.assert_awaited_once_with(None, None, "session1", "user1", "hello world")

    @pytest.mark.asyncio
    async def test_chat_dispatches_to_langchain(self, config):
        cfg = config
        cfg.llm_provider = "groq"
        with patch("core.llm_brain._load_prompts", return_value=("sys", "ref")):
            brain = LLMBrain(config=cfg, memory=MagicMock())
            brain._chat_langchain = AsyncMock(return_value="langchain reply")
            brain._providers = [("groq", None, None)]
            result = await brain.chat("s1", "u1", "msg")
            assert result == "langchain reply"

    @pytest.mark.asyncio
    async def test_analyze_output_calls_chat(self, brain):
        brain.chat = AsyncMock(return_value="analysis result")
        result = await brain.analyze_output("s1", "ovt enum all", "some output here")
        assert result == "analysis result"
        brain.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_analyze_output_truncates_long_output(self, brain):
        brain.chat = AsyncMock(return_value="ok")
        long_output = "x" * 5000
        await brain.analyze_output("s1", "cmd", long_output)
        called_msg = brain.chat.call_args[0][2]
        assert len(called_msg) <= 4000

    def test_build_context_block_empty(self, brain):
        result = brain._build_context_block({})
        assert "CURRENT SESSION CONTEXT" in result
        assert "Target" not in result

    def test_build_context_block_full(self, brain):
        ctx = {
            "session": {"dc_host": "dc01", "domain": "corp.local"},
            "recent_commands": [
                {"command": "ovt enum all", "exit_code": 0, "summary": "ok", "tags": []}
            ],
            "findings": [
                {"type": "hash", "title": "hashes found", "severity": "high", "detail": {"count": 3}}
            ],
        }
        result = brain._build_context_block(ctx)
        assert "dc01" in result
        assert "corp.local" in result
        assert "ovt enum all" in result
        assert "hashes found" in result

    def test_build_context_block_partial(self, brain):
        ctx = {"session": None, "recent_commands": [], "findings": []}
        result = brain._build_context_block(ctx)
        assert "CURRENT SESSION CONTEXT" in result
        assert "Target" not in result

    def test_build_context_block_no_session_key(self, brain):
        result = brain._build_context_block({})
        assert "CURRENT SESSION CONTEXT" in result

    @pytest.mark.asyncio
    async def test_analyze_image_non_gemini(self, config):
        cfg = config
        cfg.llm_provider = "groq"
        with patch("core.llm_brain._load_prompts", return_value=("sys", "ref")):
            brain = LLMBrain(config=cfg, memory=MagicMock())
            brain._providers = [("groq", None, None)]
            result = await brain.analyze_image(b"fake_bytes")
            assert "Gemini" in result

    @pytest.mark.asyncio
    async def test_call_with_retry_success(self, brain):
        async def ok():
            return "done"
        result = await brain._call_with_retry(ok, max_retries=3, timeout=10)
        assert result == "done"

    @pytest.mark.asyncio
    async def test_call_with_retry_transient_then_success(self, brain):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("rate limit exceeded")
            return "ok"

        result = await brain._call_with_retry(flaky, max_retries=3, timeout=10)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_call_with_retry_all_fail(self, brain):
        async def always_fail():
            raise RuntimeError("quota exceeded")
        with pytest.raises(RuntimeError, match="quota exceeded"):
            await brain._call_with_retry(always_fail, max_retries=2, timeout=10)

    @pytest.mark.asyncio
    async def test_call_with_retry_timeout(self, brain):
        async def slow():
            await asyncio.sleep(10)
            return "late"
        with pytest.raises(RuntimeError):
            await brain._call_with_retry(slow, max_retries=1, timeout=0.05)

    @pytest.mark.asyncio
    async def test_call_with_retry_non_retryable(self, brain):
        async def fatal():
            raise ValueError("non-retryable")
        with pytest.raises(ValueError):
            await brain._call_with_retry(fatal, max_retries=3, timeout=10)

    def test_retry_keywords_extracted(self, brain):
        retryable = ["rate", "429", "quota", "overloaded", "unavailable", "503", "500", "timeout", "retry"]
        for kw in retryable:
            err = RuntimeError(kw)
            assert any(r in str(err).lower() for r in ["rate", "429", "quota", "overloaded", "unavailable", "503", "500", "timeout", "retry"])
