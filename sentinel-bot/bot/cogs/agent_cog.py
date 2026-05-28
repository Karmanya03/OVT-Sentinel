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
        token="Optional agent auth token (if omitted a token will be generated)",
        tunnel="Set to True if using --tunnel (public URL via bore); False for direct LAN/public IP",
    )
    async def agent_connect(self, interaction: discord.Interaction, ws_url: str, label: str = "", token: str = "", tunnel: bool = True) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        # Determine agent token: prefer explicit token param, then global bootstrap token, else generate per-agent token
        if token:
            agent_token = token
        elif self.bot.bot_config.sentinel_token:
            agent_token = self.bot.bot_config.sentinel_token
        else:
            import secrets
            agent_token = secrets.token_hex(32)

        try:
            client = await self.agent_manager.register_agent(
                user_id, ws_url, agent_token, label=label,
            )
            if client.is_connected:
                embed = styled_embed(
                    f"{EMOJIS['done']} Agent Connected",
                    f"Your attack VM is ready.\nURL: `{ws_url}`",
                    THEME["success"],
                    footer=f"{interaction.user.display_name}",
                )
            else:
                # Show startup instruction with the token so the user can start their agent
                if tunnel:
                    register_url = self.bot.bot_config.bot_public_url
                    if register_url:
                        register_flag = f' --bot-register-url "{register_url}/register"'
                        extra = f"No `/agent connect` needed — the bot will receive the tunnel URL automatically."
                    else:
                        register_flag = ""
                        extra = f"After starting, copy the tunnel URL from terminal and run:\n`/agent connect ws_url:<tunnel-url> tunnel:True`"
                    cmd = f"sentinel-agent --token \"{agent_token}\" --tunnel{register_flag}"
                    instructions = (
                        f"**Quick start (auto-tunnel):**\n```\n# Install bore (one-time)\ncargo install bore-cli\n\n{cmd}\n```\n{extra}"
                    )
                else:
                    cmd = f"sentinel-agent --token \"{agent_token}\""
                    instructions = (
                        f"**Start the agent:**\n```\n{cmd}\n```\n"
                        f"Make sure your VM is reachable at `{ws_url}` from the internet."
                    )
                embed = styled_embed(
                    f"{EMOJIS['warn']} Agent Registered (Offline)",
                    f"Agent saved but connection failed. It will auto-reconnect on first command.\n\n{instructions}\n\nKeep this token secret — it authenticates your agent.\nURL: `{ws_url}`",
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
                "You haven't connected an attack VM yet.\n1. Install bore on Kali: `cargo install bore-cli`\n2. Run: `sentinel-agent --tunnel --token \"<token>\"`\n3. No `/agent connect` needed — auto-registers with the bot.",
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

    @agent_group.command(name="list", description="Show your registered agents")
    async def agent_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        row = await self.agent_manager.memory.get_agent(user_id)
        if not row:
            await interaction.followup.send("You haven't registered any agents.", ephemeral=True)
            return

        client = self.agent_manager._agents.get(user_id)
        status_emoji = "\u2705" if client and client.is_connected else "\u274c"

        embed = styled_embed(
            "Your Agents",
            color=THEME["info"],
            fields=[
                (f"{status_emoji} {row.get('label') or user_id[:12]}", f"URL: `{row['ws_url']}`", False),
            ],
            timestamp=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
