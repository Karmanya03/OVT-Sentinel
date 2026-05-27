import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.agent_manager import AgentManager
from core.llm_brain import LLMBrain
from core.memory import SessionMemory
from core.rate_limiter import RateLimiter
from config import Settings
from .cogs.agent_cog import AgentCog
from .cogs.ai_cog import AICog
from .cogs.browser_cog import BrowserCog
from .cogs.help_cog import HelpCog
from .cogs.history_cog import HistoryCog
from .cogs.info_cog import InfoCog
from .cogs.monitor_cog import MonitorCog
from .cogs.run_cog import RunCog
from .cogs.session_cog import SessionCog

log = logging.getLogger("sentinel.bot")


class SentinelBot(commands.Bot):
    def __init__(self, agent_manager: AgentManager, memory: SessionMemory, llm: LLMBrain, config: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.agent_manager = agent_manager
        self.memory = memory
        self.llm = llm
        self.bot_config = config
        self.rate_limiter = RateLimiter()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cfg = self.bot_config
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        channel_id = interaction.channel_id

        if cfg.allowed_guild_ids and guild_id and guild_id not in cfg.allowed_guild_ids:
            log.warning("Blocked interaction from guild %s (user %s)", guild_id, user_id)
            await interaction.response.send_message(
                "This bot is not authorized in this guild.", ephemeral=True
            )
            return False

        if cfg.allowed_user_ids and user_id not in cfg.allowed_user_ids:
            log.warning("Blocked interaction from unauthorized user %s", user_id)
            await interaction.response.send_message(
                "You are not authorized to use this bot.", ephemeral=True
            )
            return False

        if cfg.allowed_channel_ids and channel_id and channel_id not in cfg.allowed_channel_ids:
            log.warning("Blocked interaction from unauthorized channel %s (user %s)", channel_id, user_id)
            await interaction.response.send_message(
                "This bot is not authorized in this channel.", ephemeral=True
            )
            return False

        return True

    async def setup_hook(self) -> None:
        await self.add_cog(RunCog(self, self.agent_manager, self.memory, self.llm, self.bot_config, self.rate_limiter))
        await self.add_cog(MonitorCog(self, self.agent_manager, self.memory, self.rate_limiter))
        await self.add_cog(AICog(self, self.llm, self.memory, self.agent_manager, self.bot_config, self.rate_limiter))
        await self.add_cog(BrowserCog(self, self.agent_manager, self.memory, self.rate_limiter, llm=self.llm))
        await self.add_cog(HistoryCog(self, self.memory, self.rate_limiter))
        await self.add_cog(AgentCog(self, self.agent_manager, self.rate_limiter))
        await self.add_cog(HelpCog(self))
        await self.add_cog(InfoCog(self))
        await self.add_cog(SessionCog(self, self.memory, self.llm, self.agent_manager, self.rate_limiter))
        await self.tree.sync()

    async def on_ready(self) -> None:
        activity = discord.Activity(type=discord.ActivityType.watching, name="AD attacks")
        await self.change_presence(activity=activity)

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        log.error("Command error from %s: %s", ctx.author, error)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log.error("Slash command error from %s: %s", interaction.user, error)
        msg = f"\u274c Command error: {error}"
        if len(msg) > 1900:
            msg = msg[:1900] + "..."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    async def close(self) -> None:
        log.info("Shutting down...")
        try:
            await self.agent_manager.close_all()
        except Exception:
            pass
        try:
            self.memory.conn.close()
        except Exception:
            pass
        await super().close()
