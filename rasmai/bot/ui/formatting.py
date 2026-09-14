from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
import base64
import discord
import io

from rasmai.bot.ui import emoji
from rasmai.engine import analysis
from rasmai.storage.models import PlayerInfo, Recommendation


TIMESTAMP_STYLES = ("t", "T", "d", "D", "f", "F", "R")


def stamp(moment: datetime, style: str = "f") -> str:
    """A Discord timestamp: rendered in each reader's own timezone, daylight saving included.

    Styles are Discord's: t/T time, d/D date, f/F date and time, R relative.

    :param moment: The moment to show.
    :type moment: datetime
    :param style: Which of Discord's timestamp styles to use.
    :type style: str
    :rtype: str
    """
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return f"<t:{int(moment.timestamp())}:{style}>"


def message_files(player: PlayerInfo, image: Optional[bytes], image_name: str) -> Tuple[List[discord.File], Optional[str]]:
    """Attachments for a command reply: the image plus the player's avatar.

    The official avatar URL needs the maimai session cookie, so Discord cannot
    fetch it; attaching the bytes we already downloaded is the only way the
    author icon shows up. Returns (files, avatar attachment url or None).

    :param image: The rendered image, as PNG bytes.
    :type image: Optional[bytes]
    :param image_name: The file name to attach the image under.
    :type image_name: str
    :param player: The player, as maimai DX NET describes them.
    :type player: PlayerInfo
    :rtype: Tuple[List[discord.File], Optional[str]]
    """
    files: List[discord.File] = []
    if image:
        files.append(discord.File(io.BytesIO(image), filename=image_name))
    avatar_url = None
    avatar_b64 = getattr(player, "avatar_base64", "") or ""
    if avatar_b64:
        try:
            files.append(discord.File(io.BytesIO(base64.b64decode(avatar_b64)), filename="avatar.png"))
            avatar_url = "attachment://avatar.png"
        except (ValueError, TypeError):
            pass
    return files, avatar_url


def progress_bar(done: int, needed: int, width: int = 12) -> str:
    filled = 0 if needed <= 0 else max(0, min(width, round(width * done / needed)))
    return "▰" * filled + "▱" * (width - filled)


TIER_NAMES = {"basic": "BASIC", "advanced": "ADVANCED", "expert": "EXPERT",
              "master": "MASTER", "remaster": "Re:MASTER", "utage": "UTAGE"}


def _fit(lines: List[str], limit: int = 1000) -> str:
    """Join lines, stopping before Discord's 1024-character field cap.

    :param limit: Most entries to return.
    :type limit: int
    :param lines: The lines to join.
    :type lines: List[str]
    :rtype: str
    """
    out = ""
    for line in lines:
        if len(out) + len(line) + 1 > limit:
            break
        out += line + "\n"
    return out.rstrip() or "-"


TIER_SHORT = {"basic": "BAS", "advanced": "ADV", "expert": "EXP", "master": "MAS", "remaster": "ReM", "utage": "UTG"}


def level_text(level: Any, constant: Any) -> str:
    """The level with its chart constant: `13+ · 13.8`. A 13+ can be a 13.7 or a 13.9, and the constant is what rating is made of.

    :param level: A displayed level such as ``"13"`` or ``"13+"``.
    :type level: Any
    :param constant: The chart's internal difficulty constant.
    :type constant: Any
    :rtype: str
    """
    try:
        value = float(constant or 0)
    except (TypeError, ValueError):
        value = 0.0
    return f"{level} · {value:.1f}" if value > 0 else str(level)


def _short_title(title: str, limit: int = 22) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"


def chart_link(title: str, chart_type: str = "", difficulty: str = "", cover: str = "", limit: int = 22) -> str:
    """A chart's name in bold, linked to its page on the site; brackets in the title are escaped so the link survives.

    :param title: The song title.
    :type title: str
    :param chart_type: ``"std"`` or ``"dx"``.
    :type chart_type: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: str
    :param cover: The jacket file name.
    :type cover: str
    :param limit: Most entries to return.
    :type limit: int
    :rtype: str
    """
    from rasmai.web.links import chart_url
    label = _short_title(str(title), limit).replace("[", "［").replace("]", "］")
    return f"[**{label}**]({chart_url(title, chart_type, difficulty, cover)})"


def format_picks_markdown(recommendations: List[Recommendation], limit: int = 8) -> str:
    """The 'play these now' list, one line per chart.

    :param recommendations: The charts worth playing, best first.
    :type recommendations: List[Recommendation]
    :param limit: Most entries to return.
    :type limit: int
    :rtype: str
    """
    lines: List[str] = []
    movers = [r for r in recommendations if r.category not in ("near", "try")][:limit]
    for index, rec in enumerate(movers, 1):
        tier = emoji.difficulty(rec.difficulty_type) or TIER_SHORT.get(rec.difficulty_type, rec.difficulty_type[:3].upper())
        played = "new" if rec.is_unplayed else f"{rec.current_accuracy:.2f}"
        lines.append(
            f"`{index:>2}` {chart_link(rec.song, rec.chart_type, rec.difficulty_type, rec.cover_url)} {tier} {level_text(rec.level, rec.difficulty)}\n"
            f"-# {played} → **{rec.target_accuracy:.2f}** · **+{rec.potential_gain}** · {rec.feasibility * 100:.0f}%"
            + (" · constant estimated, not in the database yet" if getattr(rec, "estimated", False) else "")
            + (" · one run, far under your usual here" if "one run" in str(rec.value_chart_reason or "") else "")
        )
    return _fit(lines)


def format_try_markdown(recommendations: List[Recommendation], limit: int = 6) -> str:
    """Charts never played that are worth a run, with why each earned its place.

    :param recommendations: The charts worth playing, best first.
    :type recommendations: List[Recommendation]
    :param limit: Most entries to return.
    :type limit: int
    :rtype: str
    """
    lines: List[str] = []
    for rec in [r for r in recommendations if r.category == "try"][:limit]:
        tier = emoji.difficulty(rec.difficulty_type) or TIER_SHORT.get(rec.difficulty_type, rec.difficulty_type[:3].upper())
        why = str(rec.value_chart_reason or "").replace("never played · ", "")
        lines.append(
            f"{chart_link(rec.song, rec.chart_type, rec.difficulty_type, rec.cover_url)} {tier} {level_text(rec.level, rec.difficulty)}\n"
            f"-# aim **{rec.target_accuracy:.2f}** · {rec.feasibility * 100:.0f}% · {why}"
        )
    return _fit(lines)


def format_plan_markdown(plan: Optional["analysis.Plan"], limit: int = 12, start: int = 1) -> str:
    """Compact route: one line per step with a running total, numbered from `start`.

    :param plan: The route to a rating target.
    :type plan: Optional['analysis.Plan']
    :param limit: Most entries to return.
    :type limit: int
    :param start: Where to start from.
    :type start: int
    :rtype: str
    """
    if not plan or not plan.steps:
        return "Nothing on the route yet - play a few more charts and try again."
    lines: List[str] = []
    for index, step in enumerate(plan.steps[start - 1:start - 1 + limit], start):
        option = step.option
        tier = TIER_SHORT.get(option.difficulty_type, option.difficulty_type[:3].upper())
        mark = emoji.emoji("new")
        flag = (f" {mark} **NEW**" if mark else " **NEW**") if option.is_unplayed else ""
        lines.append(
            f"`{index:>2}` {chart_link(option.title, option.chart_type, option.difficulty_type, option.cover)}{flag} {tier} {level_text(option.level, option.constant)}\n"
            f"-# → **{option.target_accuracy:.2f}** · +{step.gain} · {option.feasibility * 100:.0f}% · Σ **{step.cumulative}**"
        )
    return _fit(lines)


def add_profile_fields(embed: discord.Embed, summary: Dict[str, Any]) -> None:
    """How the player plays, as three side-by-side fields.

    :param embed: The embed being built.
    :type embed: discord.Embed

    :param summary: The figures the analysis produced.
    :type summary: Dict[str, Any]
    """
    profile = summary.get("profile", {})
    best50 = summary.get("best50", {})
    embed.add_field(
        name="Style",
        value=(
            f"**{str(profile.get('style', 'unknown')).title()}**\n"
            f"{profile.get('fcRate', 0) * 100:.0f}% FC · {profile.get('apRate', 0) * 100:.0f}% AP\n"
            f"{profile.get('dxScoreRate', 0) * 100:.0f}% DX score\n"
            f"leans {str(profile.get('favouriteChartType', '?')).upper()}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Levels",
        value=(
            f"comfort **{profile.get('comfortConstant', 0)}**\n"
            f"reach **{profile.get('reachConstant', 0)}** · hardest S **{profile.get('hardestS', 0)}**\n"
            f"{profile.get('expectedAt13', 0)}% on 13s\n"
            f"{profile.get('expectedAt14', 0)}% on 14s"
        ),
        inline=True,
    )
    open_slots = best50.get("newSlotsOpen", 0) + best50.get("oldSlotsOpen", 0)
    slots = f"\n**{open_slots} slots empty**" if open_slots else ""
    embed.add_field(
        name="Best-50",
        value=(
            f"**{best50.get('total', 0)}**\n"
            f"{best50.get('newTotal', 0)} new + {best50.get('oldTotal', 0)} old\n"
            f"cutoffs {best50.get('newCutoff', 0)} / {best50.get('oldCutoff', 0)}{slots}"
        ),
        inline=True,
    )


def add_row_break(embed: discord.Embed) -> None:
    embed.add_field(name="\u200b", value="\u200b", inline=False)


def format_plan_verdict(plan: Optional["analysis.Plan"]) -> str:
    if not plan:
        return ""
    if plan.reached:
        head = f"**{plan.goal_rating}** is covered: **+{plan.total}** across {len(plan.steps)} charts."
    else:
        head = (
            f"Route to **{plan.goal_rating}** covers **+{plan.total}** of the **+{plan.needed}** needed "
            f"across {len(plan.steps)} charts · **{plan.shortfall} short**."
        )
    tail = f"\n-# about **{plan.average_stretch:+.1f}%** above your usual · worth ~+{plan.expected_gain:.0f} by odds"
    fresh = plan.gap_steps
    if not fresh and not plan.reached:
        tail += ("\n-# no unplayed chart would clear your best-50 on a first pass either, "
                 "so the rest has to come from scores you already hold")
    if fresh:
        mark = emoji.emoji("new")
        tail += (f"\n-# {mark + ' ' if mark else ''}**{len(fresh)}** of these are charts you have never played, worth "
                 f"**+{plan.gap_gain}** - your played charts could not cover the rest on their own")
    return f"{head}{tail}"


REGION_LABELS = {"intl": "International", "jp": "Japan", "cn": "China"}


NOT_CONNECTED_MESSAGE = (
    "**No maimai account connected yet.**\n"
    "Run `/login` and follow the link - it takes about a minute."
)


def build_login_walkthrough_embed(region: str, login_info: Dict[str, str]) -> discord.Embed:
    expires = stamp(datetime.fromisoformat(login_info["expiresAt"]), "R")
    embed = discord.Embed(
        title="Connect your maimai account",
        description=(
            "Press the button below to open the setup page. It walks you through "
            "signing in and tells you the moment you are connected."
        ),
        color=discord.Color.from_rgb(255, 182, 46),
    )
    embed.add_field(
        name="What you'll do there",
        value=(
            "1. Save the connect button to your bookmarks\n"
            "2. Sign in at [my-aime.net](https://my-aime.net/en/) with the account you play on\n"
            "3. Open the Aime authentication from the setup page\n"
            "4. Click the bookmark - that's it"
        ),
        inline=False,
    )
    embed.add_field(name="Region", value=REGION_LABELS.get(region, region), inline=True)
    embed.add_field(name="Link expires", value=expires, inline=True)
    embed.set_footer(text="Stuck? The Show me buttons play the whole thing · this card updates itself once you are connected")
    return embed


def build_login_done_embed(name: str, region: str) -> discord.Embed:
    """What the /login message turns into once the account is linked.

    :param name: The name to look up.
    :type name: str
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: str
    :rtype: discord.Embed
    """
    embed = discord.Embed(
        title="Connected",
        description=f"Signed in as **{name or 'your maimai account'}** · {REGION_LABELS.get(region, region)}.",
        color=discord.Color.from_rgb(75, 184, 95),
    )
    embed.add_field(name="Next", value="`/analyze` for what to play, `/plan` for the route to your next thousand, `/chart` to look anything up.", inline=False)
    embed.set_footer(text="Your password never reached the bot; /logout removes the session at any time")
    return embed


def today() -> str:
    """Today's date as the images print it.

    :returns: The date, such as ``"07 September 2026"``.
    :rtype: str
    """
    return datetime.now().strftime("%d %B %Y")
