from typing import Optional

import discord
from discord import app_commands

from rasmai.bot.core import bot
from rasmai.config import ADMIN_USER_ID, CONTROL_GUILD_ID, DEFAULT_NOTICE, get_public_base_url
from rasmai.storage.db import site_notice_get, site_notice_set

TONE_CHOICES = [
    app_commands.Choice(name="notice - pink, the ordinary one", value="notice"),
    app_commands.Choice(name="info - cyan, quieter", value="info"),
    app_commands.Choice(name="warning - amber, something is wrong", value="warning"),
]

# a command registered against a guild exists only in that server's picker; with no guild set it
# falls back to global, which is what a fork without a control server wants
_SCOPE = {"guilds": [discord.Object(id=CONTROL_GUILD_ID)]} if CONTROL_GUILD_ID else {}


def _describe(notice: Optional[dict]) -> str:
    if notice is None:
        text = str(DEFAULT_NOTICE.get("text", ""))
        return f"Nothing has been set, so the site is showing its built-in notice:\n> {text}"
    if not notice.get("text"):
        return "The site is showing no banner."
    link = notice.get("link") or ""
    return (f"The site is showing a **{notice.get('tone', 'notice')}** banner:\n> {notice['text']}"
            + (f"\n<{link}>" if link else "")
            + f"\n-# set {notice.get('setAt', 'at some point')}")


@bot.tree.command(name="notice", description="Set the banner every visitor sees on the website", **_SCOPE)
@app_commands.describe(
    message="What the banner should say. Leave it out to see what is up now.",
    tone="How loud it looks.",
    link="An https address to offer alongside the words.",
    clear="Take the banner down entirely.",
)
@app_commands.choices(tone=TONE_CHOICES)
async def notice(interaction: discord.Interaction, message: Optional[str] = None,
                 tone: Optional[app_commands.Choice[str]] = None, link: Optional[str] = None,
                 clear: bool = False):
    # a guild command is invisible outside its server, but a user-installed bot carries it into DMs,
    # so the only thing that actually decides who may set a banner is this line
    if str(interaction.user.id) != ADMIN_USER_ID:
        await interaction.response.send_message("That command is not yours to run.", ephemeral=True)
        return

    if clear:
        site_notice_set("", by=str(interaction.user.id))
        await interaction.response.send_message("Banner taken down. The site shows none until you set one.", ephemeral=True)
        return

    if message is None:
        await interaction.response.send_message(_describe(site_notice_get()), ephemeral=True)
        return

    if link and not link.startswith("https://"):
        await interaction.response.send_message("The link has to be an https:// address, or left out.", ephemeral=True)
        return

    stored = site_notice_set(message, tone.value if tone else "notice", link or "", str(interaction.user.id))
    if not stored["text"]:
        await interaction.response.send_message("That message was empty, so nothing changed. Use `clear` to take the banner down.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"Up on every page of {get_public_base_url()} within a minute, as a **{stored['tone']}** banner:\n"
        f"> {stored['text']}" + (f"\n<{stored['link']}>" if stored["link"] else "")
        + "\n-# Anyone who dismissed an earlier banner sees this one, because the wording decides the banner.",
        ephemeral=True,
    )
