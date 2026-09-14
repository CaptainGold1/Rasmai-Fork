from typing import Any, Dict, Optional, Tuple
import logging

import discord
from discord import app_commands

from rasmai.bot.core import bot
from rasmai.config import ADMIN_USER_ID, CONTROL_GUILD_ID, DEFAULT_NOTICE, get_public_base_url
from rasmai.security import public_reason
from rasmai.storage.db import site_notice_get, site_notice_set
from rasmai.storage.db.sources import MAX_NOTICE, TONES

logger = logging.getLogger(__name__)

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


def _tone(typed: str) -> Tuple[str, str]:
    """The tone a typed word means, and a note for the setter when it was not one of them.

    A form takes words rather than a menu, so the first letter is enough: "w" is a warning.
    Anything else goes up as the ordinary tone rather than costing the writer their words.

    :param typed: The tone as written in the form.
    :type typed: str
    :rtype: Tuple[str, str]
    """
    wanted = (typed or "").strip().lower()
    for tone in TONES:
        if wanted and tone.startswith(wanted):
            return tone, ""
    return "notice", f"`{wanted[:12]}` is not a tone, so it went up as **notice**." if wanted else ""


async def _publish(interaction: discord.Interaction, message: str, tone: str, link: str, note: str = "") -> None:
    """Put the banner up and tell the setter what went live, including anything that was dropped.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction
    :param message: What the banner should say.
    :type message: str
    :param tone: One of ``info``, ``notice`` or ``warning``.
    :type tone: str
    :param link: An https address to offer alongside the words, if any.
    :type link: str
    :param note: Anything the setter should know about how their words were read.
    :type note: str
    """
    stored = site_notice_set(message, tone, link, str(interaction.user.id))
    if not stored["text"]:
        await interaction.response.send_message(
            "That message was empty, so nothing changed. `/notice clear:True` takes the banner down.", ephemeral=True)
        return
    notes = [note] if note else []
    if link and not stored["link"]:
        notes.append("The link was dropped: a banner carries a plain https:// address or none.")
    notes.append("Anyone who dismissed an earlier banner sees this one, because the wording decides the banner.")
    await interaction.response.send_message(
        f"Up on every page of {get_public_base_url()} within a minute, as a **{stored['tone']}** banner:\n"
        f"> {stored['text']}" + (f"\n<{stored['link']}>" if stored["link"] else "")
        + "".join(f"\n-# {line}" for line in notes),
        ephemeral=True,
    )


class NoticeModal(discord.ui.Modal, title="Site banner"):
    """The banner as a form: its words, an address to point at, and how loud it looks.

    A slash option is one line and 300 characters of banner is a paragraph, so the words are
    written here instead. The form opens filled in with whatever is up, so changing a word is
    not retyping the banner."""

    def __init__(self, current: Dict[str, Any]):
        super().__init__(timeout=900)
        self.words = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            default=str(current.get("text") or "")[:MAX_NOTICE],
            placeholder="Rasmai is moving to rasmai.lol. Your scores move with it.",
            max_length=MAX_NOTICE,
            required=True,
        )
        self.link = discord.ui.TextInput(
            default=str(current.get("link") or "")[:300],
            placeholder="https://…",
            max_length=300,
            required=False,
        )
        self.tone = discord.ui.TextInput(
            default=str(current.get("tone") or "notice"),
            placeholder="notice",
            max_length=12,
            required=False,
        )
        self.add_item(discord.ui.Label(
            text="What every visitor reads",
            description=f"Up to {MAX_NOTICE} characters, across the top of every page.",
            component=self.words,
        ))
        self.add_item(discord.ui.Label(
            text="A link to offer alongside the words",
            description="An https:// address, or leave it empty for none.",
            component=self.link,
        ))
        self.add_item(discord.ui.Label(
            text="Tone",
            description="notice is pink, info cyan, warning amber. The first letter is enough.",
            component=self.tone,
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        tone, note = _tone(str(self.tone.value or ""))
        await _publish(interaction, str(self.words.value or ""), tone, str(self.link.value or "").strip(), note)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.exception("the banner form failed")
        message = f"The banner did not go up: {public_reason(error)}"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="notice", description="Set the banner every visitor sees on the website", **_SCOPE)
@app_commands.describe(
    clear="Take the banner down entirely.",
    show="Say what is up now instead of opening the form.",
)
async def notice(interaction: discord.Interaction, clear: bool = False, show: bool = False):
    # a guild command is invisible outside its server, but a user-installed bot carries it into DMs,
    # so the only thing that actually decides who may set a banner is this line
    if str(interaction.user.id) != ADMIN_USER_ID:
        await interaction.response.send_message("That command is not yours to run.", ephemeral=True)
        return

    if clear:
        site_notice_set("", by=str(interaction.user.id))
        await interaction.response.send_message("Banner taken down. The site shows none until you set one.", ephemeral=True)
        return

    current = site_notice_get()
    if show:
        await interaction.response.send_message(_describe(current), ephemeral=True)
        return

    # nothing set yet means the site is showing its built-in notice, so that is what the form edits
    await interaction.response.send_modal(NoticeModal(current if current is not None else DEFAULT_NOTICE))
