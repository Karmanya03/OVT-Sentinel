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

    @agent_group.command(name="register", description="Generate a token and get the command to run on your Kali VM")
    @app_commands.describe(
        mode="Connectivity method (default: reverse with tunnel fallback)",
        label="Optional friendly label for this agent",
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="\U0001f504 Reverse (recommended) \u2014 agent connects outbound, auto-fallback to tunnel", value="reverse"),
        app_commands.Choice(name="\U0001f4e6 Tunnel (cloudflared) \u2014 agent behind NAT, cloudflared required", value="tunnel"),
        app_commands.Choice(name="\U0001f517 Direct \u2014 raw WS server, needs public IP / port forward", value="direct"),
    ])
    async def agent_register(self, interaction: discord.Interaction, mode: str = "reverse", label: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)
        import secrets
        agent_token = secrets.token_hex(32)
        await self.agent_manager.memory.save_agent(user_id, "pending", agent_token, label=label)

        raw_url = (self.bot.bot_config.bot_public_url or "").strip().rstrip("/")

        # Normalise: add https:// if no scheme given
        if raw_url and not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = f"https://{raw_url}"

        if raw_url:
            register_flag = f' --bot-register-url "{raw_url}/register"'
        else:
            register_flag = ""

        if mode == "reverse":
            if not raw_url:
                instructions = (
                    f"**Error:** `BOT_PUBLIC_URL` not configured on the server.\n"
                    f"Set it in Koyeb dashboard or use `mode: Tunnel` instead."
                )
            else:
                ws_url = raw_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
                cmd = f"sudo ./sentinel-agent --token \"{agent_token}\" --connect-to-bot \"{ws_url}/agent-ws\" --fallback-tunnel{register_flag}"
                instructions = (
                    f"**Agent connects outbound to the bot** \u2014 no tunnel needed.\n"
                    f"If the reverse connection fails, it auto-falls back to a cloudflared tunnel.\n\n"
                    f"**Install cloudflared (one-time, for fallback):**\n"
                    f"```\nsudo curl -sSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared\nsudo chmod +x /usr/local/bin/cloudflared\n```\n\n"
                    f"**Run on Kali:**\n```\n{cmd}\n```\n"
                    f"No `/agent connect` needed \u2014 automagic!"
                )

        elif mode == "tunnel":
            cmd = f"sudo ./sentinel-agent --token \"{agent_token}\" --tunnel{register_flag}"
            if register_flag:
                extra = "No `/agent connect` needed \u2014 the bot will receive the tunnel URL automatically."
            else:
                extra = "After starting, copy the tunnel URL from terminal and connect:\n`/agent connect ws_url:<tunnel-url>`"
            instructions = (
                f"**Install cloudflared (one-time):**\n"
                f"```\nsudo curl -sSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared\nsudo chmod +x /usr/local/bin/cloudflared\n```\n\n"
                f"**Run on Kali:**\n```\n{cmd}\n```\n{extra}"
            )

        else:  # direct
            cmd = f"sudo ./sentinel-agent --token \"{agent_token}\""
            instructions = (
                f"**Run on Kali:**\n```\n{cmd}\n```\n"
                f"Then connect with your VM's public IP:\n`/agent connect ws_url:ws://YOUR_IP:7331`"
            )

        embed = styled_embed(
            f"{EMOJIS['info']} Agent Token Generated",
            f"Use this token to authenticate your agent.\n\n{instructions}\n\n**Token:** `{agent_token}`\nKeep this secret!",
            THEME["info"],
            footer=f"{interaction.user.display_name}",
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.timestamp = datetime.now(timezone.utc)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @agent_group.command(name="connect", description="Connect your attack VM using its WebSocket URL")
    @app_commands.describe(
        ws_url="WebSocket URL (e.g. ws://bore.pub:22698 or ws://your-vm:7331)",
        label="Optional friendly label for this agent",
        token="Optional auth token (uses stored token from /agent register if omitted)",
    )
    async def agent_connect(self, interaction: discord.Interaction, ws_url: str, label: str = "", token: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)

        if token:
            agent_token = token
        else:
            row = await self.agent_manager.memory.get_agent(user_id)
            if row and row.get("token"):
                agent_token = row["token"]
            elif self.bot.bot_config.sentinel_token:
                agent_token = self.bot.bot_config.sentinel_token
            else:
                import secrets
                agent_token = secrets.token_hex(32)

        is_tunnel = "trycloudflare" in ws_url

        try:
            client = await self.agent_manager.register_agent(
                user_id, ws_url, agent_token, label=label,
            )
            if client.is_connected:
                embed = styled_embed(
                    f"{EMOJIS['done']} Agent Connected",
                    f"Your attack VM is ready.\nURL: `{ws_url}`\n{'Tunnel via bore' if is_tunnel else 'Direct connection'}",
                    THEME["success"],
                    footer=f"{interaction.user.display_name}",
                )
            else:
                embed = styled_embed(
                    f"{EMOJIS['warn']} Agent Saved (Offline)",
                    f"Agent saved but couldn't connect. It will auto-reconnect on first command.\nURL: `{ws_url}`",
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
                "Start with `/agent register` to get a token and the command to run on Kali.\nThen use `/agent connect ws_url:<tunnel-url>` once the agent is running.",
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
