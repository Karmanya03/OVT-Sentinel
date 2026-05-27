import os
import tempfile
import pytest
from core.memory import SessionMemory


@pytest.fixture
def mem():
    tmp = tempfile.mktemp(suffix=".db", prefix="sentinel_test_")
    m = SessionMemory(tmp)
    yield m
    m.conn.close()
    if os.path.exists(tmp):
        os.remove(tmp)
    if os.path.exists(tmp + "-wal"):
        os.remove(tmp + "-wal")
    if os.path.exists(tmp + "-shm"):
        os.remove(tmp + "-shm")


class TestSessionMemory:
    @pytest.mark.asyncio
    async def test_get_or_create_session_new(self, mem):
        sid = await mem.get_or_create_session("user_abc")
        assert sid == "user_abc"
        cur = mem.conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE id=?", (sid,))
        assert cur.fetchone() is not None

    @pytest.mark.asyncio
    async def test_get_or_create_session_existing(self, mem):
        sid1 = await mem.get_or_create_session("user_abc")
        sid2 = await mem.get_or_create_session("user_abc")
        assert sid1 == sid2

    @pytest.mark.asyncio
    async def test_get_or_create_session_with_id(self, mem):
        sid = await mem.get_or_create_session("user_abc", session_id="custom_id")
        assert sid == "custom_id"
        cur = mem.conn.cursor()
        cur.execute("SELECT id FROM sessions WHERE id=?", ("custom_id",))
        assert cur.fetchone() is None

    @pytest.mark.asyncio
    async def test_update_session_all_fields(self, mem):
        await mem.get_or_create_session("user1")
        await mem.update_session("user1", dc_host="dc01", domain="corp.local",
                                 username="admin", password="secret123")
        ctx = await mem.get_session_context("user1")
        s = ctx["session"]
        assert s["dc_host"] == "dc01"
        assert s["domain"] == "corp.local"
        assert s["username"] == "admin"
        assert s["password"] == "secret123"

    @pytest.mark.asyncio
    async def test_update_session_filters_invalid_keys(self, mem):
        await mem.get_or_create_session("user1")
        await mem.update_session("user1", invalid_key="should_ignore", dc_host="dc01")
        ctx = await mem.get_session_context("user1")
        assert ctx["session"]["dc_host"] == "dc01"

    @pytest.mark.asyncio
    async def test_update_session_no_op(self, mem):
        await mem.get_or_create_session("user1")
        await mem.update_session("user1")
        ctx = await mem.get_session_context("user1")
        assert ctx["session"] is not None

    @pytest.mark.asyncio
    async def test_log_command(self, mem):
        await mem.get_or_create_session("user1")
        await mem.log_command("user1", "user1", "ovt enum all", exit_code=0,
                              output_summary="success", agent_name="agent1")
        ctx = await mem.get_session_context("user1")
        assert len(ctx["recent_commands"]) == 1
        assert ctx["recent_commands"][0]["command"] == "ovt enum all"

    @pytest.mark.asyncio
    async def test_log_command_truncates_summary(self, mem):
        await mem.get_or_create_session("user1")
        long_summary = "x" * 1000
        await mem.log_command("user1", "user1", "test", output_summary=long_summary)
        ctx = await mem.get_session_context("user1")
        assert len(ctx["recent_commands"][0]["summary"]) <= 500

    @pytest.mark.asyncio
    async def test_log_command_with_tags(self, mem):
        await mem.get_or_create_session("user1")
        await mem.log_command("user1", "user1", "test", tags=["enum", "ad"])
        ctx = await mem.get_session_context("user1")
        assert ctx["recent_commands"][0]["tags"] == ["enum", "ad"]

    @pytest.mark.asyncio
    async def test_log_command_no_tags(self, mem):
        await mem.get_or_create_session("user1")
        await mem.log_command("user1", "user1", "test", tags=None)
        ctx = await mem.get_session_context("user1")
        assert ctx["recent_commands"][0]["tags"] == []

    @pytest.mark.asyncio
    async def test_log_finding(self, mem):
        await mem.get_or_create_session("user1")
        await mem.log_finding("user1", "kerberos_hash", "Kerberos hashes extracted",
                              {"count": 5}, severity="high")
        ctx = await mem.get_session_context("user1")
        assert len(ctx["findings"]) == 1
        assert ctx["findings"][0]["type"] == "kerberos_hash"
        assert ctx["findings"][0]["severity"] == "high"

    @pytest.mark.asyncio
    async def test_log_finding_default_severity(self, mem):
        await mem.get_or_create_session("user1")
        await mem.log_finding("user1", "info", "test info", {"key": "val"})
        ctx = await mem.get_session_context("user1")
        assert ctx["findings"][0]["severity"] == "medium"

    @pytest.mark.asyncio
    async def test_get_session_context_no_session(self, mem):
        ctx = await mem.get_session_context("nonexistent")
        assert ctx["session"] is None
        assert ctx["recent_commands"] == []
        assert ctx["findings"] == []

    @pytest.mark.asyncio
    async def test_get_session_context_no_commands(self, mem):
        await mem.get_or_create_session("user1")
        ctx = await mem.get_session_context("user1")
        assert ctx["session"] is not None
        assert ctx["recent_commands"] == []

    @pytest.mark.asyncio
    async def test_add_and_get_chat_history(self, mem):
        await mem.get_or_create_session("user1")
        await mem.add_chat_message("user1", "user", "hello")
        await mem.add_chat_message("user1", "assistant", "hi there")
        history = await mem.get_chat_history("user1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "hello"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "hi there"

    @pytest.mark.asyncio
    async def test_get_chat_history_limit(self, mem):
        await mem.get_or_create_session("user1")
        for i in range(5):
            await mem.add_chat_message("user1", "user", f"msg{i}")
        history = await mem.get_chat_history("user1", limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_get_chat_history_empty(self, mem):
        history = await mem.get_chat_history("nobody")
        assert history == []

    @pytest.mark.asyncio
    async def test_log_and_get_events(self, mem):
        await mem.log_event("agent_connected", "agent1")
        await mem.log_event("command_started", "ovt enum all")
        events = await mem.get_recent_events(limit=10)
        assert len(events) == 2
        assert events[0]["type"] == "command_started"
        assert events[1]["type"] == "agent_connected"

    @pytest.mark.asyncio
    async def test_log_output(self, mem):
        await mem.log_output("req_123", "stdout", "line1")
        await mem.log_output("req_123", "stdout", "line2")
        cur = mem.conn.cursor()
        cur.execute("SELECT count(*) as cnt FROM outputs WHERE request_id=?", ("req_123",))
        row = cur.fetchone()
        assert row["cnt"] == 2

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, mem):
        await mem.get_or_create_session("user1")
        await mem.get_or_create_session("user2")
        await mem.log_command("user1", "user1", "cmd1")
        await mem.log_command("user2", "user2", "cmd2")
        ctx1 = await mem.get_session_context("user1")
        ctx2 = await mem.get_session_context("user2")
        assert len(ctx1["recent_commands"]) == 1
        assert len(ctx2["recent_commands"]) == 1
        assert ctx1["recent_commands"][0]["command"] == "cmd1"
        assert ctx2["recent_commands"][0]["command"] == "cmd2"

    @pytest.mark.asyncio
    async def test_output_summary_capping(self, mem):
        await mem.get_or_create_session("user1")
        await mem.log_command("user1", "user1", "test", output_summary="x" * 600)
        ctx = await mem.get_session_context("user1")
        assert len(ctx["recent_commands"][0]["summary"]) <= 500
