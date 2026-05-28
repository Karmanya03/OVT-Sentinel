import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import Settings
from core.agent_manager import AgentManager
from core.utils import safe_call

log = logging.getLogger("sentinel.ai")
from core.bloodhound_parser import analyze_bloodhound_json
from core.llm_brain import LLMBrain
from core.memory import SessionMemory
from core.rate_limiter import RateLimiter
from core.web_tools import web_search, web_fetch, search_vulnerabilities
from ..notifications import styled_embed, ai_embed, warn_embed, error_embed, THEME
from ..paginator import send_paginated


class AICog(commands.Cog):
    def __init__(self, bot: commands.Bot, llm: LLMBrain, memory: SessionMemory, agent_manager: AgentManager, config: Settings, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.llm = llm
        self.memory = memory
        self.agent_manager = agent_manager
        self.config = config
        self.rate_limiter = rate_limiter

    async def _get_agent(self, interaction: discord.Interaction):
        return await self.agent_manager.get_agent_for_user(str(interaction.user.id))

    async def _rate_limited_execution(self, interaction: discord.Interaction) -> None:
        await self.rate_limiter.acquire(f"user:{interaction.user.id}")

    @app_commands.command(name="ask", description="Ask OVT-Sentinel anything about AD pentesting")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        await self._rate_limited_execution(interaction)
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        await safe_call(interaction, lambda: self.memory.get_or_create_session(session_id), "get session")
        response = await safe_call(interaction,
            lambda: self.llm.chat(session_id, str(interaction.user.id), question), "AI response")
        if response is None:
            return
        await send_paginated(interaction, "OVT-Sentinel", response, THEME["ai"])

    @app_commands.command(name="analyze", description="Analyze OVT command output with AI")
    @app_commands.describe(command="The OVT command you ran", output="Paste the command output here")
    async def analyze(self, interaction: discord.Interaction, command: str, output: str) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        analysis = await safe_call(interaction,
            lambda: self.llm.analyze_output(session_id, command, output), "AI analysis")
        if analysis is None:
            return
        await send_paginated(interaction, f"Analysis: `{command[:60]}`", analysis, THEME["ai"])

    @app_commands.command(name="path", description="Find attack path in the current graph")
    @app_commands.describe(source="Source user/computer", target="Target (e.g. 'Domain Admins')")
    async def path(self, interaction: discord.Interaction, source: str, target: str) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        command = f"ovt graph path -i ./graphs/attack_graph.json --from '{source}' --to '{target}'"
        output_lines = []
        agent = await self._get_agent(interaction)
        async for msg in agent.run_command(command):
            if msg.type == "command_output":
                output_lines.append(msg.payload.get("data", ""))
            elif msg.type == "command_complete":
                break
        path_output = "\n".join(output_lines)

        analysis_prompt = f"""I ran: `ovt graph path` from {source} to {target}
Output:
```
{path_output[:2000]}
```
Explain this attack path step by step. What does each hop mean? What OVT commands would execute each step?"""
        explanation = await safe_call(interaction,
            lambda: self.llm.chat(session_id, str(interaction.user.id), analysis_prompt), "path AI analysis")
        if explanation is None:
            return

        embed = styled_embed(
            f"Attack Path: {source} \u2192 {target}",
            color=THEME["danger"],
            fields=[
                ("Raw Path", f"```\n{path_output[:900]}\n```", False),
                ("AI Explanation", explanation[:1000], False),
            ],
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="suggest", description="Get AI suggestion for the next best attack step")
    async def suggest(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        prompt = """Based on everything I've done this session and what we've found, 
what is the single best next attack step I should take right now? 
Give me the exact OVT command with all flags filled in and explain why this is the optimal move."""
        suggestion = await safe_call(interaction,
            lambda: self.llm.chat(session_id, str(interaction.user.id), prompt), "AI suggestion")
        if suggestion is None:
            return
        await send_paginated(interaction, "Next Best Move", suggestion, THEME["warning"])

    @app_commands.command(name="mistakes", description="Review what you did wrong this session")
    async def mistakes(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)
        prompt = """Review all the OVT commands I ran this session. 
For each one that was wrong, suboptimal, or done in the wrong order, explain:
1. What I did
2. Why it was wrong or suboptimal
3. What I should have done instead
Be direct and specific. If something was correct, say so briefly."""
        review = await safe_call(interaction,
            lambda: self.llm.chat(session_id, str(interaction.user.id), prompt), "AI review")
        if review is None:
            return
        await send_paginated(interaction, "Session Review", review, THEME["danger"])

    @app_commands.command(name="bloodhound", description="Analyze a BloodHound JSON file from loot with AI")
    @app_commands.describe(filename="BloodHound JSON filename in the loot directory")
    async def bloodhound(self, interaction: discord.Interaction, filename: str) -> None:
        await interaction.response.defer()
        session_id = str(interaction.user.id)

        agent = await self._get_agent(interaction)
        loot_msg = await safe_call(interaction, lambda: agent.get_loot(), "get loot listing")
        if loot_msg is None or loot_msg.type == "error":
            return

        files = loot_msg.payload.get("files", [])
        target = None
        for f in files:
            if f.get("name") == filename or f.get("name", "").endswith(filename):
                target = f
                break

        if not target:
            await interaction.followup.send(f"File '{filename}' not found in loot directory. Use /loot to see available files.")
            return

        content_msg = await safe_call(interaction,
            lambda: agent.read_loot_file(target["path"]), "read loot file")
        if content_msg is None or content_msg.type == "error":
            return

        raw_content = content_msg.payload.get("content", "")

        local_analysis = None
        try:
            local_analysis = analyze_bloodhound_json(raw_content)
            stats_lines = [
                f"Nodes: {local_analysis['total_nodes']}, Edges: {local_analysis['total_edges']}",
                f"Users: {len(local_analysis['users'])}, Computers: {len(local_analysis['computers'])}",
            ]
            if local_analysis["kerberoastable"]:
                stats_lines.append(f"Kerberoastable: {len(local_analysis['kerberoastable'])}")
            if local_analysis["asrep_roastable"]:
                stats_lines.append(f"AS-REP Roastable: {len(local_analysis['asrep_roastable'])}")
            if local_analysis["high_value_groups"]:
                names = ", ".join(g["name"] for g in local_analysis["high_value_groups"][:5])
                stats_lines.append(f"High-value groups: {names}")
            if local_analysis["sessions"]:
                stats_lines.append(f"Active sessions: {len(local_analysis['sessions'])}")
            if local_analysis["interesting_acls"]:
                acls = ", ".join(f"{a['type']}: {a['grantee']}\u2192{a['target']}" for a in local_analysis["interesting_acls"][:3])
                stats_lines.append(f"Interesting ACLs: {acls}")
            edge_types = ", ".join(f"{k}={v}" for k, v in local_analysis["edges_by_type"].items())
            if edge_types:
                stats_lines.append(f"Edge types: {edge_types}")
            stats = "\n".join(stats_lines)
        except Exception as e:
            stats = f"Could not parse JSON locally: {e}"

        analysis = await safe_call(interaction,
            lambda: self.llm.chat(session_id, str(interaction.user.id),
                f"Analyze this BloodHound JSON data. File: {filename}\n"
                f"Size: {target.get('size_bytes', 0)} bytes\n"
                f"Local stats: {stats}\n\n"
                f"First 4000 chars of data:\n```json\n{raw_content[:4000]}\n```\n\n"
                "Identify: key findings, privilege escalation paths, "
                "interesting ACEs/ACLs, kerberoastable users, AS-REP roastable users, "
                "delegation targets, and the shortest path to Domain Admins."
            ), "BloodHound AI analysis")
        if analysis is None:
            return

        await send_paginated(interaction, f"BloodHound Analysis: {filename}", f"**Stats:** {stats}\n\n{analysis}", THEME["ai"])

        if local_analysis and local_analysis.get("interesting_acls"):
            for acl in local_analysis["interesting_acls"][:5]:
                await safe_call(interaction, lambda: self.memory.log_finding(
                    session_id, "acl_abuse",
                    f"{acl['type']}: {acl['grantee']} \u2192 {acl['target']}",
                    acl, severity="high",
                ), "log finding")
        if local_analysis and local_analysis.get("kerberoastable"):
            await safe_call(interaction, lambda: self.memory.log_finding(
                session_id, "kerberoastable",
                f"Kerberoastable users: {len(local_analysis['kerberoastable'])}",
                {"users": [u["name"] for u in local_analysis["kerberoastable"]]},
                severity="high",
            ), "log finding")
        if local_analysis and local_analysis.get("asrep_roastable"):
            await safe_call(interaction, lambda: self.memory.log_finding(
                session_id, "asrep_roastable",
                f"AS-REP roastable users: {len(local_analysis['asrep_roastable'])}",
                {"users": [u["name"] for u in local_analysis["asrep_roastable"]]},
                severity="high",
            ), "log finding")

    @app_commands.command(name="search", description="Search the web for vulnerabilities, exploits, or techniques")
    @app_commands.describe(query="Search query")
    async def search(self, interaction: discord.Interaction, query: str) -> None:
        await interaction.response.defer()
        results = await web_search(query)
        lines = []
        for r in results:
            if "error" in r:
                lines.append(f"Error: {r['error']}")
            elif "info" in r:
                lines.append(r["info"])
            else:
                lines.append(f"**{r.get('title', '?')}**")
                lines.append(f"{r.get('snippet', '')[:300]}")
                lines.append(f"<{r.get('url', '')}>")
                lines.append("")
        text = "\n".join(lines[:50])
        await send_paginated(interaction, f"Search Results: {query[:80]}", text, THEME["info"])

    @app_commands.command(name="cve", description="Look up known CVEs for a Windows Server version or product")
    @app_commands.describe(product="Windows Server version (e.g. ws2019, ws2022, ws2025) or product name")
    async def cve(self, interaction: discord.Interaction, product: str) -> None:
        await interaction.response.defer()
        result = await search_vulnerabilities(product)
        wrapped = f"```\n{result}\n```"
        await send_paginated(interaction, f"Vulnerabilities: {product[:60]}", wrapped, THEME["danger"])

    @app_commands.command(name="fetch", description="Fetch and read a web page")
    @app_commands.describe(url="URL to fetch")
    async def fetch(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer()
        content = await web_fetch(url)
        wrapped = f"```\n{content}\n```"
        await send_paginated(interaction, f"Fetched: {url[:80]}", wrapped, THEME["success"])
