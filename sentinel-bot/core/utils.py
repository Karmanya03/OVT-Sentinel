import logging
import re
import traceback
from typing import Any, Callable, Optional

import discord

log = logging.getLogger("sentinel.utils")


def sanitize_text(text: str) -> str:
    return re.sub(r'[\ud800-\udfff\ud800-\udbff\udc00-\udfff]', '', text)


async def safe_call(interaction: discord.Interaction, coro_factory: Callable[[], Any], label: str = "operation", ephemeral: bool = False, timeout: float = 90.0) -> Optional[Any]:
    try:
        return await asyncio.wait_for(coro_factory(), timeout=timeout)
    except asyncio.TimeoutError:
        msg = f"\u274c {label} timed out after {timeout}s. Try again or use a different provider."
        log.error("%s timed out", label)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(msg, ephemeral=ephemeral)
        except Exception:
            pass
        return None
    except Exception as e:
        tb = traceback.format_exc()
        log.error("%s failed: %s\n%s", label, e, tb)
        msg = f"\u274c {label} failed: {e}"
        if len(msg) > 1900:
            msg = msg[:1900] + "..."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(msg, ephemeral=ephemeral)
        except Exception:
            pass
        return None
