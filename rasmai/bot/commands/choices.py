from typing import List, Optional
import re

import discord
from discord import app_commands

from rasmai.bot.builders.charts import LEVEL_PATTERN, LEVEL_SORTS
from rasmai.engine.analysis import constant_span
from rasmai.bot.state.prefs import get_prefs
from rasmai.bot.builders.results import OUTPUT_LABELS


OUTPUT_CHOICES = [
    app_commands.Choice(name="Image + text", value="both"),
    app_commands.Choice(name="Image only", value="image"),
    app_commands.Choice(name="Text only", value="embed"),
]


DIFFICULTY_CHOICES = [
    app_commands.Choice(name="Master", value="master"),
    app_commands.Choice(name="Re:Master", value="remaster"),
    app_commands.Choice(name="Expert", value="expert"),
    app_commands.Choice(name="Advanced", value="advanced"),
    app_commands.Choice(name="Basic", value="basic"),
    app_commands.Choice(name="Any (Expert and up)", value="any"),
]


SORT_CHOICES = [app_commands.Choice(name=label.capitalize(), value=value) for value, label in LEVEL_SORTS.items()]


OUTPUT_HELP = "What to send: the image and the text, or just one of them (default: your /settings layout)"


CHALLENGE_HELP = "How ambitious the targets are (default: your /settings choice)"


CHALLENGE_CHOICES = [
    app_commands.Choice(name="Easier - targets you land about half the time", value="easy"),
    app_commands.Choice(name="Balanced - one time in four", value="balanced"),
    app_commands.Choice(name="Challenging - a stretch, about one in six", value="hard"),
    app_commands.Choice(name="Long shots - the biggest gain on the board, about one in ten", value="extreme"),
]


def _output_value(choice: Optional[app_commands.Choice[str]], user_id: int) -> str:
    if choice and choice.value in OUTPUT_LABELS:
        return choice.value
    return get_prefs(str(user_id))["layout"]


def _challenge_value(choice: Optional[app_commands.Choice[str]], user_id: int) -> str:
    if choice and choice.value in {c.value for c in CHALLENGE_CHOICES}:
        return choice.value
    return get_prefs(str(user_id))["challenge"]


async def constant_autocomplete(_interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Levels, and the ten constants inside a level once a digit or a dot is typed: `13` offers 13, 13+ and 13.0 to 13.9."""
    needle = (current or "").strip()
    out: List[tuple] = []
    if not needle:
        out = [(lv, f"level {lv}") for lv in LEVEL_PATTERN[-8:]]
    else:
        out = [(lv, f"level {lv}") for lv in LEVEL_PATTERN if lv.startswith(needle)]
        match = re.fullmatch(r"(\d{1,2})(?:\.\d?)?", needle)
        if match:
            out += [(f"{match.group(1)}.{d}", f"constant {match.group(1)}.{d}") for d in range(10) if f"{match.group(1)}.{d}".startswith(needle)]
        if "-" in needle and constant_span(needle):
            out.insert(0, (needle, f"constants {needle}"))
    return [app_commands.Choice(name=name, value=value) for value, name in out[:25]]


async def level_autocomplete(_interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    needle = (current or "").strip()
    if re.fullmatch(r"\d{1,2}\.\d", needle):
        return [app_commands.Choice(name=f"constant {needle}", value=needle)]
    levels = [lv for lv in LEVEL_PATTERN if lv.startswith(needle)] if needle else list(LEVEL_PATTERN[-10:])
    return [app_commands.Choice(name=lv, value=lv) for lv in levels[:25]]


FOCUS_CHOICES = [
    app_commands.Choice(name="Where you lose points - traits you score below your curve on", value="weak"),
    app_commands.Choice(name="Where you shine - traits you score above your curve on", value="strong"),
]


LAYOUT_CHOICES = OUTPUT_CHOICES


EXPORT_CHOICES = [app_commands.Choice(name="JSON", value="json"), app_commands.Choice(name="CSV", value="csv")]


REGION_CHOICES = [
    app_commands.Choice(name="International", value="intl"),
    app_commands.Choice(name="Japan", value="jp"),
    app_commands.Choice(name="China", value="cn"),
]
