from typing import Any, Dict, List, Optional, Tuple
import asyncio
import logging

import discord

from rasmai.engine.analysis import rank_for
from rasmai.engine.losses import note_losses
from rasmai.bot.state.cache import CachedAnalysis, cache_get
from rasmai.bot.builders.charts import build_song, build_song_history, charts_for, jacket_file, page_index
from rasmai.bot.ui.formatting import TIER_NAMES, message_files, stamp, today
from rasmai.web.links import chart_url
from rasmai.bot.ui import emoji
from rasmai.bot.ui.views import OwnerOnlyView
from rasmai.scraping.scraper import SessionRejected
from rasmai.security import public_reason
from rasmai.storage.db import get_connected_account, mark_session_expired
from rasmai.bot.core import try_render
from rasmai.images.cards import play_card_html
from rasmai.images.render import cover_html_factory
from rasmai.images.pages import star_text, stars_for
from rasmai.bot.builders.history.plays import recent_plays

logger = logging.getLogger(__name__)


NOTE_ORDER = ("tap", "hold", "slide", "touch", "break")


def lost_text(detail: Dict[str, Any]) -> str:
    """What each note type cost the play, largest first: "break **1.23%** · tap **0.97%**", or "" without judgements.

    :param detail: The play's judgement page.
    :type detail: Dict[str, Any]
    :rtype: str
    """
    lost = note_losses(detail.get("notes") or {}, float(detail.get("achievement") or 0))
    return " · ".join(f"{kind} **{value:.2f}%**" for kind, value in sorted(lost.items(), key=lambda kv: -kv[1]) if value >= 0.005)


def play_detail(cached: CachedAnalysis, idx: str) -> Dict[str, Any]:
    """The judgement page for one play on the recent list, read once and kept with the analysis.

    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :param idx: The site's own id for the play.
    :type idx: str
    :rtype: Dict[str, Any]
    """
    slot = f"playlog:{idx}"
    detail = cached.extras.get(slot)
    if detail is None:
        a = cached.analyzer
        if getattr(a, "_official_session", None) is None:
            # an analysis loaded from the stored copy has never signed in; the play page needs a session
            account = get_connected_account(cached.user_id)
            if not account or not account.get("token"):
                raise ValueError("Not signed in")
            try:
                a.fetch_official_player_profile(str(account["token"]), cached.region)
            except SessionRejected:
                # for someone who only uses the website this is the first live read of the visit,
                # so it is where a dead sign-in surfaces; flagging it here covers /lastplay too
                mark_session_expired(cached.user_id)
                raise
        detail = a.fetch_playlog_detail(idx, cached.region)
        cached.extras[slot] = detail
        record = next((r for r in a.recent_songs or [] if str(r.get("idx", "")) == idx), None)
        if record:
            from rasmai.bot.state.snapshots import judgement_key
            from rasmai.storage.db import save_judgement
            try:
                save_judgement(cached.user_id, idx, *judgement_key(a, record), detail)
            except Exception:
                logger.exception("Could not store a judgement page")
    return detail


async def build_lastplay(cached: CachedAnalysis, owner_id: int, position: int) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    a = cached.analyzer
    player = a.player
    plays = recent_plays(cached)
    if not plays:
        embed = discord.Embed(title="No recent plays", description="Nothing on the account's recent-plays list yet.", color=discord.Color.orange())
        return embed, [], None
    position = max(1, min(position, len(plays)))
    play = plays[position - 1]
    detail = await asyncio.to_thread(play_detail, cached, play["idx"])

    card_key = f"playcard:{play['idx']}"
    if card_key not in cached.images:
        cached.images[card_key] = await try_render(play_card_html(
            play, detail, cover_html_factory(a.jacket_path), player.name, cached.start_rating, player.avatar_base64, date_text=today(),
        ))
    files, avatar_url = message_files(player, cached.images[card_key], "rasmai-play.png")
    embed = discord.Embed(
        title=f"{play['title']}",
        url=chart_url(play["title"], play["chart_type"], play["difficulty"], play.get("cover", "")),
        description=(f"**{TIER_NAMES.get(play['difficulty'], play['difficulty'].upper())} {play['level']}** · "
                     f"{play['chart_type'].upper()} · {detail.get('track') or play['track']} · "
                     + (stamp(play["when"], "f") if play["when"] else str(detail.get("played_at") or play["day"]))),
        color=discord.Color.from_rgb(162, 102, 232),
    )
    embed.set_author(name=player.name, icon_url=avatar_url)
    thumb = jacket_file(cached, play["cover"])
    if thumb:
        files.append(thumb)
        embed.set_thumbnail(url=f"attachment://{thumb.filename}")
    achievement = detail.get("achievement") or play["achievement"] or 0.0
    lamp = emoji.lamps(play["fc"], play["fs"])
    shown_rank = rank_for(achievement)
    best = f" {emoji.emoji('pb')} **new best**" if play["pb"] else ""
    embed.add_field(name="Achievement", value=f"**{achievement:.4f}%** {emoji.rank(shown_rank, shown_rank)}{best}" + (f"\n{lamp}" if lamp else ""), inline=True)
    max_dx = detail.get("max_dx_score") or play["max_dx"]
    dx = detail.get("dx_score") or play["dx"]
    stars = stars_for(dx / max_dx) if max_dx else 0
    embed.add_field(name="DX score", value=f"**{dx:,}** / {max_dx:,}\n-# {star_text(stars)} {100.0 * dx / max_dx if max_dx else 0:.1f}%", inline=True)
    embed.add_field(name="Combo", value=f"**{detail.get('combo', 0):,}** / {detail.get('max_combo', 0):,}" + (f"\n-# sync {detail.get('sync', 0):,} / {detail.get('max_sync', 0):,}" if detail.get("max_sync") else ""), inline=True)
    embed.add_field(name="Timing", value=f"fast **{detail.get('fast', 0)}** · late **{detail.get('late', 0)}**", inline=True)
    change = detail.get("rating_change", 0)
    embed.add_field(name="Rating after", value=f"**{detail.get('rating', 0)}** ({change:+d})", inline=True)
    if play["chart_rating"]:
        embed.add_field(name="Chart rating", value=f"**{play['chart_rating']}**" + (" · in best-50" if play["in_b50"] else ""), inline=True)
    notes = detail.get("notes") or {}
    if notes:
        header = f"{'':7s}{'CRIT':>6}{'PERF':>6}{'GREAT':>6}{'GOOD':>6}{'MISS':>6}"
        rows = [header]
        totals = {"critical": 0, "perfect": 0, "great": 0, "good": 0, "miss": 0}
        for kind in NOTE_ORDER:
            n = notes.get(kind)
            if not n:
                continue
            rows.append(f"{kind.upper():7s}{n['critical']:>6}{n['perfect']:>6}{n['great']:>6}{n['good']:>6}{n['miss']:>6}")
            for k in totals:
                totals[k] += n.get(k, 0)
        rows.append(f"{'ALL':7s}{totals['critical']:>6}{totals['perfect']:>6}{totals['great']:>6}{totals['good']:>6}{totals['miss']:>6}")
        cost = lost_text(detail)
        embed.add_field(name="Judgements", value="```\n" + "\n".join(rows) + "\n```" + (f"\n-# lost to {cost}" if cost else ""), inline=False)
    embed.set_footer(text=f"play {position} of {len(plays)} · newest first")
    refs = charts_for(play["title"], a.chart_index)
    return embed, files, LastPlayView(owner_id, position, len(plays), play["title"], page_index(refs, play["chart_type"], play["difficulty"]))


class LastPlayView(OwnerOnlyView):
    def __init__(self, owner_id: int, position: int, total: int, title: str = "", page: Optional[int] = None):
        super().__init__(owner_id, timeout=600)
        self.position, self.total = position, total
        self.title, self.page = title, page
        self.message: Optional[discord.Message] = None
        newer = discord.ui.Button(label="Newer", style=discord.ButtonStyle.primary, disabled=position <= 1)
        newer.callback = self._mover(-1)
        self.add_item(newer)
        older = discord.ui.Button(label="Older", style=discord.ButtonStyle.primary, disabled=position >= total)
        older.callback = self._mover(1)
        self.add_item(older)
        if title:
            for label, build in (("Chart details", build_song), ("Score history", build_song_history)):
                jump = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)
                jump.callback = self._jump(build)
                self.add_item(jump)

    def _jump(self, build):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = cache_get(str(self.owner_id))
            try:
                embed, files, view = await build(cached, self.title, self.page, self.owner_id)
            except Exception as error:
                logger.exception("lastplay jump failed")
                await interaction.followup.send(f"Couldn't open that chart: {public_reason(error)}", ephemeral=True)
                return
            await interaction.edit_original_response(embed=embed, attachments=files, view=view)
            if view is not None:
                view.message = self.message
        return callback

    def _mover(self, delta: int):
        async def callback(interaction: discord.Interaction) -> None:
            await interaction.response.defer()
            cached = cache_get(str(self.owner_id))
            if cached is None:
                await interaction.followup.send("Those results have expired - run the command again.", ephemeral=True)
                return
            try:
                embed, files, view = await build_lastplay(cached, self.owner_id, self.position + delta)
            except Exception as error:
                logger.exception("playlog detail failed")
                await interaction.followup.send(f"Couldn't read that play: {public_reason(error)}", ephemeral=True)
                return
            await interaction.edit_original_response(embed=embed, attachments=files, view=view)
            if view is not None:
                view.message = self.message
        return callback
