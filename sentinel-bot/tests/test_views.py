from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.views.confirm_view import ConfirmView
from bot.views.loot_view import LootView, DownloadModal, FILES_PER_PAGE


SAMPLE_FILES = [
    {"name": f"output_{i}.txt", "size_bytes": i * 1024, "file_type": "Hashes"}
    for i in range(1, 13)
]


def _mock_interaction():
    inter = MagicMock()
    inter.response = AsyncMock()
    inter.followup = AsyncMock()
    inter.user = MagicMock()
    inter.user.id = 12345
    return inter


def _invoke_button(view, label, interaction):
    """Invoke a discord.ui.Button callback by label."""
    for child in view.children:
        if getattr(child, "label", None) == label:
            return child.callback(interaction)
    raise AssertionError(f"Button '{label}' not found")


class TestConfirmView:
    def test_init(self):
        view = ConfirmView()
        assert view.confirmed is False
        assert view.timeout == 30

    @pytest.mark.asyncio
    async def test_confirm_sets_flag(self):
        view = ConfirmView()
        inter = _mock_interaction()
        await _invoke_button(view, "\u2705 Confirm", inter)
        assert view.confirmed is True
        inter.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_sets_flag(self):
        view = ConfirmView()
        inter = _mock_interaction()
        await _invoke_button(view, "\u274c Cancel", inter)
        assert view.confirmed is False
        inter.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_timeout_disables_buttons(self):
        view = ConfirmView()
        view._message = AsyncMock()
        await view.on_timeout()
        for child in view.children:
            assert child.disabled is True
        view._message.edit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_timeout_no_message(self):
        view = ConfirmView()
        view._message = None
        await view.on_timeout()
        for child in view.children:
            assert child.disabled is True


class TestLootView:
    def test_init_empty(self):
        view = LootView([], agent=None)
        assert view.page == 0
        assert view.max_page == 0
        assert view.agent is None

    def test_init_single_page(self):
        view = LootView(SAMPLE_FILES[:5], agent="mock")
        assert view.max_page == 0

    def test_init_multi_page(self):
        view = LootView(SAMPLE_FILES, agent="mock")
        assert view.max_page == 1

    def test_update_buttons_first_page(self):
        view = LootView(SAMPLE_FILES, agent=None)
        assert view.prev_button.disabled is True
        assert view.next_button.disabled is False

    def test_update_buttons_last_page(self):
        view = LootView(SAMPLE_FILES, agent=None)
        view.page = 1
        view._update_buttons()
        assert view.prev_button.disabled is False
        assert view.next_button.disabled is True

    def test_build_embed_first_page(self):
        view = LootView(SAMPLE_FILES, agent=None)
        embed = view._build_embed()
        assert "Page 1/2" in embed.description
        assert len(embed.fields) == FILES_PER_PAGE

    def test_build_embed_second_page(self):
        view = LootView(SAMPLE_FILES, agent=None)
        view.page = 1
        embed = view._build_embed()
        assert "Page 2/2" in embed.description
        remaining = len(SAMPLE_FILES) - FILES_PER_PAGE
        assert len(embed.fields) == remaining

    def test_build_embed_empty(self):
        view = LootView([], agent=None)
        embed = view._build_embed()
        assert "Page 1/1" in embed.description
        assert "0 total files" in embed.description

    def test_build_embed_file_missing_keys(self):
        view = LootView([{"name": "orphan.txt"}], agent=None)
        embed = view._build_embed()
        assert len(embed.fields) == 1

    @pytest.mark.asyncio
    async def test_prev_button(self):
        view = LootView(SAMPLE_FILES, agent=None)
        view.page = 1
        inter = _mock_interaction()
        await _invoke_button(view, "\u25c0 Prev", inter)
        assert view.page == 0
        inter.response.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prev_button_stays_at_zero(self):
        view = LootView(SAMPLE_FILES, agent=None)
        inter = _mock_interaction()
        await _invoke_button(view, "\u25c0 Prev", inter)
        assert view.page == 0

    @pytest.mark.asyncio
    async def test_next_button(self):
        view = LootView(SAMPLE_FILES, agent=None)
        inter = _mock_interaction()
        await _invoke_button(view, "Next \u25b6", inter)
        assert view.page == 1

    @pytest.mark.asyncio
    async def test_next_button_stays_at_max(self):
        view = LootView(SAMPLE_FILES, agent=None)
        view.page = view.max_page
        inter = _mock_interaction()
        await _invoke_button(view, "Next \u25b6", inter)
        assert view.page == view.max_page

    @pytest.mark.asyncio
    async def test_download_button_opens_modal(self):
        view = LootView(SAMPLE_FILES, agent="mock")
        inter = _mock_interaction()
        await _invoke_button(view, "\U0001f4e5 Download", inter)
        inter.response.send_modal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_button(self):
        view = LootView(SAMPLE_FILES, agent=None)
        inter = _mock_interaction()
        await _invoke_button(view, "\u274c Close", inter)
        assert view.is_finished()
        inter.response.edit_message.assert_awaited_once()


class TestDownloadModal:
    def _make_modal(self, agent=None):
        modal = DownloadModal(SAMPLE_FILES, agent)
        modal.filename = MagicMock()
        return modal

    @pytest.mark.asyncio
    async def test_on_submit_empty_filename(self):
        modal = self._make_modal(agent=AsyncMock())
        modal.filename.value = ""
        inter = _mock_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_awaited_once_with("\u274c No filename provided.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_on_submit_path_traversal(self):
        modal = self._make_modal(agent=AsyncMock())
        modal.filename.value = "../etc/passwd"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_awaited_once_with("\u274c Invalid path.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_on_submit_absolute_path(self):
        modal = self._make_modal(agent=AsyncMock())
        modal.filename.value = "/etc/passwd"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_awaited_once_with("\u274c Invalid path.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_on_submit_no_agent(self):
        modal = self._make_modal(agent=None)
        modal.filename.value = "output_1.txt"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        inter.response.send_message.assert_awaited_once_with("\u274c Agent not available.", ephemeral=True)

    @pytest.mark.asyncio
    async def test_on_submit_success(self):
        agent = AsyncMock()
        agent.read_loot_file.return_value = MagicMock(
            type="loot_file_content",
            payload={"content": "file contents here"}
        )
        modal = self._make_modal(agent=agent)
        modal.filename.value = "output_1.txt"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        agent.read_loot_file.assert_awaited_once_with("output_1.txt")
        inter.followup.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_submit_agent_error(self):
        agent = AsyncMock()
        agent.read_loot_file.return_value = MagicMock(type="error", payload={})
        modal = self._make_modal(agent=agent)
        modal.filename.value = "output_1.txt"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        inter.followup.send.assert_awaited_once()
        msg = inter.followup.send.call_args[0][0]
        assert "Failed to read" in msg

    @pytest.mark.asyncio
    async def test_on_submit_truncated_content(self):
        agent = AsyncMock()
        agent.read_loot_file.return_value = MagicMock(
            type="loot_file_content",
            payload={"content": "x" * 3000}
        )
        modal = self._make_modal(agent=agent)
        modal.filename.value = "big.txt"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        sent = inter.followup.send.call_args[0][0]
        assert "...[truncated]" in sent

    @pytest.mark.asyncio
    async def test_on_submit_exception(self):
        agent = AsyncMock()
        agent.read_loot_file.side_effect = RuntimeError("connection lost")
        modal = self._make_modal(agent=agent)
        modal.filename.value = "output_1.txt"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        inter.followup.send.assert_awaited_once()
        msg = inter.followup.send.call_args[0][0]
        assert "Error" in msg

    @pytest.mark.asyncio
    async def test_on_submit_empty_content(self):
        agent = AsyncMock()
        agent.read_loot_file.return_value = MagicMock(
            type="loot_file_content",
            payload={"content": ""}
        )
        modal = self._make_modal(agent=agent)
        modal.filename.value = "empty.txt"
        inter = _mock_interaction()
        await modal.on_submit(inter)
        sent = inter.followup.send.call_args[0][0]
        assert "(empty)" in sent
