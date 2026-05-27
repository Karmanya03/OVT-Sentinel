from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.agent_manager import AgentManager
from core.rate_limiter import RateLimiter
from ..notifications import styled_embed, status_embed, THEME


class AgentCog(commands.Cog):
    def __init__(self, bot: commands.Bot, agent_manager: AgentManager, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.agent_manager = agent_manager
        self.rate_limiter = rate_limiter

    agent_group = app_commands.Group(name="agent", description="Manage connected agent VMs")

    @agent_group.command(name="list", description="List all registered agents with connection status")
    async def agent_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        agents = self.agent_manager.list_agents()
        if not agents:
            await interaction.followup.send("No agents registered.")
            return

        embed = styled_embed(
            "Registered Agents",
            color=THEME["info"],
            timestamp=False,
        )
        for a in agents:
            status_emoji = "\u2705" if a["connected"] else "\u274c"
            active_marker = " \u25c6" if a["active"] else ""
            hostname = a["hostname"] or "?"
            embed.add_field(
                name=f"{status_emoji} {a['name']}{active_marker}",
                value=f"Host: `{hostname}`\nURL: `{a['ws_url']}`",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @agent_group.command(name="select", description="Select the active agent for commands")
    @app_commands.describe(name="Agent name to activate")
    async def agent_select(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer()
        try:
            self.agent_manager.set_active(name)
            await interaction.followup.send(f"\u2705 Active agent set to `{name}`")
        except KeyError:
            await interaction.followup.send(f"\u274c Agent `{name}` not found")

    @agent_group.command(name="add", description="Register a new agent VM")
    @app_commands.describe(name="Unique name for the agent", ws_url="WebSocket URL (e.g. ws://host:7331)")
    async def agent_add(self, interaction: discord.Interaction, name: str, ws_url: str) -> None:
        await interaction.response.defer()
        try:
            client = self.agent_manager.register(name, ws_url, self.bot.bot_config.sentinel_token)
            try:
                await client.connect(max_retries=2, retry_delay=1.0)
                try:
                    status = await client.get_status()
                    hostname = status.payload.get("hostname", status.payload.get("os_hostname", ""))
                    if hostname:
                        client.hostname = hostname
                except Exception:
                    pass
                await interaction.followup.send(
                    f"\u2705 Agent `{name}` registered and connected at `{ws_url}`"
                )
            except Exception as exc:
                await interaction.followup.send(
                    f"\u26a0\ufe0f Agent `{name}` registered but connection failed: {exc}"
                )
        except ValueError as e:
            await interaction.followup.send(f"\u274c {e}")

    @agent_group.command(name="remove", description="Remove a registered agent")
    @app_commands.describe(name="Agent name to remove")
    async def agent_remove(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer()
        try:
            self.agent_manager.unregister(name)
            await interaction.followup.send(f"\u2705 Agent `{name}` removed")
        except KeyError:
            await interaction.followup.send(f"\u274c Agent `{name}` not found")

    @agent_group.command(name="info", description="Show active agent details")
    async def agent_info(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        try:
            client = self.agent_manager.get_active()
        except RuntimeError as e:
            await interaction.followup.send(str(e))
            return

        embed = styled_embed(
            f"Active Agent: {self.agent_manager.active_name or '?'}",
            color=THEME["success"] if client.is_connected else THEME["danger"],
            fields=[
                ("URL", f"`{client.ws_url}`", False),
                ("Connected", "\u2705 Yes" if client.is_connected else "\u274c No", True),
                ("Hostname", f"`{hostname}`", True),
            ],
        )
        await interaction.followup.send(embed=embed)
