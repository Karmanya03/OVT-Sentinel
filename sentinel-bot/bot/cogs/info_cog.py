import discord
from discord import app_commands
from discord.ext import commands

from ..notifications import styled_embed, THEME, EMOJIS


class InfoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="info", description="Show information about OVT-Sentinel")
    async def info(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title=f"{EMOJIS['shield']} OVT-Sentinel",
            description=(
                "AI-powered Discord bot designed to orchestrate "
                "**Overthrone (OVT)** Active Directory pentesting operations."
            ),
            color=THEME["primary"],
        )
        embed.add_field(
            name="\ud83d\udd17 About",
            value=(
                "OVT-Sentinel connects your Discord to a remote attack VM running "
                "[Overthrone](https://github.com/Karmanya03/Overthrone), "
                "providing seamless command execution, live streaming, loot management, "
                "system monitoring, and AI-driven analysis \u2014 all from within your server."
            ),
            inline=False,
        )
        embed.add_field(
            name="\ud83e\udde0 AI Brain",
            value=(
                "Multi-provider fallback (Groq \u2192 OpenAI \u2192 "
                "SambaNova \u2192 Cerebras \u2192 Ollama) with agentic tool calling, "
                "retry logic, and session-aware chat. Supports vision, web search, "
                "and automated attack path analysis."
            ),
            inline=False,
        )
        embed.add_field(
            name="\ud83d\udee1\ufe0f Security",
            value=(
                "Token-authenticated WebSocket, TLS support, user/guild/channel "
                "allowlists, destructive command confirmation, rate limiting, "
                "and no shell injection."
            ),
            inline=False,
        )
        embed.add_field(
            name="\ud83d\udc68\u200d\ud83d\udcbb Made by",
            value="[karmanya03](https://github.com/Karmanya03)",
            inline=True,
        )
        embed.add_field(
            name="\ud83d\udcc6 Version",
            value="v0.1.0",
            inline=True,
        )
        embed.add_field(
            name="\ud83d\udcbb Repository",
            value="[OVT-Sentinel](https://github.com/Karmanya03/OVT-Sentinel)",
            inline=True,
        )
        embed.add_field(
            name="\u26a1 Quick Start",
            value="`/help` \u2014 view all commands\n`/session-start` \u2014 begin a session",
            inline=False,
        )

        embed.set_thumbnail(
            url="https://cdn.discordapp.com/emojis/1055804536481648640.png"
        )
        embed.set_footer(text="OVT-Sentinel \u2022 Active Directory Pentesting Bot")
        from datetime import datetime, timezone
        embed.timestamp = datetime.now(timezone.utc)

        await interaction.followup.send(embed=embed, ephemeral=True)
