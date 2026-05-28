import textwrap
from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from config import Settings
from core.agent_manager import AgentManager
from core.utils import safe_call
from core.llm_brain import LLMBrain
from core.memory import SessionMemory
from core.output_parser import parse_output
from core.rate_limiter import RateLimiter
from ..views.confirm_view import ConfirmView
from ..notifications import (
    styled_embed, cmd_embed, ai_embed, warn_embed, error_embed,
    THEME, EMOJIS,
)
from ..paginator import send_paginated

DESTRUCTIVE_KEYWORDS = [
    "forge", "skeleton-key", "dsrm", "relay", "dump", "exec",
    "golden", "silver", "diamond", "sapphire", "shadow-creds",
    "backdoor", "cleanup", "ntlm relay",
]


class RunCog(commands.Cog):
    def __init__(self, bot: commands.Bot, agent_manager: AgentManager, memory: SessionMemory, llm: LLMBrain, config: Settings, rate_limiter: RateLimiter) -> None:
        self.bot = bot
        self.agent_manager = agent_manager
        self.memory = memory
        self.llm = llm
        self.config = config
        self.rate_limiter = rate_limiter

    async def _get_agent(self, interaction: discord.Interaction):
        return await self.agent_manager.get_agent_for_user(str(interaction.user.id))

    async def _get_agent_name(self, interaction: discord.Interaction) -> str:
        return str(interaction.user.id)[:8]

    async def _rate_limited_execution(self, interaction: discord.Interaction) -> None:
        await self.rate_limiter.acquire(f"user:{interaction.user.id}")

    @app_commands.command(name="set", description="Set session targets (DC, domain, username, password) — values are ephemeral")
    @app_commands.describe(dc_host="Target DC hostname or IP", domain="Target domain", username="Auth username", password="Auth password (stored locally, never visible in chat)")
    async def session_set(self, interaction: discord.Interaction,
                          dc_host: str = "", domain: str = "",
                          username: str = "", password: str = "") -> None:
        await interaction.response.defer(ephemeral=True)
        session_id = str(interaction.user.id)
        await self.memory.get_or_create_session(session_id)
        updates = {}
        if dc_host:
            updates["dc_host"] = dc_host
        if domain:
            updates["domain"] = domain
        if username:
            updates["username"] = username
        if password:
            updates["password"] = password
        if updates:
            await self.memory.update_session(session_id, **updates)
        fields = []
        for k, v in [("DC", dc_host), ("Domain", domain), ("Username", username), ("Password", "****" if password else "")]:
            if v:
                fields.append(f"**{k}:** {v}")
        msg = "\n".join(fields) if fields else "No values provided."
        embed = styled_embed("Session Updated", msg, THEME["success"], footer=f"{interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="run", description="Run an OVT command on the agent VM")
    async def run(self, interaction: discord.Interaction, command: str) -> None:
        await self._rate_limited_execution(interaction)
        needs_confirm = False
        if self.config.require_confirm_destructive:
            if any(kw in command.lower() for kw in DESTRUCTIVE_KEYWORDS):
                needs_confirm = True

        if needs_confirm:
            view = ConfirmView("Destructive Operation", f"```\n{command}\n```")
            await view.send(interaction, f"```\n{command}\n```")
            await view.wait()
            if not view.confirmed:
                return
        else:
            await interaction.response.defer(ephemeral=False)

        output_lines: List[str] = []
        request_id = None
        agent = await self._get_agent(interaction)
        async for msg in agent.run_command(command):
            if msg.type == "command_output":
                request_id = msg.payload.get("request_id", request_id)
                line = msg.payload.get("data", "")
                output_lines.append(line)
                await self.memory.log_output(request_id or "unknown", msg.payload.get("stream", ""), line)
            elif msg.type == "command_complete":
                request_id = msg.payload.get("request_id", request_id)
                break
            elif msg.type == "error":
                await interaction.followup.send(f"Agent error: {msg.payload.get('message')}")
                return

        if request_id:
            await self.memory.log_command(
                session_id=str(interaction.user.id),
                user_id=str(interaction.user.id),
                command=command,
                exit_code=0,
                output_summary="\n".join(output_lines[-5:]),
                agent_name=await self._get_agent_name(interaction),
            )

        content = "\n".join(output_lines[-50:])
        if not content:
            content = "(no output)"
        content = textwrap.shorten(content, width=1800, placeholder="\n...[truncated]")
        embed = cmd_embed("Command Output", f"```\n{content}\n```")
        await interaction.followup.send(embed=embed)

        if len(output_lines) > 10 and self.llm:
            session_id = str(interaction.user.id)
            full_output = "\n".join(output_lines)
            analysis = await safe_call(interaction,
                lambda: self.llm.analyze_output(session_id, command, full_output),
                "AI analysis")
            if analysis:
                await send_paginated(interaction, "OVT-Sentinel Analysis", analysis, THEME["ai"])

            parsed = parse_output(full_output)
            if parsed["kerb_hashes"]:
                await safe_call(interaction, lambda: self.memory.log_finding(
                    session_id, "kerberos_hash",
                    f"Kerberos hashes extracted ({len(parsed['kerb_hashes'])} found)",
                    parsed["kerb_hashes"][:5], severity="high"), "logging finding")
            if parsed["ntlm_hashes"]:
                await safe_call(interaction, lambda: self.memory.log_finding(
                    session_id, "ntlm_hash",
                    f"NTLM hashes extracted ({len(parsed['ntlm_hashes'])} found)",
                    parsed["ntlm_hashes"][:5], severity="high"), "logging finding")
            if parsed["adcs_findings"]:
                await safe_call(interaction, lambda: self.memory.log_finding(
                    session_id, "adcs_vulnerability",
                    "ADCS vulnerabilities detected",
                    {"findings": parsed["adcs_findings"][:10]}, severity="critical"),
                    "logging finding")
            if parsed["delegation_types"]:
                await safe_call(interaction, lambda: self.memory.log_finding(
                    session_id, "delegation",
                    "Delegation types detected",
                    {"types": parsed["delegation_types"]}, severity="high"),
                    "logging finding")

    @app_commands.command(name="stream", description="Run an OVT command with live line-by-line streaming")
    async def stream(self, interaction: discord.Interaction, command: str) -> None:
        await interaction.response.send_message(f"\u25b6 Starting: `{command}`")
        line_count = 0
        agent = await self._get_agent(interaction)
        async for msg in agent.run_command(command):
            if msg.type == "command_output":
                line = msg.payload.get("data", "")
                if line.strip():
                    line_count += 1
                    if line_count % 5 == 0:
                        await interaction.channel.send(f"```\n{line}\n```")
            elif msg.type == "command_complete":
                await interaction.channel.send("\u2705 Command complete.")
                break

    @app_commands.command(name="doctor", description="Run ovt doctor health check on the VM")
    async def doctor(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        output_lines = []
        agent = await self._get_agent(interaction)
        async for msg in agent.run_command("ovt doctor"):
            if msg.type == "command_output":
                output_lines.append(msg.payload.get("data", ""))
            elif msg.type == "command_complete":
                break
        output = "\n".join(output_lines)
        wrapped = f"```\n{output}\n```"
        await send_paginated(interaction, "Doctor Report", wrapped, THEME["info"])

    async def _run_and_send(self, interaction: discord.Interaction, command: str, title: str) -> list[str]:
        await interaction.response.defer()
        output_lines = []
        agent = await self._get_agent(interaction)
        async for msg in agent.run_command(command):
            if msg.type == "command_output":
                line = msg.payload.get("data", "")
                output_lines.append(line)
            elif msg.type == "command_complete":
                break
        output = "\n".join(output_lines)
        wrapped = f"```\n{output}\n```"
        await send_paginated(interaction, title, wrapped, THEME["success"])
        return output_lines

    def _get_session_target(self, interaction: discord.Interaction) -> dict:
        return {}  # replaced by per-command session lookup

    async def _session_target(self, interaction: discord.Interaction) -> dict:
        session_id = str(interaction.user.id)
        await self.memory.get_or_create_session(session_id)
        ctx = await self.memory.get_session_context(session_id)
        s = ctx.get("session") or {}
        return {
            "dc": s.get("dc_host", ""),
            "domain": s.get("domain", ""),
            "username": s.get("username", ""),
            "password": s.get("password", ""),
        }

    def _build_cmd(self, base: str, target: dict,
                   dc: str = "", domain: str = "", username: str = "",
                   extra: list[str] = None) -> str:
        parts = [base]
        h = dc or target.get("dc", "")
        d = domain or target.get("domain", "")
        u = username or target.get("username", "")
        p = target.get("password", "")
        if h: parts.extend(["-H", h])
        if d: parts.extend(["-d", d])
        if u: parts.extend(["-u", u])
        if p: parts.extend(["-p", p])
        if extra: parts.extend(extra)
        return " ".join(parts)

    @app_commands.command(name="enum-all", description="Run full AD enumeration with session targets")
    async def enum_all(self, interaction: discord.Interaction,
                       dc_host: str = "", domain: str = "", username: str = "") -> None:
        target = await self._session_target(interaction)
        command = self._build_cmd("ovt enum all", target, dc_host, domain, username)
        await self._run_and_send(interaction, command, "Full AD Enumeration")

    @app_commands.command(name="kerberoast", description="Run Kerberoasting against the target domain")
    async def kerberoast(self, interaction: discord.Interaction,
                         dc_host: str = "", domain: str = "", username: str = "") -> None:
        target = await self._session_target(interaction)
        command = self._build_cmd("ovt kerberos roast", target, dc_host, domain, username)
        await self._run_and_send(interaction, command, "Kerberoast Results")

    @app_commands.command(name="spray", description="Password spray with lockout safety check")
    async def spray(self, interaction: discord.Interaction,
                    password: str, dc_host: str = "", domain: str = "",
                    userlist: str = "users.txt") -> None:
        target = await self._session_target(interaction)
        dc = dc_host or target["dc"]
        dom = domain or target["domain"]

        policy_parts = ["ovt enum policy"]
        if dc:
            policy_parts.append(f"-H {dc}")
        if dom:
            policy_parts.append(f"-d {dom}")
        policy_cmd = " ".join(policy_parts)

        await interaction.response.defer()
        policy_lines = []
        agent = await self._get_agent(interaction)
        async for msg in agent.run_command(policy_cmd):
            if msg.type == "command_output":
                policy_lines.append(msg.payload.get("data", ""))
            elif msg.type == "command_complete":
                break
        policy_output = "\n".join(policy_lines)

        if self.llm and policy_output:
            safety_check = await self.llm.chat(
                str(interaction.user.id), str(interaction.user.id),
                f"Review this lockout policy output. Is it safe to run a password spray with password '{password}' against the userlist '{userlist}'? Only respond with SAFE or NOT SAFE followed by a one-line reason.\n\n{policy_output[:2000]}"
            )
            if "not safe" in safety_check.lower():
                await interaction.followup.send(f"\u26a0\ufe0f Spray may not be safe:\n{safety_check[:500]}")
                return
            await interaction.followup.send(f"\u2705 {safety_check[:200]}")

        spray_parts = ["ovt spray"]
        if dc:
            spray_parts.append(f"-H {dc}")
        if dom:
            spray_parts.append(f"-d {dom}")
        spray_parts.append(f"--userlist {userlist}")
        spray_parts.append(f"--password \"{password}\"")
        spray_cmd = " ".join(spray_parts)

        spray_lines = []
        async for msg in agent.run_command(spray_cmd):
            if msg.type == "command_output":
                spray_lines.append(msg.payload.get("data", ""))
            elif msg.type == "command_complete":
                break
        spray_output = "\n".join(spray_lines)
        wrapped = f"```\n{spray_output}\n```"
        await send_paginated(interaction, "Password Spray Results", wrapped, THEME["warning"])

    @app_commands.command(name="adcs-scan", description="Run ADCS vulnerability scan")
    async def adcs_scan(self, interaction: discord.Interaction,
                        dc_host: str = "", domain: str = "", username: str = "") -> None:
        target = await self._session_target(interaction)
        command = self._build_cmd("ovt adcs enum", target, dc_host, domain, username)
        await self._run_and_send(interaction, command, "ADCS Vulnerability Scan")

    @app_commands.command(name="crack", description="Crack hashes from the loot directory")
    async def crack(self, interaction: discord.Interaction,
                    hash_file: str = "hashes.txt",
                    wordlist: str = "/usr/share/wordlists/rockyou.txt") -> None:
        command = f"ovt crack --hashes {hash_file} --wordlist {wordlist}"
        await self._run_and_send(interaction, command, "Hash Cracking Results")

    @app_commands.command(name="kill", description="Kill a running command by request ID")
    async def kill(self, interaction: discord.Interaction, request_id: str) -> None:
        agent = await self._get_agent(interaction)
        result = await safe_call(interaction,
            lambda: agent.kill_command(request_id), "kill command")
        if result is not None:
            await interaction.response.send_message(f"Kill signal sent for {request_id}")

    @app_commands.command(name="dump", description="DCSync — extract domain credentials via DRSUAPI")
    @app_commands.describe(dc_host="Target DC hostname or IP")
    async def dump(self, interaction: discord.Interaction, dc_host: str = "") -> None:
        target = await self._session_target(interaction)
        command = self._build_cmd("ovt dump", target, dc_host)
        await self._run_and_send(interaction, command, "DCSync Dump Results")

    @app_commands.command(name="graph", description="Generate an attack path graph from BloodHound data")
    @app_commands.describe(query="Custom Cypher query (optional)", depth="Path depth (default: 5)")
    async def graph(self, interaction: discord.Interaction, query: str = "", depth: int = 5) -> None:
        parts = ["ovt graph"]
        if query:
            parts.append(f"--query \"{query}\"")
        parts.append(f"--depth {depth}")
        command = " ".join(parts)
        await self._run_and_send(interaction, command, "Attack Path Graph")

    @app_commands.command(name="session-reset", description="Reset your session context (DC, domain, username, password)")
    async def session_reset(self, interaction: discord.Interaction) -> None:
        session_id = str(interaction.user.id)
        await safe_call(interaction,
            lambda: self.memory.update_session(session_id, dc_host="", domain="", username="", password=""),
            "session reset")
        await interaction.response.send_message("\u2705 Session context cleared.", ephemeral=True)
