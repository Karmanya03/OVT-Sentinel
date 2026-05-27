from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.agent_manager import AgentManager, NoAgentError
from core.rate_limiter import RateLimiter
from ..notifications import styled_embed, error_embed, THEME, EMOJIS


class AgentCog(commands.Cog):
    def __init__(self, bot: commands.Bot, agent_manager: AgentManager, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.agent_manager = agent_manager
        self.rate_limiter = rate_limiter

    agent_group = app_commands.Group(name="agent", description="Manage your attack VM connection")

    @agent_group.command(name="connect", description="Connect your own attack VM to this bot")
    @app_commands.describe(
        ws_url="WebSocket URL of your agent (e.g. ws://your-vm:7331)",
        label="Optional friendly label for this agent",
    )
    async def agent_connect(self, interaction: discord.Interaction, ws_url: str, label: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)

        try:
            client = await self.agent_manager.register_agent(
                user_id, ws_url, self.bot.bot_config.sentinel_token, label=label,
            )
            if client.is_connected:
                embed = styled_embed(
                    f"{EMOJIS['done']} Agent Connected",
                    f"Your attack VM is ready.\nURL: `{ws_url}`",
                    THEME["success"],
                    footer=f"{interaction.user.display_name}",
                )
            else:
                embed = styled_embed(
                    f"{EMOJIS['warn']} Agent Registered (Offline)",
                    f"Agent saved but connection failed. It will auto-reconnect on first command.\nURL: `{ws_url}`",
                    THEME["warning"],
                    footer=f"{interaction.user.display_name}",
                )
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            embed.timestamp = datetime.now(timezone.utc)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(embed=error_embed("Connection Failed", str(e)), ephemeral=True)

    @agent_group.command(name="disconnect", description="Disconnect your attack VM from this bot")
    async def agent_disconnect(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)

        await self.agent_manager.remove_agent(user_id)
        embed = styled_embed(
            "\u274c Agent Disconnected",
            "Your attack VM has been unregistered and disconnected.",
            THEME["neutral"],
            footer=f"{interaction.user.display_name}",
        )
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @agent_group.command(name="status", description="Show your agent connection status")
    async def agent_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)

        row = await self.agent_manager.memory.get_agent(user_id)
        if not row:
            embed = styled_embed(
                f"{EMOJIS['info']} No Agent Configured",
                "You haven't connected an attack VM yet.\nUse `/agent connect ws://your-vm:7331` to get started.",
                THEME["info"],
                footer=f"{interaction.user.display_name}",
            )
            embed.timestamp = datetime.now(timezone.utc)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        client = self.agent_manager._agents.get(user_id)
        connected = client is not None and client.is_connected
        hostname = client.hostname if client else ""

        embed = styled_embed(
            f"{'🟢' if connected else '🔴'} Agent Status",
            color=THEME["success"] if connected else THEME["danger"],
            fields=[
                ("URL", f"`{row['ws_url']}`", False),
                ("Status", "\u2705 Connected" if connected else "\u274c Disconnected", True),
                ("Hostname", f"`{hostname}`" if hostname else "`?`", True),
                ("Label", row.get("label") or "—", True),
            ],
            footer=f"{interaction.user.display_name}",
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @agent_group.command(name="list", description="List all registered agents (admin only)")
    async def agent_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        rows = await self.agent_manager.memory.list_agents()
        if not rows:
            await interaction.followup.send("No agents registered.", ephemeral=True)
            return

        embed = styled_embed(
            "Registered Agents",
            color=THEME["info"],
            timestamp=False,
        )
        for row in rows:
            uid = row["user_id"]
            client = self.agent_manager._agents.get(uid)
            status_emoji = "\u2705" if client and client.is_connected else "\u274c"
            embed.add_field(
                name=f"{status_emoji} `{uid[:12]}...`",
                value=f"URL: `{row['ws_url']}`\nLabel: {row.get('label') or '—'}",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)
