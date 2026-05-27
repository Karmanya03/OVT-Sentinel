import discord
from discord import app_commands
from discord.ext import commands

from core.memory import SessionMemory
from core.rate_limiter import RateLimiter
from core.utils import safe_call
from ..notifications import styled_embed, cmd_embed, THEME


class HistoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot, memory: SessionMemory, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.memory = memory
        self.rate_limiter = rate_limiter

    @app_commands.command(name="log", description="Show recent Sentinel events")
    async def log(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        events = await safe_call(interaction, lambda: self.memory.get_recent_events(10), "get events")
        if events is None:
            return
        if not events:
            await interaction.followup.send("No events logged yet")
            return

        lines = [f"{ts} {etype}: {data}" for ts, etype, data in events]
        text = "\n".join(lines)
        if len(text) > 1800:
            text = text[:1800] + "\n...[truncated]"
        await interaction.followup.send(f"```\n{text}\n```")

    @app_commands.command(name="history", description="Show command history for this session")
    async def history(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        await safe_call(interaction, lambda: self.memory.get_or_create_session(session_id), "get session")
        ctx = await safe_call(interaction, lambda: self.memory.get_session_context(session_id), "get session context")
        if ctx is None:
            return
        cmds = ctx.get("recent_commands", [])

        if not cmds:
            await interaction.followup.send("No commands run yet in this session.")
            return

        lines = []
        for i, c in enumerate(cmds, 1):
            status = "\u2705" if c["exit_code"] == 0 else "\u274c"
            lines.append(f"{i}. {status} `{c['command'][:70]}`")

        embed = styled_embed("Command History", "\n".join(lines), THEME["ai"])
        await interaction.followup.send(embed=embed)
