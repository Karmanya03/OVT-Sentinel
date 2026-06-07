import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.agent_manager import AgentManager
from core.llm_brain import LLMBrain
from core.memory import SessionMemory
from core.rate_limiter import RateLimiter
from core.utils import safe_call
from ..notifications import (
    styled_embed, session_embed, ai_embed, cmd_embed, error_embed,
    THEME, EMOJIS,
)
from ..paginator import send_paginated

log = logging.getLogger("sentinel.session")


class SessionCog(commands.Cog):
    def __init__(self, bot: commands.Bot, memory: SessionMemory, llm: LLMBrain,
                 agent_manager: AgentManager, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.memory = memory
        self.llm = llm
        self.agent_manager = agent_manager
        self.rate_limiter = rate_limiter

    async def _rate_limit(self, interaction: discord.Interaction) -> None:
        await self.rate_limiter.acquire(f"user:{interaction.user.id}")

    @app_commands.command(name="session-start", description="Start a new pentest session in a dedicated thread")
    @app_commands.describe(name="Optional label for this session")
    async def session_start(self, interaction: discord.Interaction, name: str = "") -> None:
        await self._rate_limit(interaction)
        await interaction.response.defer(ephemeral=True)

        session_id = str(interaction.user.id)
        await self.memory.get_or_create_session(session_id)

        existing_thread_id = await self.memory.get_thread_by_session(session_id)
        if existing_thread_id:
            thread = self.bot.get_channel(existing_thread_id)
            if thread and isinstance(thread, discord.Thread) and not thread.archived:
                await interaction.followup.send(
                    f"You already have an active session in {thread.mention}. "
                    f"Use `/session-end` first or `/resume` in that thread.",
                    ephemeral=True,
                )
                return

        thread = await interaction.channel.create_thread(
            name=f"session-{interaction.user.display_name}{'-' + name[:20] if name else ''}",
            type=discord.ChannelType.public_thread,
            reason=f"Session started by {interaction.user}",
        )

        await self.memory.register_thread(thread.id, session_id, interaction.guild_id or 0, interaction.channel_id)

        embed = session_embed(
            "Session Started",
            f"Welcome {interaction.user.mention}. This thread is your dedicated session workspace.",
            [
                ("\ud83d\udfe2 Status", "**Active** \u2014 all commands & chat output will appear here.", False),
                ("\ud83d\udcdd Session ID", f"`{session_id}`", True),
                ("\ud83d\udd17 Resume", f"Use `/resume` in this thread to continue later.", True),
                ("\u274c End", f"Use `/session-end` in this thread to finish.", True),
            ],
            footer=f"OVT-Sentinel \u2022 {interaction.user.display_name}",
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        await thread.send(embed=embed)

        await self.memory.log_event("session_start", f"Session {session_id} started in thread {thread.id}")
        await interaction.followup.send(f"Session started in {thread.mention} \u2192", ephemeral=True)

    @app_commands.command(name="session-end", description="End the current session and archive this thread")
    async def session_end(self, interaction: discord.Interaction) -> None:
        await self._rate_limit(interaction)

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This command must be used in a session thread. Use `/session-start` first.",
                ephemeral=True,
            )
            return

        mapping = await self.memory.get_session_by_thread(interaction.channel_id)
        if not mapping:
            await interaction.response.send_message(
                "This thread is not linked to any active session.", ephemeral=True
            )
            return

        session_id = mapping["session_id"]
        summary = await self.memory.get_session_context(session_id)

        cmds_run = len(summary.get("recent_commands", []))
        findings_count = len(summary.get("findings", []))

        await self.memory.update_session(session_id, status="ended")
        await self.memory.remove_thread_mapping(interaction.channel_id)

        embed = session_embed(
            "Session Ended",
            f"Session `{session_id[:12]}...` has been closed.",
            [
                ("\ud83d\udccb Commands Run", str(cmds_run), True),
                ("\ud83d\udd0d Findings", str(findings_count), True),
                ("\ud83d\udfe2 Status", "**Ended** \u2014 this thread will be archived.", False),
            ],
            footer="OVT-Sentinel",
        )
        await interaction.response.send_message(embed=embed)
        await self.memory.log_event("session_end", f"Session {session_id} ended in thread {interaction.channel_id}")
        await interaction.channel.edit(archived=True, locked=False)

    @app_commands.command(name="resume", description="Resume an existing session in this thread")
    async def resume(self, interaction: discord.Interaction) -> None:
        await self._rate_limit(interaction)

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Use `/resume` inside the thread you want to resume.", ephemeral=True
            )
            return

        mapping = await self.memory.get_session_by_thread(interaction.channel_id)
        if not mapping:
            await interaction.response.send_message(
                "No session is linked to this thread. Use `/session-start` to begin.", ephemeral=True
            )
            return

        session_id = mapping["session_id"]
        await self.memory.get_or_create_session(session_id)
        await self.memory.update_session(session_id, status="active")

        ctx = await self.memory.get_session_context(session_id)
        cmds = ctx.get("recent_commands", [])

        embed = session_embed(
            f"Session Resumed",
            f"Welcome back {interaction.user.mention}. Resuming session `{session_id[:12]}...`",
            [
                ("\ud83d\udccb Previous Commands", str(len(cmds)), True),
                ("\ud83d\udd0d Findings", str(len(ctx.get("findings", []))), True),
            ],
            footer="OVT-Sentinel",
        )
        if cmds:
            recent = "\n".join(
                f"{EMOJIS['done'] if c['exit_code'] == 0 else EMOJIS['fail']} `{c['command'][:60]}`"
                for c in cmds[-5:]
            )
            embed.add_field(name="Recent Commands", value=recent, inline=False)

        await interaction.response.send_message(embed=embed)
        await self.memory.log_event("session_resume", f"Session {session_id} resumed in thread {interaction.channel_id}")

    @app_commands.command(name="chat", description="Chat with the AI about AD pentesting")
    @app_commands.describe(message="Your message or question")
    async def chat(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.defer()
        await self._rate_limit(interaction)
        session_id = str(interaction.user.id)
        await self.memory.get_or_create_session(session_id)

        target = interaction.channel
        thread_id = await self.memory.get_thread_by_session(session_id)
        if thread_id:
            thread = self.bot.get_channel(thread_id)
            if thread and isinstance(thread, discord.Thread) and not thread.archived:
                target = thread

        await target.typing()
        response = await safe_call(
            interaction,
            lambda: self.llm.chat(session_id, str(interaction.user.id), message),
            "AI response",
        )
        if response is None:
            return

        is_thread = isinstance(target, discord.Thread) and target.id != interaction.channel_id
        if is_thread:
            await send_paginated(
                target, "OVT-Sentinel Chat", response, THEME["ai"],
                footer=interaction.user.display_name,
                author_name=interaction.user.display_name,
                author_icon=interaction.user.display_avatar.url,
            )
            await interaction.response.send_message(
                f"Response posted in {target.mention} \u2192", ephemeral=True
            )
        else:
            await send_paginated(
                interaction, "OVT-Sentinel Chat", response, THEME["ai"],
                footer=interaction.user.display_name,
                author_name=interaction.user.display_name,
                author_icon=interaction.user.display_avatar.url,
            )

    @app_commands.command(name="exploit", description="Generate exploits/malware/offensive content (uncensored model)")
    @app_commands.describe(prompt="Describe the exploit or offensive tool you need")
    async def exploit(self, interaction: discord.Interaction, prompt: str) -> None:
        await interaction.response.defer()
        await self._rate_limit(interaction)
        session_id = str(interaction.user.id)
        await self.memory.get_or_create_session(session_id)

        target = interaction.channel
        thread_id = await self.memory.get_thread_by_session(session_id)
        if thread_id:
            thread = self.bot.get_channel(thread_id)
            if thread and isinstance(thread, discord.Thread) and not thread.archived:
                target = thread

        await target.typing()
        response = await safe_call(
            interaction,
            lambda: self.llm.chat_unsafe(session_id, str(interaction.user.id), prompt),
            "exploit response",
        )
        if response is None:
            return

        is_thread = isinstance(target, discord.Thread) and target.id != interaction.channel_id
        if is_thread:
            await send_paginated(
                target, "OVT-Sentinel Exploit", response, 0xe74c3b,
                footer=interaction.user.display_name,
                author_name=interaction.user.display_name,
                author_icon=interaction.user.display_avatar.url,
            )
            await interaction.response.send_message(
                f"Exploit posted in {target.mention} \u2192", ephemeral=True
            )
        else:
            await send_paginated(
                interaction, "OVT-Sentinel Exploit", response, 0xe74c3b,
                footer=interaction.user.display_name,
                author_name=interaction.user.display_name,
                author_icon=interaction.user.display_avatar.url,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if isinstance(message.channel, discord.Thread):
            mapping = await self.memory.get_session_by_thread(message.channel.id)
            if mapping:
                session_id = mapping["session_id"]
                async with message.channel.typing():
                    try:
                        response = await self.llm.chat(
                            session_id, str(message.author.id), message.content
                        )
                        await send_paginated(
                            message.channel, "OVT-Sentinel Chat", response, THEME["ai"],
                            footer=message.author.display_name,
                            author_name=message.author.display_name,
                            author_icon=message.author.display_avatar.url,
                        )
                    except Exception as e:
                        log.error("Thread chat error: %s", e)
                return

        if self.bot.user in message.mentions:
            session_id = str(message.author.id)
            await self.memory.get_or_create_session(session_id)
            content = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            if not content:
                return

            thread_id = await self.memory.get_thread_by_session(session_id)
            target = message.channel
            if thread_id:
                thread = self.bot.get_channel(thread_id)
                if thread and isinstance(thread, discord.Thread) and not thread.archived:
                    target = thread

            async with target.typing():
                try:
                    response = await self.llm.chat(
                        session_id, str(message.author.id), content
                    )
                    await send_paginated(
                        target, "OVT-Sentinel Chat", response, THEME["ai"],
                        footer=message.author.display_name,
                        author_name=message.author.display_name,
                        author_icon=message.author.display_avatar.url,
                    )
                except Exception as e:
                    log.error("Mention chat error: %s", e)
