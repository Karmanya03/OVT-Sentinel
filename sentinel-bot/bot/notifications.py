import discord

THEME = {
    "primary": 0x5865F2,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "danger": 0xED4245,
    "info": 0x00B0FF,
    "neutral": 0x2B2D31,
    "ai": 0x9B59B6,
    "ad": 0xE67E22,
}

EMOJIS = {
    "cmd": "\u25b6",
    "done": "\u2705",
    "fail": "\u274c",
    "warn": "\u26a0\ufe0f",
    "info": "\u2139\ufe0f",
    "ai": "\ud83e\udde0",
    "target": "\ud83c\udfaf",
    "loot": "\ud83d\udce6",
    "browser": "\ud83c\udf10",
    "session": "\ud83d\udd17",
    "status": "\ud83d\udcca",
    "graph": "\ud83d\udd17",
    "shield": "\ud83d\udee1\ufe0f",
    "lock": "\ud83d\udd12",
    "key": "\ud83d\udd11",
}


def _footer(text: str = "OVT-Sentinel") -> dict:
    return {"text": text, "icon_url": "https://cdn.discordapp.com/emojis/1055804536481648640.png"}


def styled_embed(
    title: str,
    description: str = "",
    color: int = THEME["primary"],
    fields: list[tuple[str, str, bool]] = None,
    footer: str = None,
    timestamp: bool = True,
) -> discord.Embed:
    embed = discord.Embed(
        title=title[:256],
        description=description[:4096],
        color=color,
    )
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name[:256], value=value[:1024], inline=inline)
    if footer:
        embed.set_footer(text=footer)
    elif timestamp:
        from datetime import datetime, timezone
        embed.timestamp = datetime.now(timezone.utc)
    return embed


def cmd_embed(title: str, description: str = "", extra_fields: list = None) -> discord.Embed:
    return styled_embed(f"{EMOJIS['cmd']} {title}", description, THEME["success"], extra_fields)


def ai_embed(title: str, description: str = "", extra_fields: list = None) -> discord.Embed:
    return styled_embed(f"{EMOJIS['ai']} {title}", description, THEME["ai"], extra_fields)


def warn_embed(title: str, description: str = "") -> discord.Embed:
    return styled_embed(f"{EMOJIS['warn']} {title}", description, THEME["warning"])


def error_embed(title: str = "Error", description: str = "") -> discord.Embed:
    return styled_embed(f"{EMOJIS['fail']} {title}", description, THEME["danger"])


def session_embed(title: str, description: str = "", extra_fields: list = None) -> discord.Embed:
    return styled_embed(f"{EMOJIS['session']} {title}", description, THEME["neutral"], extra_fields)


def status_embed(title: str, description: str = "", extra_fields: list = None) -> discord.Embed:
    return styled_embed(f"{EMOJIS['status']} {title}", description, THEME["info"], extra_fields)


async def notify_new_loot(msg_data: dict) -> discord.Embed:
    path = msg_data.get("path", "unknown")
    size_bytes = msg_data.get("size_bytes", 0)
    name = path.split("/")[-1].split("\\")[-1]
    size_kb = size_bytes / 1024
    embed = styled_embed(
        f"{EMOJIS['loot']} New Loot File",
        f"**{name}** ({size_kb:.1f} KB)\nPath: `{path}`",
        THEME["success"],
        footer="Auto-detected from agent VM",
    )
    return embed


async def notify_error(message: str) -> discord.Embed:
    return error_embed(description=message)
