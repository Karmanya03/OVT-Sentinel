import base64
import io

import discord
from discord import app_commands
from discord.ext import commands

from core.agent_manager import AgentManager
from core.memory import SessionMemory
from core.rate_limiter import RateLimiter
from core.llm_brain import LLMBrain
from core.utils import safe_call
from ..notifications import styled_embed, ai_embed, error_embed, THEME
from ..paginator import send_paginated


class BrowserCog(commands.Cog):
    def __init__(self, bot: commands.Bot, agent_manager: AgentManager, memory: SessionMemory, rate_limiter: RateLimiter, llm: LLMBrain = None) -> None:
        self.bot = bot
        self.agent_manager = agent_manager
        self.memory = memory
        self.rate_limiter = rate_limiter
        self.llm = llm

    async def _get_agent(self, interaction: discord.Interaction):
        return await self.agent_manager.get_agent_for_user(str(interaction.user.id))

    async def _send_screenshot(self, interaction: discord.Interaction, msg, analyze: bool, screenshot_label: str = "Screenshot") -> None:
        if msg.type == "error":
            await interaction.followup.send(f"Agent error: {msg.payload.get('message')}")
            return

        data_b64 = msg.payload.get("data_base64", "")
        if not data_b64:
            await interaction.followup.send("No screenshot data returned")
            return

        image_bytes = base64.b64decode(data_b64)
        file = discord.File(io.BytesIO(image_bytes), filename="screenshot.png")
        await interaction.followup.send(file=file)

        if analyze and self.llm:
            await interaction.followup.send(f"Analyzing {screenshot_label.lower()} with AI...")
            try:
                vision_prompt = (
                    f"This is a {screenshot_label.lower()} from an Active Directory pentest VM. "
                    "Identify: what tools/terminals are visible, any visible commands or output, "
                    "what attack phase the user is in, "
                    "any errors or misconfigurations visible, "
                    "and what the single best next step should be."
                )
                analysis = await self.llm.analyze_image(image_bytes, vision_prompt)
                await send_paginated(interaction, f"{screenshot_label} Analysis", analysis, THEME["ai"])
            except Exception as e:
                await interaction.followup.send(f"{screenshot_label} analysis failed: {e}")

    @app_commands.command(name="screenshot", description="Take a VM screenshot and optionally analyze it with AI")
    @app_commands.describe(analyze="Whether to analyze the screenshot with AI (default: True)")
    async def screenshot(self, interaction: discord.Interaction, analyze: bool = True) -> None:
        await interaction.response.defer()
        agent = await self._get_agent(interaction)
        msg = await safe_call(interaction, lambda: agent.take_screenshot(), "take screenshot")
        if msg is None:
            return
        await self._send_screenshot(interaction, msg, analyze, "Screenshot")

    @app_commands.command(name="browse", description="Open a URL in the VM browser and return a screenshot")
    @app_commands.describe(url="URL to open in the VM browser", analyze="Analyze the page with AI (default: True)")
    async def browse(self, interaction: discord.Interaction, url: str, analyze: bool = True) -> None:
        await interaction.response.defer()
        from core.web_tools import validate_public_url
        err = validate_public_url(url)
        if err:
            await interaction.followup.send(f"\u274c {err}")
            return
        agent = await self._get_agent(interaction)
        msg = await safe_call(interaction, lambda: agent.browse_url(url), "browse URL")
        if msg is None:
            return
        await self._send_screenshot(interaction, msg, analyze, "Browser Screenshot")
