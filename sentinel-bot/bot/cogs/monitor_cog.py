from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.agent_manager import AgentManager
from core.memory import SessionMemory
from core.rate_limiter import RateLimiter
from core.utils import safe_call
from ..views.loot_view import LootView
from ..notifications import styled_embed, status_embed, session_embed, error_embed, THEME


class MonitorCog(commands.Cog):
    def __init__(self, bot: commands.Bot, agent_manager: AgentManager, memory: SessionMemory, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.agent_manager = agent_manager
        self.memory = memory
        self.rate_limiter = rate_limiter

    async def _get_agent(self, interaction: discord.Interaction):
        return await self.agent_manager.get_agent_for_user(str(interaction.user.id))

    @app_commands.command(name="status", description="Get agent VM status")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        agent = await self._get_agent(interaction)
        msg = await safe_call(interaction, lambda: agent.get_status(), "get status")
        if msg is None or msg.type == "error":
            return

        cpu = msg.payload.get("cpu_percent")
        ram_used = msg.payload.get("ram_used_mb")
        ram_total = msg.payload.get("ram_total_mb")
        disk_free = msg.payload.get("disk_free_gb")
        ovt_version = msg.payload.get("ovt_version")
        proc_count = len(msg.payload.get("running_processes", []))

        embed = status_embed(
            "VM Status",
            extra_fields=[
                ("CPU", f"{cpu:.1f}%" if cpu is not None else "n/a", True),
                ("RAM", f"{ram_used}/{ram_total} MB", True),
                ("Disk Free", f"{disk_free:.2f} GB" if disk_free is not None else "n/a", True),
                ("Processes", str(proc_count), True),
            ],
        )
        if ovt_version:
            embed.add_field(name="OVT Version", value=ovt_version, inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="loot", description="List loot files on the agent VM")
    async def loot(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        agent = await self._get_agent(interaction)
        msg = await safe_call(interaction, lambda: agent.get_loot(), "get loot")
        if msg is None or msg.type == "error":
            return

        files = msg.payload.get("files", [])
        view = LootView(files, agent=agent)
        await interaction.followup.send("Loot files:", view=view)

    @app_commands.command(name="readloot", description="Read a loot file from the agent VM")
    async def read_loot(self, interaction: discord.Interaction, path: str) -> None:
        await interaction.response.defer()
        agent = await self._get_agent(interaction)
        if ".." in path or path.startswith("/") or path.startswith("\\"):
            await interaction.followup.send("\u274c Path traversal detected: `..`, absolute paths, and symlinks are not allowed.")
            return
        msg = await safe_call(interaction, lambda: self.agent.read_loot_file(path), "read loot")
        if msg is None or msg.type == "error":
            return

        content = msg.payload.get("content", "")
        if not content:
            content = "(empty)"
        if len(content) > 1800:
            content = content[:1800] + "\n...[truncated]"
        await interaction.followup.send(f"```\n{content}\n```")

    @app_commands.command(name="session", description="Show current session summary")
    async def session(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        await safe_call(interaction, lambda: self.memory.get_or_create_session(session_id), "get session")
        ctx = await safe_call(interaction, lambda: self.memory.get_session_context(session_id), "get session context")
        if ctx is None:
            return

        embed = session_embed("Session Summary")

        if ctx.get("session"):
            s = ctx["session"]
            embed.add_field(
                name="Target",
                value=f"DC: `{s.get('dc_host', '?')}`, Domain: `{s.get('domain', '?')}`",
                inline=False,
            )

        cmds = ctx.get("recent_commands", [])
        if cmds:
            cmd_text = "\n".join(
                f"{'\u2705' if c['exit_code']==0 else '\u274c'} `{c['command'][:60]}`"
                for c in cmds[:10]
            )
            embed.add_field(name=f"Commands Run ({len(cmds)} total)", value=cmd_text, inline=False)

        findings = ctx.get("findings", [])
        if findings:
            f_text = "\n".join(
                f"[{f['severity'].upper()}] {f['type']}: {f['title']}"
                for f in findings[:8]
            )
            embed.add_field(name=f"Findings ({len(findings)} total)", value=f_text, inline=False)

        await interaction.followup.send(embed=embed)
