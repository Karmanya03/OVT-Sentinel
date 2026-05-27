import discord
from discord import app_commands
from discord.ext import commands

from ..notifications import styled_embed, THEME, EMOJIS

HELP_DATA = {
    "session": {
        "emoji": EMOJIS["session"],
        "color": THEME["neutral"],
        "desc": "Session & thread management",
        "commands": {
            "session-start": "Create a new session in a dedicated thread. All chat and output will appear there.",
            "session-end": "End the current session and archive the thread.",
            "resume": "Resume an existing session. Use this inside the session thread.",
            "chat": "Send a message to the AI. Response goes to your session thread if active.",
            "set": "Configure session targets (DC, domain, username, password). Values are ephemeral.",
            "session-reset": "Clear all session target values.",
            "session": "Show a summary of the current session (commands run, findings).",
        },
    },
    "ai": {
        "emoji": EMOJIS["ai"],
        "color": THEME["ai"],
        "desc": "AI-powered analysis & intelligence",
        "commands": {
            "ask": "Ask OVT-Sentinel anything about AD pentesting techniques or concepts.",
            "analyze": "Paste OVT command output for AI-driven analysis.",
            "suggest": "Get an AI suggestion for the single best next attack step.",
            "mistakes": "Review what you did wrong this session with AI critique.",
            "path": "Analyze an attack path from source to target using BloodHound data.",
            "bloodhound": "Upload & analyze a BloodHound JSON file with AI + local parsing.",
        },
    },
    "attack": {
        "emoji": "\ud83d\udfe1",
        "color": THEME["ad"],
        "desc": "AD attack commands (via OVT agent)",
        "commands": {
            "run": "Execute any OVT command on the agent VM. Destructive commands require confirmation.",
            "stream": "Run a command with live line-by-line streaming output.",
            "enum-all": "Full AD enumeration using session targets.",
            "kerberoast": "Run Kerberoasting against the target domain.",
            "spray": "Password spray attack with lockout policy safety check.",
            "adcs-scan": "Scan for ADCS (Active Directory Certificate Services) vulnerabilities.",
            "dump": "DCSync attack \u2014 extract domain credentials via DRSUAPI.",
            "crack": "Crack password hashes from the loot directory.",
            "kill": "Kill a running command by request ID.",
            "graph": "Generate an attack path graph from BloodHound data.",
            "doctor": "Run `ovt doctor` health check on the agent VM.",
        },
    },
    "monitor": {
        "emoji": EMOJIS["status"],
        "color": THEME["info"],
        "desc": "VM monitoring & loot management",
        "commands": {
            "status": "Show agent VM status (CPU, RAM, disk, OVT version, running processes).",
            "loot": "List loot files collected on the agent VM with interactive pagination.",
            "readloot": "Read the contents of a specific loot file.",
            "screenshot": "Take a VM screenshot (optionally analyze with AI).",
            "browse": "Open a URL in the VM browser and return a screenshot.",
        },
    },
    "utilities": {
        "emoji": "\ud83d\udd27",
        "color": THEME["primary"],
        "desc": "Web tools & history",
        "commands": {
            "search": "Search the web for vulnerabilities, exploits, or techniques.",
            "cve": "Look up known CVEs for a Windows Server version or product.",
            "fetch": "Fetch and read the content of a web page.",
            "log": "Show recent Sentinel events.",
            "history": "Show the command history for this session.",
            "help": "Show this help message.",
        },
    },
}


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="Show detailed help for all commands")
    @app_commands.describe(category="Optional: filter by category (session, ai, attack, monitor, utilities)")
    async def help(self, interaction: discord.Interaction, category: str = "") -> None:
        await interaction.response.defer(ephemeral=True)

        if category:
            cat = category.lower().strip()
            if cat not in HELP_DATA:
                await interaction.followup.send(
                    f"Unknown category `{cat}`. Available: {', '.join(HELP_DATA.keys())}",
                    ephemeral=True,
                )
                return
            groups = {cat: HELP_DATA[cat]}
        else:
            groups = HELP_DATA

        embed = discord.Embed(
            title=f"{EMOJIS['shield']} OVT-Sentinel Command Reference",
            description="Select a category below or use `/help <category>` for details.",
            color=THEME["primary"],
        )
        from datetime import datetime, timezone
        embed.timestamp = datetime.now(timezone.utc)

        for key, group in groups.items():
            cmd_list = "\n".join(
                f"`/{cmd}` \u2014 {desc}"
                for cmd, desc in group["commands"].items()
            )
            embed.add_field(
                name=f"{group['emoji']} {key.title()} \u2014 {group['desc']}",
                value=cmd_list,
                inline=False,
            )

        embed.set_footer(text=f"Total: {sum(len(g['commands']) for g in HELP_DATA.values())} commands")

        view = HelpCategoryView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class HelpCategoryView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @discord.ui.button(label="Session", style=discord.ButtonStyle.secondary, emoji="\ud83d\udd17")
    async def btn_session(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show_category(interaction, "session")

    @discord.ui.button(label="AI", style=discord.ButtonStyle.secondary, emoji="\ud83e\udde0")
    async def btn_ai(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show_category(interaction, "ai")

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger, emoji="\ud83d\udfe1")
    async def btn_attack(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show_category(interaction, "attack")

    @discord.ui.button(label="Monitor", style=discord.ButtonStyle.primary, emoji="\ud83d\udcca")
    async def btn_monitor(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show_category(interaction, "monitor")

    @discord.ui.button(label="Utilities", style=discord.ButtonStyle.secondary, emoji="\ud83d\udd27")
    async def btn_utils(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._show_category(interaction, "utilities")

    async def _show_category(self, interaction: discord.Interaction, key: str) -> None:
        group = HELP_DATA[key]
        cmd_list = "\n".join(
            f"`/{cmd}` \u2014 {desc}"
            for cmd, desc in group["commands"].items()
        )
        embed = styled_embed(
            f"{group['emoji']} {key.title()} \u2014 {group['desc']}",
            cmd_list,
            group["color"],
            footer=f"OVT-Sentinel \u2022 use `/help all` for all commands",
        )
        await interaction.response.edit_message(embed=embed, view=self)
