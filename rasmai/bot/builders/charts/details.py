from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import discord

from rasmai.engine.analysis import ChartRef
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.ui.formatting import TIER_NAMES, _fit
from rasmai.web.links import area_url, chart_url
from rasmai.bot.ui import emoji
from rasmai.scraping import wiki


def unlock_field(embed: discord.Embed, page: Dict[str, Any], cached: Optional[CachedAnalysis] = None) -> None:
    """The wiki's unlock notes as one field, when it has any.

    A note that names one of the player's own areas gets their distance there under it, so
    "reach 5,000 km in X" comes with how far along X they are.

    :param embed: The embed being built.
    :type embed: discord.Embed
    :param page: Which page to show, counting from zero.
    :type page: Dict[str, Any]
    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    """
    lines = [str(line) for line in page.get("unlock") or []]
    if not lines:
        return
    summary = None
    if cached is not None and getattr(cached.analyzer, "events_data", None):
        from rasmai.bot.builders.areas import area_summary
        from rasmai.engine.areas import area_mentions
        summary = area_summary(cached)
    out: List[str] = []
    for line in lines:
        out.append(f"-# {line}")
        for area in (area_mentions(line, summary) if summary else [])[:2]:
            standing = f"{int(area['distance']):,} km"
            if area["state"] == "completed":
                standing += ", completed"
            elif area["state"] == "not_started":
                standing = "not started"
            elif area.get("milestone"):
                standing += f", next reward at {int(area['milestone']):,} km"
            from rasmai.bot.builders.areas import area_title
            out.append(f"-# ↳ [you in {area_title(area)}: {standing}]({area_url(area['name'])})")
    embed.add_field(name="How to unlock", value=_fit(out), inline=False)


def video_button(ref: ChartRef, videos: Dict[Tuple[str, str], str], both_types: bool, row: int = 4) -> discord.ui.Button:
    """The exact chart video when the wiki has one, else a YouTube search for it.

    :param ref: The chart being shown.
    :type ref: ChartRef
    :param videos: A video per chart, keyed by type and difficulty.
    :type videos: Dict[Tuple[str, str], str]
    :param row: One row of the table.
    :type row: int
    :param both_types: Whether the song has a standard and a DX chart.
    :type both_types: bool
    :rtype: discord.ui.Button
    """
    video = videos.get((ref.chart_type, ref.difficulty))
    if video:
        return discord.ui.Button(label="Watch on YouTube", style=discord.ButtonStyle.link, row=row, url=wiki.video_url(video))
    return discord.ui.Button(label="Search YouTube", style=discord.ButtonStyle.link, row=row, url=youtube_search_url(ref, both_types))


def youtube_search_url(ref: ChartRef, both_types: bool = False) -> str:
    """A YouTube search for a play of this chart; uploads title them with the song and tier.

    :param ref: The chart being shown.
    :type ref: ChartRef
    :param both_types: Whether the song has a standard and a DX chart.
    :type both_types: bool
    :rtype: str
    """
    terms = ["maimai", ref.title, TIER_NAMES.get(ref.difficulty, ref.difficulty.upper())]
    if both_types:
        terms.append("DX" if ref.chart_type == "dx" else "スタンダード")
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(" ".join(terms))


def chart_notes(ref: ChartRef) -> Optional[Dict[str, Any]]:
    """What mai-notes holds for a chart: the note split and its pattern tags, or None.

    :param ref: The chart being shown.
    :type ref: ChartRef
    :rtype: Optional[Dict[str, Any]]
    """
    try:
        from rasmai.scraping import mai_notes
        return mai_notes.cached_facts().get(ref.key)
    except Exception:
        return None


def _note_split(ref: ChartRef) -> str:
    """The note count broken down by type, which the chart database does not carry.

    :param ref: The chart being shown.
    :type ref: ChartRef
    :rtype: str
    """
    row = chart_notes(ref)
    if not row:
        return ""
    parts = [f"{row.get(field, 0):,} {name}" for field, name in
             (("t", "tap"), ("h", "hold"), ("s", "slide"), ("u", "touch"), ("b", "break")) if row.get(field)]
    return "\n-# " + " · ".join(parts) if parts else ""


def _chart_credit(ref: ChartRef) -> str:
    """Who wrote the chart and the day it arrived, as a small line under the note split.

    :param ref: The chart being shown.
    :type ref: ChartRef
    :rtype: str
    """
    parts = []
    if ref.designer:
        parts.append(f"charted by {ref.designer}")
    if ref.released:
        try:
            day = datetime.fromisoformat(ref.released)
            parts.append(f"added {day.day} {day.strftime('%b %Y')}")
        except ValueError:
            pass
    return "\n-# " + " · ".join(parts) if parts else ""


def _pattern_field(embed: discord.Embed, cached: Optional[CachedAnalysis], ref: ChartRef) -> None:
    """The patterns mai-notes' editors put on this chart, marked where the player scores below their own curve on them.

    :param embed: The embed being built.
    :type embed: discord.Embed
    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param ref: The chart being shown.
    :type ref: ChartRef
    """
    from rasmai.engine import insights
    tags = insights.chart_tags(ref)
    if not tags:
        return
    offsets = {}
    if cached is not None and getattr(cached.analyzer, "play_profile", None):
        offsets = {t["label"]: float(t["offset"]) for t in (cached.analyzer.play_profile.traits or [])}
    lines = []
    for tag in [t for t in tags if t["community"]]:
        offset = offsets.get(tag["label"])
        mark = f" · your confirmed scores on this sit **{offset:+.1f}** against your curve" if offset is not None else ""
        lines.append(f"-# {tag['label']}{mark}")
    measured = [t for t in tags if not t["community"]]
    if measured:
        parts = []
        for tag in measured:
            offset = offsets.get(tag["label"])
            parts.append(f"{tag['label']}{f' **{offset:+.1f}**' if offset is not None else ''}")
        lines.append(("-# from the chart itself · " if any(t["community"] for t in tags) else "-# ") + " · ".join(parts))
    lines.append("-# know these before the run, and afterwards ask which of them cost you"
                 + (" · `/charts pattern:` lists every chart with one" if any(t["community"] for t in tags) else ""))
    embed.add_field(name="What it asks of you", value=_fit(lines), inline=False)


def _song_chart_line(ref: ChartRef, row: Dict[str, Any], designer: str) -> str:
    """One chart of the song, as a line of the /song embed.

    :param ref: The chart being shown.
    :type ref: ChartRef
    :param row: One row of the table.
    :type row: Dict[str, Any]
    :rtype: str
    """
    head = f"{emoji.difficulty(ref.difficulty)} [**{TIER_NAMES.get(ref.difficulty, ref.difficulty.upper())} {ref.level}**]({chart_url(ref.title, ref.chart_type, ref.difficulty, ref.cover)})".strip()
    facts = [f"const {ref.constant:.1f}"]
    if ref.notes:
        facts.append(f"{ref.notes:,} notes")
    if designer:
        facts.append(designer)
    line = f"{head} · {' · '.join(facts)}"
    if row.get("played"):
        line += f"\n-# you: **{row['accuracy']:.4f}%** {row['rank']} · rating {row['rating']}"
        if row.get("plays"):
            line += f" · {row['plays']} play{'s' if row['plays'] != 1 else ''}"
    return line
