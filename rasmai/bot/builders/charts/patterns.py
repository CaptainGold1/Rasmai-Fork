from typing import Any, Dict, List, Optional, Tuple
import math

import discord
from discord import app_commands

from rasmai.engine import patterns
from rasmai.engine.analysis import rank_for
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.ui.formatting import TIER_SHORT, _fit, chart_link, message_files
from rasmai.bot.ui.views import OwnerOnlyView
from rasmai.bot.builders.charts.index import shared_index, song_for_chart, songs_by_loose_key
from rasmai.bot.builders.charts.ladder import entry_note

PAGE = 12


def _index(cached: Optional[CachedAnalysis]) -> Any:
    return cached.analyzer.chart_index if cached else shared_index()


def pattern_rows(cached: Optional[CachedAnalysis], tag: str, level: Optional[str], difficulty: Optional[str]) -> List[Dict[str, Any]]:
    """The charts carrying a pattern, hardest first, each with the player's own score where there is one.

    :param cached: The player's analysis, held in memory; None for someone not linked.
    :type cached: Optional[CachedAnalysis]
    :param tag: The mai-notes tag.
    :type tag: str
    :param level: A displayed level, or None.
    :type level: Optional[str]
    :param difficulty: A difficulty tier, or None.
    :type difficulty: Optional[str]
    :rtype: List[Dict[str, Any]]
    """
    index = _index(cached)
    loose = songs_by_loose_key(cached) if cached else {}
    rows: List[Dict[str, Any]] = []
    for ref in patterns.charts_with(index, tag, level, difficulty, patterns.reading_for(cached)):
        song = song_for_chart(loose, ref) if cached else None
        rows.append({
            "title": ref.title, "chart_type": ref.chart_type, "difficulty": ref.difficulty, "level": ref.level, "constant": ref.constant,
            "cover": ref.cover, "played": song is not None,
            "accuracy": float(song.accuracy or 0) if song is not None else None,
            "rank": (song.current_rank or rank_for(float(song.accuracy or 0))) if song is not None else "",
            "rating": int(song.rating or 0) if song is not None else 0,
            "note": entry_note(cached, ref, song) if cached else "",
            "tags": [patterns.label_of(t) for t in patterns.tags_of(ref) if t != tag][:3],
        })
    return rows


def _line(index: int, r: Dict[str, Any]) -> str:
    short = TIER_SHORT.get(r["difficulty"], r["difficulty"][:3].upper())
    head = f"`{index:>3}` {chart_link(r['title'], r['chart_type'], r['difficulty'], r.get('cover', ''))} {short} {r['chart_type'].upper()} · {r['constant']:.1f}"
    also = f" · also {', '.join(patterns.english_of(t.split(' (')[0]) for t in r['tags'])}" if r["tags"] else ""
    if r["played"]:
        return f"{head}\n-# **{r['accuracy']:.4f}** {r['rank']} · {r['rating']}{(' · ' + r['note']) if r['note'] else ''}{also}"
    return f"{head}\n-# never played{also}"


def catalogue_embed(cached: Optional[CachedAnalysis]) -> discord.Embed:
    """Every pattern tag with how many charts carry it: the map of what the charts ask of you."""
    items = patterns.catalogue(_index(cached), patterns.reading_for(cached))
    embed = discord.Embed(title="Traits", color=discord.Color.from_rgb(92, 211, 232))
    embed.description = ("What a chart asks of your hands. Pick one with `/charts pattern:` to see every chart that has it, with your own "
                         "scores beside them; the option searches Japanese and English, so `streams` and `乱打` both find it.\n"
                         "-# a trait is a reading aid: knowing a chart is streams and hand swaps tells you what to watch for on your next run")
    if not items:
        embed.add_field(name="Nothing read yet", value="The chart table from maiノーツ has not been read on this instance.", inline=False)
        return embed
    community = [item for item in items if item["community"]]
    measured = [item for item in items if not item["community"]]
    if community:
        lines = [f"**{item['english']}** · {item['tag']} · {item['charts']}" for item in community]
        half = math.ceil(len(lines) / 2)
        embed.add_field(name=f"Tagged by maiノーツ · {len(community)} · charts each", value=_fit(lines[:half]), inline=True)
        if lines[half:]:
            embed.add_field(name="​", value=_fit(lines[half:]), inline=True)
    if measured:
        embed.add_field(name=f"Measured from the chart · {len(measured)} · charts each",
                        value=_fit([f"**{item['label']}** · {item['charts']}" for item in measured]), inline=False)
    embed.set_footer(text="maiノーツ's editors have tagged about one chart in ten, nearly all Master and above · the measured ones come from the chart's own notes, tempo and density")
    return embed


async def build_patterns(cached: Optional[CachedAnalysis], owner_id: int, query: str, level: Optional[str], difficulty: Optional[str],
                         page: int = 0) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    """Charts carrying a pattern, in pages, with the player's own scores where they are linked.

    :param cached: The player's analysis, held in memory; None for someone not linked.
    :type cached: Optional[CachedAnalysis]
    :param owner_id: The Discord user id of whoever asked.
    :type owner_id: int
    :param query: The tag as typed: Japanese, English, or part of either. Empty shows the catalogue.
    :type query: str
    :param level: A displayed level, or None.
    :type level: Optional[str]
    :param difficulty: A difficulty tier, or None.
    :type difficulty: Optional[str]
    :param page: Which page of the list to show.
    :type page: int
    :rtype: Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]
    """
    files: List[discord.File] = []
    avatar_url = None
    if cached is not None:
        files, avatar_url = message_files(cached.analyzer.player, None, "")
    if not str(query or "").strip():
        embed = catalogue_embed(cached)
        if cached is not None:
            embed.set_author(name=cached.analyzer.player.name, icon_url=avatar_url)
        return embed, files, None
    index = _index(cached)
    reading = patterns.reading_for(cached)
    tag = patterns.resolve(query, index, reading)
    if tag is None:
        near = patterns.suggest(str(query)[:2], index, limit=4, reading=reading)
        hint = (" Closest: " + ", ".join(f"`{item['english'] if item['community'] else item['label']}`" for item in near)) if near else ""
        embed = discord.Embed(title="Traits", description=f"No trait matches `{str(query)[:40]}`. Run `/charts` on its own to see them all.{hint}",
                              color=discord.Color.from_rgb(92, 211, 232))
        return embed, files, None
    entry = next((item for item in patterns.catalogue(index, reading) if item["tag"] == tag), None)
    rows = pattern_rows(cached, tag, level, difficulty)
    pages = max(1, math.ceil(len(rows) / PAGE))
    page = max(0, min(page, pages - 1))
    scope = " · ".join(bit for bit in (f"level {level}" if level else "", TIER_SHORT.get(difficulty or "", "") if difficulty else "") if bit)
    heading = f"{patterns.english_of(tag)} · {tag}" if (entry is None or entry["community"]) else str(entry["label"])
    embed = discord.Embed(title=heading, color=discord.Color.from_rgb(92, 211, 232))
    if cached is not None:
        embed.set_author(name=cached.analyzer.player.name, icon_url=avatar_url)
    played = sum(1 for r in rows if r["played"])
    if not rows:
        embed.description = f"No playable chart carries this tag{' at ' + scope if scope else ''}."
        return embed, files, None
    embed.description = (f"**{len(rows)}** charts{' · ' + scope if scope else ''}, hardest first"
                         + (f" · you have played **{played}** of them" if cached is not None else "")
                         + "\n-# use these to practice the pattern on purpose, or to know what to watch for before a run")
    lines = [_line(i, r) for i, r in enumerate(rows[page * PAGE:(page + 1) * PAGE], page * PAGE + 1)]
    half = math.ceil(len(lines) / 2)
    embed.add_field(name=f"Charts {page * PAGE + 1}-{min((page + 1) * PAGE, len(rows))}", value=_fit(lines[:half]), inline=True)
    if lines[half:]:
        embed.add_field(name="​", value=_fit(lines[half:]), inline=True)
    source = "tagged by maiノーツ" if (entry is None or entry["community"]) else "measured from each chart's own notes"
    embed.set_footer(text=f"page {page + 1}/{pages} · {source} · /chart shows a chart's own traits")
    return embed, files, PatternsView(owner_id, query, level, difficulty, page, pages) if pages > 1 else None


class PatternsView(OwnerOnlyView):
    def __init__(self, owner_id: int, query: str, level: Optional[str], difficulty: Optional[str], page: int, pages: int):
        super().__init__(owner_id, timeout=600)
        self.query, self.level, self.difficulty, self.page, self.pages = query, level, difficulty, page, pages
        prev_button = discord.ui.Button(label="Prev", style=discord.ButtonStyle.secondary, disabled=page <= 0)
        prev_button.callback = self._mover(-1)
        self.add_item(prev_button)
        next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, disabled=page >= pages - 1)
        next_button.callback = self._mover(1)
        self.add_item(next_button)

    def _mover(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            from rasmai.bot.state.cache import cache_get
            await interaction.response.defer()
            cached = cache_get(str(self.owner_id))
            embed, files, view = await build_patterns(cached, self.owner_id, self.query, self.level, self.difficulty, self.page + delta)
            await interaction.edit_original_response(embed=embed, attachments=files, view=view)
            if view is not None:
                view.message = self.message
        return callback


def _choice_name(item: Dict[str, Any]) -> str:
    if item["community"]:
        return f"{item['english']} · {item['tag']} · {item['charts']} charts"[:100]
    return f"{item['label']} · measured · {item['charts']} charts"[:100]


async def pattern_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    # the person typing decides whether traits read from the charts are offered at all
    from rasmai.bot.state.cache import cache_get
    reading = patterns.reading_for(cache_get(str(interaction.user.id)))
    items = patterns.suggest(current, shared_index(), reading=reading)
    return [app_commands.Choice(name=_choice_name(item), value=item["tag"][:100]) for item in items]
