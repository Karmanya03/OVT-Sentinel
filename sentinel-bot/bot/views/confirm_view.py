import discord

from ..notifications import warn_embed, styled_embed, THEME


class ConfirmView(discord.ui.View):
    def __init__(self, title: str = "Destructive Operation", description: str = "") -> None:
        super().__init__(timeout=30)
        self.confirmed = False
        self._title = title
        self._description = description

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        try:
            embed = warn_embed("Timed Out", "This confirmation expired. Run again to retry.")
            await self._message.edit(embed=embed, view=self)
        except Exception:
            pass

    async def send(self, interaction: discord.Interaction, description: str) -> None:
        self._description = description
        embed = warn_embed(self._title, self._description)
        await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        self._message = await interaction.original_response()

    @discord.ui.button(label="\u2705 Confirm", style=discord.ButtonStyle.danger, emoji="\u26a0\ufe0f")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        for child in self.children:
            child.disabled = True
        embed = styled_embed("Confirmed", "Executing command...", THEME["success"])
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="\u274c Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        for child in self.children:
            child.disabled = True
        embed = styled_embed("Cancelled", "Command was not executed.", THEME["danger"])
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()
