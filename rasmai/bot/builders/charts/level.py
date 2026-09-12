from typing import Any, Dict, List, Optional, Tuple
import math
import re
import discord

from rasmai.engine.analysis import DIFFICULTY_ORDER, rank_for
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.ui.formatting import TIER_SHORT, _fit, chart_link, message_files, today
from rasmai.bot.ui.views import OwnerOnlyView
from rasmai.images.render import cover_html_factory
from rasmai.images.pages import level_image_html
from rasmai.bot.builders.charts.index import loose_key, songs_by_key, songs_by_loose_key
from rasmai.bot.builders.charts.ladder import entry_note


LEVEL_SORTS = {"weakest": "weakest first", "unplayed": "unplayed first", "rating": "highest rating first"}


LEVEL_PAGE = 12


def is_constant(level: str) -> bool:
    """Whether a level as typed is a constant like ``13.8`` rather than a level like ``13+``."""
    return bool(re.fullmatch(r"\d{1,2}\.\d", level.strip()))


def level_rows(cached: CachedAnalysis, level: str, sort: str) -> List[Dict[str, Any]]:
    a = cached.analyzer
    by_key = songs_by_key(cached)
    rows: List[Dict[str, Any]] = []
    seen = set()
    constant = float(level) if is_constant(level) else None

    def at_level(shown: Any, value: float) -> bool:
        return abs(value - constant) < 0.05 if constant is not None else str(shown or "").strip() == level

    for key, song in by_key.items():
        ref = a.chart_index.get(key)
        if not at_level(song.level, float(song.difficulty or (ref.constant if ref else 0))) or str(song.difficulty_type).lower() == "utage":
            continue
        ref = a.chart_index.get(key)
        seen.add(key)
        rows.append({
            "title": song.name, "difficulty": key[2], "chart_type": key[1], "level": level,
            "constant": float(song.difficulty or (ref.constant if ref else 0)),
            "accuracy": float(song.accuracy or 0), "rank": song.current_rank or rank_for(float(song.accuracy or 0)),
            "rating": int(song.rating or 0), "fc": song.fc_status, "fs": song.fs_status, "unplayed": False,
            "cover": song.cover_url or (ref.cover if ref else ""),
            "note": entry_note(cached, ref, song) if ref else "",
        })
    played_loose = set(songs_by_loose_key(cached))
    for ref in a.chart_index.values():
        if not at_level(ref.level, ref.constant) or ref.difficulty not in DIFFICULTY_ORDER:
            continue
        if ref.key in seen or loose_key(ref.title, ref.chart_type, ref.difficulty) in played_loose:
            continue
        if not a.chart_index.playable(ref):
            continue
        rows.append({
            "title": ref.title, "difficulty": ref.difficulty, "chart_type": ref.chart_type, "level": level,
            "constant": ref.constant, "accuracy": 0.0, "rank": "", "rating": 0, "fc": "", "fs": "",
            "unplayed": True, "cover": ref.cover, "note": entry_note(cached, ref, None),
        })
    if sort == "unplayed":
        rows.sort(key=lambda r: (not r["unplayed"], r["accuracy"], -r["constant"]))
    elif sort == "rating":
        rows.sort(key=lambda r: (r["unplayed"], -r["rating"], -r["accuracy"]))
    else:
        rows.sort(key=lambda r: (r["unplayed"], r["accuracy"], -r["constant"]))
    return rows


async def build_level(cached: CachedAnalysis, owner_id: int, level: str, sort: str, page: int) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    from rasmai.bot.builders.results import _image
    a = cached.analyzer
    player = a.player
    level = level.strip()
    sort = sort if sort in LEVEL_SORTS else "weakest"
    rows = level_rows(cached, level, sort)
    pages = max(1, math.ceil(len(rows) / LEVEL_PAGE))
    page = max(0, min(page, pages - 1))
    played = sum(1 for r in rows if not r["unplayed"])
    shot = None
    if rows:
        # the image carries this page's charts as big cards, so it is drawn again on every page turn
        shot = await _image(cached, f"level:{level}:{sort}:{page}", lambda: level_image_html(
            rows[page * LEVEL_PAGE:(page + 1) * LEVEL_PAGE], level, LEVEL_SORTS[sort], player.name, cached.start_rating,
            player.avatar_base64, cover_html_factory(a.jacket_path), len(rows), played, start=page * LEVEL_PAGE + 1, date_text=today(),
        ))
    files, avatar_url = message_files(player, shot, "rasmai-level.png")
    embed = discord.Embed(title=f"{'Constant' if is_constant(level) else 'Level'} {level} · {LEVEL_SORTS[sort]}", color=discord.Color.from_rgb(226, 69, 90))
    embed.set_author(name=player.name, icon_url=avatar_url)
    if not rows:
        embed.description = f"No charts at {level} in the database. Levels look like `13` or `13+`, constants like `13.8`."
        return embed, files, None
    embed.description = f"**{played}** of **{len(rows)}** charts played" + (f" · {len(rows) - played} never played" if len(rows) > played else "")
    lines: List[str] = []
    for index, r in enumerate(rows[page * LEVEL_PAGE:(page + 1) * LEVEL_PAGE], page * LEVEL_PAGE + 1):
        short = TIER_SHORT.get(r["difficulty"], r["difficulty"][:3].upper())
        if r["unplayed"]:
            lines.append(f"`{index:>3}` {chart_link(r['title'], r['chart_type'], r['difficulty'], r.get('cover', ''))} {short} {r['chart_type'].upper()}\n-# never played · const {r['constant']:.1f}")
        else:
            lines.append(f"`{index:>3}` {chart_link(r['title'], r['chart_type'], r['difficulty'], r.get('cover', ''))} {short} {r['chart_type'].upper()}\n-# {r['constant']:.1f} · **{r['accuracy']:.4f}** {r['rank']} · {r['rating']} · {r['note']}")
    half = math.ceil(len(lines) / 2)
    embed.add_field(name=f"Charts {page * LEVEL_PAGE + 1}-{min((page + 1) * LEVEL_PAGE, len(rows))}", value=_fit(lines[:half]), inline=True)
    if lines[half:]:
        embed.add_field(name="​", value=_fit(lines[half:]), inline=True)
    embed.set_footer(text=f"page {page + 1}/{pages} · the image shows this page's charts")
    return embed, files, LevelView(owner_id, level, sort, page, pages)


class LevelView(OwnerOnlyView):
    def __init__(self, owner_id: int, level: str, sort: str, page: int, pages: int):
        super().__init__(owner_id, timeout=600)
        self.level, self.sort, self.page, self.pages = level, sort, page, pages
        self.message: Optional[discord.Message] = None
        prev_button = discord.ui.Button(label="Prev", row=0, style=discord.ButtonStyle.secondary, disabled=page <= 0)
        prev_button.callback = self._mover(-1)
        self.add_item(prev_button)
        next_button = discord.ui.Button(label="Next", row=0, style=discord.ButtonStyle.secondary, disabled=page >= pages - 1)
        next_button.callback = self._mover(1)
        self.add_item(next_button)
        select = discord.ui.Select(placeholder="Sort", row=1, options=[
            discord.SelectOption(label=label.capitalize(), value=value, default=value == sort) for value, label in LEVEL_SORTS.items()
        ])
        select.callback = self._sorter(select)
        self.add_item(select)

    async def _redraw(self, interaction: discord.Interaction, sort: str, page: int) -> None:
        from rasmai.bot.state.cache import cache_get
        await interaction.response.defer()
        cached = cache_get(str(self.owner_id))
        if cached is None:
            await interaction.followup.send("Those results have expired - run the command again.", ephemeral=True)
            return
        embed, files, view = await build_level(cached, self.owner_id, self.level, sort, page)
        await interaction.edit_original_response(embed=embed, attachments=files, view=view)
        if view is not None:
            view.message = self.message

    def _mover(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self._redraw(interaction, self.sort, self.page + delta)
        return callback

    def _sorter(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction) -> None:
            await self._redraw(interaction, select.values[0], 0)
        return callback

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
