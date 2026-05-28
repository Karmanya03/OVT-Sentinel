import discord
from .notifications import sanitize

MAX_DESC = 4096


def _split_text(text: str) -> list[str]:
    """Split long text into chunks respecting paragraph breaks."""
    text = text.strip()
    if not text:
        return [""]

    chunks = []
    while len(text) > MAX_DESC:
        split_at = text.rfind("\n\n", 0, MAX_DESC)
        if split_at == -1:
            split_at = text.rfind("\n", 0, MAX_DESC)
        if split_at == -1:
            split_at = text.rfind(" ", 0, MAX_DESC)
        if split_at == -1 or split_at < MAX_DESC // 2:
            split_at = MAX_DESC

        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    if text:
        chunks.append(text)
    return chunks


class PaginatorView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed], timeout: int = 600) -> None:
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current = 0
        self._refresh()

    def _refresh(self) -> None:
        self.prev_button.disabled = self.current == 0
        self.next_button.disabled = self.current == len(self.embeds) - 1
        if self.counter:
            self.counter.label = f"{self.current + 1}/{len(self.embeds)}"

    @discord.ui.button(label="\u25c0", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.current -= 1
        self._refresh()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    @discord.ui.button(label="\u2022", style=discord.ButtonStyle.secondary, disabled=True)
    async def counter(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        pass

    @discord.ui.button(label="\u25b6", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.current += 1
        self._refresh()
        await interaction.response.edit_message(embed=self.embeds[self.current], view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True


def build_embeds(title: str, text: str, color: int, footer: str = None) -> list[discord.Embed]:
    """Split long text into embed pages with navigation."""
    text = sanitize(text)
    chunks = _split_text(text)
    embeds: list[discord.Embed] = []
    for i, chunk in enumerate(chunks):
        embed = discord.Embed(title=sanitize(title[:256]), description=chunk, color=color)
        parts = []
        if footer:
            parts.append(footer)
        if len(chunks) > 1:
            parts.append(f"Page {i+1}/{len(chunks)}")
        if parts:
            embed.set_footer(text=" \u00b7 ".join(parts))
        embeds.append(embed)
    return embeds


async def send_paginated(
    interaction_or_channel,
    title: str,
    text: str,
    color: int,
    footer: str = None,
    ephemeral: bool = False,
    author_name: str = None,
    author_icon: str = None,
) -> None:
    """Send a potentially-long response as one or more embed pages.

    Accepts either a discord.Interaction (uses followup) or a
    discord.abc.Messageable (uses send).
    """
    embeds = build_embeds(title, text, color, footer)
    for e in embeds:
        if author_name:
            e.set_author(name=author_name, icon_url=author_icon)

    if isinstance(interaction_or_channel, discord.Interaction):
        if len(embeds) == 1:
            await interaction_or_channel.followup.send(embed=embeds[0], ephemeral=ephemeral)
        else:
            view = PaginatorView(embeds)
            await interaction_or_channel.followup.send(embed=embeds[0], view=view, ephemeral=ephemeral)
    else:
        if len(embeds) == 1:
            await interaction_or_channel.send(embed=embeds[0])
        else:
            view = PaginatorView(embeds)
            await interaction_or_channel.send(embed=embeds[0], view=view)
