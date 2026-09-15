from typing import List, Optional, Tuple
import io
import random
import discord

from rasmai.engine.analysis import DIFFICULTY_ORDER
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.ui.formatting import TIER_NAMES
from rasmai.web.links import chart_url
from rasmai.bot.ui.views import OwnerOnlyView
from rasmai.bot.builders.charts.index import charts_for, jacket_file, song_for_chart, songs_by_loose_key
from rasmai.bot.builders.charts.rows import _chart_rows, _song_card
from rasmai.bot.builders.charts.page import page_index
from rasmai.bot.builders.charts.song import build_song
from rasmai.bot.builders.charts.ladder import entry_note


async def build_random(cached: CachedAnalysis, owner_id: int, level: Optional[str], difficulty: Optional[str],
                       unplayed: bool) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    a = cached.analyzer
    loose_map = songs_by_loose_key(cached)
    pool = [
        ref for ref in a.chart_index.values()
        if ref.difficulty in DIFFICULTY_ORDER and a.chart_index.playable(ref)
        and (not level or str(ref.level).strip() == level)
        and (not difficulty or ref.difficulty == difficulty)
        # a random pick is something to go and play, so a song still behind an unlock is no use
        and (not unplayed or (song_for_chart(loose_map, ref) is None and not ref.locked))
    ]
    embed = discord.Embed(color=discord.Color.from_rgb(92, 211, 232))
    embed.set_author(name=a.player.name)
    if not pool:
        embed.title = "Nothing matches"
        embed.description = "No chart fits those filters. Loosen the level or difficulty."
        return embed, [], None
    ref = random.choice(pool)
    song = song_for_chart(loose_map, ref)
    refs = charts_for(ref.title, a.chart_index)
    embed.title = ref.title
    embed.url = chart_url(ref.title, ref.chart_type, ref.difficulty, ref.cover)
    embed.description = f"**{TIER_NAMES.get(ref.difficulty, ref.difficulty.upper())} {ref.level}** · {ref.chart_type.upper()} · const {ref.constant:.1f}\n{ref.artist} · {ref.genre}"
    if song is None:
        expected = a.play_profile.expected_for(ref.constant, ref.difficulty) if a.play_profile else 0.0
        value = "never played"
        if expected:
            value += f" · you'd usually land ~{expected:.1f}% here"
        embed.add_field(name="Your score", value=value, inline=False)
    else:
        embed.add_field(name="Your score", value=f"**{float(song.accuracy):.4f}%** {song.current_rank} · rating {int(song.rating)}", inline=False)
    embed.add_field(name="Best-50", value=entry_note(cached, ref, song), inline=False)
    files: List[discord.File] = []
    shot = await _song_card(cached, ref.title, refs, _chart_rows(cached, refs), highlight=ref.difficulty)
    if shot:
        files.append(discord.File(io.BytesIO(shot), filename="rasmai-song.png"))
    thumb = jacket_file(cached, ref.cover)
    if thumb:
        files.append(thumb)
        embed.set_thumbnail(url=f"attachment://{thumb.filename}")
    embed.set_footer(text=f"one of {len(pool)} charts that fit")
    return embed, files, RandomView(owner_id, level, difficulty, unplayed, ref.title, page_index(refs, ref.chart_type, ref.difficulty))


class RandomView(OwnerOnlyView):
    def __init__(self, owner_id: int, level: Optional[str], difficulty: Optional[str], unplayed: bool,
                 title: str = "", page: Optional[int] = None):
        super().__init__(owner_id, timeout=600)
        self.level, self.difficulty, self.unplayed = level, difficulty, unplayed
        self.title, self.page = title, page
        self.message: Optional[discord.Message] = None
        again = discord.ui.Button(label="Another", style=discord.ButtonStyle.primary)
        again.callback = self._again
        self.add_item(again)
        if title:
            details = discord.ui.Button(label="Chart details", style=discord.ButtonStyle.secondary)
            details.callback = self._details
            self.add_item(details)

    async def _details(self, interaction: discord.Interaction) -> None:
        from rasmai.bot.state.cache import cache_get
        await interaction.response.defer()
        cached = cache_get(str(self.owner_id))
        embed, files, view = await build_song(cached, self.title, self.page, self.owner_id)
        await interaction.edit_original_response(embed=embed, attachments=files, view=view)
        if view is not None:
            view.message = self.message

    async def _again(self, interaction: discord.Interaction) -> None:
        from rasmai.bot.state.cache import cache_get
        await interaction.response.defer()
        cached = cache_get(str(self.owner_id))
        if cached is None:
            await interaction.followup.send("Those results have expired - run the command again.", ephemeral=True)
            return
        embed, files, view = await build_random(cached, self.owner_id, self.level, self.difficulty, self.unplayed)
        await interaction.edit_original_response(embed=embed, attachments=files, view=view)
        if view is not None:
            view.message = self.message
