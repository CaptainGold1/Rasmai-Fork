from typing import Any, Dict, List, Optional, Tuple
import io
import discord
import asyncio
import logging

from rasmai.engine.analysis import ChartRef, loose_title
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.ui.formatting import TIER_NAMES, _fit
from rasmai.web.links import chart_url
from rasmai.scraping import wiki
from rasmai.config import WIKI_VIDEOS
from rasmai.bot.builders.charts.index import (
    chart_designer, charts_for, jacket_file, resolve_title, shared_index, song_record, version_name,
)
from rasmai.bot.builders.charts.ladder import _cutoffs, _version_label, chart_ladder, prediction_for
from rasmai.bot.builders.charts.details import _chart_credit, _note_split, _pattern_field, _song_chart_line, unlock_field
from rasmai.bot.builders.charts.page import DIFFICULTY_COLOUR, _default_page, _page_fields, difficulty_page, ensure_play_counts, last_play
from rasmai.bot.builders.charts.rows import _chart_rows, _song_card

logger = logging.getLogger(__name__)


def _resolve_song(cached: Optional[CachedAnalysis], query: str) -> Tuple[Optional[str], List[ChartRef], Optional[discord.Embed]]:
    """Title and charts for a query, or the embed that says why there are none.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param query: What the player typed.
    :type query: str
    :rtype: Tuple[Optional[str], List[ChartRef], Optional[discord.Embed]]
    """
    index = cached.analyzer.chart_index if cached else shared_index()
    title = resolve_title(query, index)
    if not title:
        mine = [s for s in (cached.analyzer.songs if cached else []) if str(s.name).casefold() == str(query).casefold()]
        if mine:
            scores = ", ".join(f"{str(s.difficulty_type).title()} {s.level} at {float(s.accuracy):.4f}%" for s in mine)
            embed = discord.Embed(title=f"{mine[0].name} is not in the chart database yet",
                                  description=(f"It is a new song. The database refreshes itself within a day of a read that meets it; the jacket, "
                                               f"constants and this page arrive with it. Until then your score counts with a constant taken from the "
                                               f"middle of its level.\n-# yours: {scores}"),
                                  color=discord.Color.orange())
            return None, [], embed
        embed = discord.Embed(title="No song found",
                              description=f"Nothing in the chart database matches **{query}**. Try part of the title, or its reading in romaji.",
                              color=discord.Color.orange())
        return None, [], embed
    refs = charts_for(title, index)
    if not refs:
        embed = discord.Embed(title=title, description="The database lists this title but no playable charts.", color=discord.Color.orange())
        return title, [], embed
    return title, refs, None


async def build_song(cached: Optional[CachedAnalysis], query: str, page: Optional[int] = None,
                     owner_id: Optional[int] = None, difficulty: Optional[str] = None
                     ) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    """One page per chart of the song, with buttons to move between them; the card image shows them all.

    `difficulty` opens straight at that tier; otherwise the page is the chart that matters most.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param query: What the player typed.
    :type query: str
    :param page: Which page to show, counting from zero.
    :type page: Optional[int]
    :param owner_id: The Discord user the components answer to.
    :type owner_id: Optional[int]
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: Optional[str]
    :rtype: Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]
    """
    from rasmai.bot.builders.charts.views import SongView
    title, refs, problem = _resolve_song(cached, query)
    if problem is not None:
        return problem, [], None
    await ensure_play_counts(cached, refs)
    rows = _chart_rows(cached, refs)
    if page is None and difficulty:
        page = difficulty_page(refs, rows, difficulty)
    page = _default_page(rows) if page is None else max(0, min(page, len(refs) - 1))
    ref, row = refs[page], rows[page]
    play = last_play(cached, ref) if row.get("played") else None
    detail = None
    if play and play.get("idx"):
        from rasmai.bot.builders.history import play_detail
        try:
            detail = await asyncio.to_thread(play_detail, cached, play["idx"])
        except Exception as error:      # the judgement page is a bonus here; the chart page stands without it
            logger.info("last play detail skipped for %s: %s", title, error)

    embed = discord.Embed(
        title=f"{title}",
        description=f"{ref.artist}\n-# {ref.genre} · {_version_label(cached, ref)}",
        color=discord.Color.from_rgb(*DIFFICULTY_COLOUR.get(ref.difficulty, (162, 102, 232))),
    )
    # embeds do not render markdown headings, so the chart name is a field title
    embed.add_field(
        name=f"{TIER_NAMES.get(ref.difficulty, ref.difficulty.upper())} {ref.level} · {ref.chart_type.upper()}",
        value=f"const **{ref.constant:.1f}**" + (f" · {ref.notes:,} notes" if ref.notes else "")
              + ("" if ref.intl else " · **Japan only**") + (" · **removed from the game**" if ref.deleted else "")
              + _note_split(ref) + _chart_credit(ref), inline=False,
    )
    _page_fields(embed, cached, ref, row, play, detail)
    _pattern_field(embed, cached, ref)

    files: List[discord.File] = []
    forecast = prediction_for(cached, ref, row)
    if forecast:
        forecast_text = f"a good run lands ~{forecast['expected']:.2f}% ({forecast['low']:.1f} to {forecast['high']:.1f})"
        if forecast.get("new_best") is not None:
            forecast_text += f" · {forecast['new_best'] * 100:.0f}% chance of a new best next time"
        else:
            forecast_text += " · first pass"
    else:
        forecast_text = ""
    shot = await _song_card(cached, title, refs, rows, highlight=ref.difficulty,
                            ladder=chart_ladder(cached, ref, row),
                            ladder_label=f"{TIER_NAMES.get(ref.difficulty, ref.difficulty.upper())} {ref.level}",
                            forecast=forecast_text)
    if shot:
        files.append(discord.File(io.BytesIO(shot), filename="rasmai-song.png"))
    thumb = jacket_file(cached, ref.cover)
    if thumb:
        files.append(thumb)
        embed.set_thumbnail(url=f"attachment://{thumb.filename}")
    footer = f"chart {page + 1} of {len(refs)} · constants from otoge-db"
    if cached:
        footer += f" · your cutoffs {_cutoffs(cached)}"
    embed.url = chart_url(title, ref.chart_type, ref.difficulty, ref.cover)
    page_info = await song_page(title, refs)
    videos = page_info["videos"]
    unlock_field(embed, page_info, cached)
    if (ref.chart_type, ref.difficulty) in videos:
        footer += " · video via SilentBlue RemyWiki"
    embed.set_footer(text=footer)
    view = SongView(owner_id, title, refs, rows, page, videos=videos, last_play=play["position"] if play else None) if owner_id is not None else None
    return embed, files, view


EMPTY_PAGE: Dict[str, Any] = {"page": "", "videos": {}, "unlock": []}


async def song_page(title: str, refs: List[ChartRef]) -> Dict[str, Any]:
    """What the wiki holds for the song (chart videos, unlock notes), within a short wait; a slow first fetch finishes in the background and is cached.

    :param title: The song title.
    :type title: str
    :param refs: Every chart the song has.
    :type refs: List[ChartRef]
    :rtype: Dict[str, Any]
    """
    if not WIKI_VIDEOS or not refs:
        return dict(EMPTY_PAGE)
    record = song_record(title)
    reading = str(record.get("alt_title", "") or "")
    types = [ref.chart_type for ref in refs]
    task = asyncio.ensure_future(asyncio.to_thread(wiki.lookup_page, title, reading, types))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
    except asyncio.TimeoutError:
        return dict(EMPTY_PAGE)
    except Exception as error:      # a wiki hiccup must never break /chart
        logger.info("wiki lookup failed for %r: %s", title, error)
        return dict(EMPTY_PAGE)


async def song_videos(title: str, refs: List[ChartRef]) -> Dict[Tuple[str, str], str]:
    return (await song_page(title, refs))["videos"]


async def build_song_details(cached: Optional[CachedAnalysis], query: str, owner_id: Optional[int] = None
                             ) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    """The song itself: who made it, when it landed, and every chart it has, with your scores where they exist.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param query: What the player typed.
    :type query: str
    :param owner_id: The Discord user the components answer to.
    :type owner_id: Optional[int]
    :rtype: Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]
    """
    from rasmai.bot.builders.charts.views import SongDetailsView
    title, refs, problem = _resolve_song(cached, query)
    if problem is not None:
        return problem, [], None
    record = song_record(title)
    first = refs[0]
    await ensure_play_counts(cached, refs)
    rows = _chart_rows(cached, refs)

    reading = str(record.get("alt_title", "") or "").strip()
    facts: List[str] = []
    if reading and loose_title(reading) != loose_title(title):
        facts.append(reading)
    facts.append(first.genre or "genre unknown")
    bpm = str(record.get("bpm", "") or "").strip()
    if bpm:
        facts.append(f"BPM {bpm}")
    version = version_name(record) or _version_label(cached, first)
    if version:
        facts.append(version)
    if cached and cached.analyzer.current_version and first.version == cached.analyzer.current_version:
        facts.append("current version")
    if not first.intl:
        facts.append("not on the international version")
    if first.deleted:
        facts.append("removed from the game")
    played = [r for r in rows if r.get("played")]
    embed = discord.Embed(
        title=title,
        description=f"{first.artist or 'artist unknown'}\n-# {' · '.join(facts)}",
        color=discord.Color.from_rgb(*DIFFICULTY_COLOUR.get(max(refs, key=lambda r: r.constant).difficulty, (162, 102, 232))),
    )
    for chart_type in ("std", "dx"):
        group = [(ref, row) for ref, row in zip(refs, rows) if ref.chart_type == chart_type]
        if not group:
            continue
        lines = [_song_chart_line(ref, row, chart_designer(record, ref)) for ref, row in group]
        embed.add_field(name=f"{'Standard' if chart_type == 'std' else 'DX'} charts", value=_fit(lines), inline=False)
    if cached:
        if played:
            best = max(played, key=lambda r: r["rating"])
            summary = f"**{len(played)}** of {len(rows)} charts played · best rating **{best['rating']}** on {TIER_NAMES.get(best['difficulty'], best['difficulty'].upper())}"
            if cached.analyzer.best50 is not None:
                inside = sum(1 for r in played if "in your best-50" in str(r.get("note", "")))
                if inside:
                    summary += f" · {inside} in your best-50"
        else:
            summary = "none of its charts played yet"
        embed.add_field(name="You", value=summary, inline=False)
    else:
        embed.add_field(name="You", value="-# /login to see your scores here", inline=False)
    wiki_url = str(record.get("wiki_url", "") or "").strip()
    footer = "levels, constants and note counts from otoge-db · title links to the dashboard"
    embed.set_footer(text=footer)

    files: List[discord.File] = []
    card_facts = [f"BPM {bpm}"] if bpm else []
    if reading and loose_title(reading) != loose_title(title):
        card_facts.insert(0, reading)
    shot = await _song_card(cached, title, refs, rows, eyebrow="Song lookup", version=version_name(record), facts=card_facts)
    if shot:
        files.append(discord.File(io.BytesIO(shot), filename="rasmai-song.png"))
    thumb = jacket_file(cached, first.cover)
    if thumb:
        files.append(thumb)
        embed.set_thumbnail(url=f"attachment://{thumb.filename}")
    embed.url = chart_url(title, first.chart_type, first.difficulty, first.cover)
    page_info = await song_page(title, refs)
    videos = page_info["videos"]
    unlock_field(embed, page_info, cached)
    view = SongDetailsView(owner_id, title, refs, rows, official=videos.get(("", "official")), wiki_url=wiki_url) if owner_id is not None else None
    if videos.get(("", "official")) or page_info.get("unlock"):
        embed.set_footer(text=footer + " · video and unlock notes via SilentBlue RemyWiki")
    return embed, files, view
