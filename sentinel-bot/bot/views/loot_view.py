import discord

from ..notifications import styled_embed, THEME, EMOJIS

FILES_PER_PAGE = 8

TYPE_PREFIXES = {
    "BloodHoundJson": "\U0001f50d",
    "Hashes": "\U0001f511",
    "Tickets": "\U0001f3f7\ufe0f",
    "Report": "\U0001f4c4",
    "Credentials": "\U0001f4b3",
    "Other": "\U0001f4e6",
}


class LootView(discord.ui.View):
    def __init__(self, files: list[dict], agent=None) -> None:
        super().__init__(timeout=120)
        self.files = files
        self.agent = agent
        self.page = 0
        self.max_page = max(0, (len(files) - 1) // FILES_PER_PAGE)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.max_page

    def _build_embed(self) -> discord.Embed:
        start = self.page * FILES_PER_PAGE
        end = start + FILES_PER_PAGE
        page_files = self.files[start:end]

        embed = styled_embed(
            f"{EMOJIS['loot']} Loot Files",
            f"Page {self.page + 1}/{self.max_page + 1} \u2022 {len(self.files)} total files",
            THEME["success"],
            footer=f"OVT-Sentinel",
        )
        for f in page_files:
            name = f.get("name", "?")
            size = f.get("size_bytes", 0)
            ftype = f.get("file_type", "Other")
            prefix = TYPE_PREFIXES.get(ftype, "\U0001f4e6")
            embed.add_field(
                name=f"{prefix} {name}",
                value=f"`{size // 1024} KB` | `{ftype}`",
                inline=False,
            )
        return embed

    @discord.ui.button(label="\u25c0 Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Next \u25b6", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page = min(self.max_page, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="\U0001f4e5 Download", style=discord.ButtonStyle.primary, row=0)
    async def download_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(DownloadModal(self.files, self.agent))

    @discord.ui.button(label="\u274c Close", style=discord.ButtonStyle.danger, row=0)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Closed.", embed=None, view=None)
        self.stop()


class DownloadModal(discord.ui.Modal):
    def __init__(self, files: list[dict], agent) -> None:
        self.files = {f.get("name", ""): f for f in files}
        self.agent = agent
        super().__init__(title="\U0001f4e5 Download Loot File")

    filename = discord.ui.TextInput(
        label="Filename (from the loot list above)",
        placeholder="e.g. output.txt or hashes.txt",
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.filename.value.strip()
        if not name:
            await interaction.response.send_message("\u274c No filename provided.", ephemeral=True)
            return
        if ".." in name or name.startswith("/") or name.startswith("\\"):
            await interaction.response.send_message("\u274c Invalid path.", ephemeral=True)
            return
        if self.agent is None:
            await interaction.response.send_message("\u274c Agent not available.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            msg = await self.agent.read_loot_file(name)
            if msg is None or msg.type == "error":
                await interaction.followup.send(f"\u274c Failed to read `{name}`.", ephemeral=True)
                return
            content = msg.payload.get("content", "")
            if not content:
                content = "(empty)"
            if len(content) > 1800:
                content = content[:1800] + "\n...[truncated]"
            await interaction.followup.send(f"```\n{content}\n```", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"\u274c Error: {e}", ephemeral=True)
