from typing import Optional
import logging

import discord
from discord import app_commands

from rasmai.bot.state.cache import cache_get
from rasmai.bot.builders.charts import (
    LEVEL_PATTERN, build_b50, build_dxscore, build_level, build_patterns, build_random, build_song, pattern_autocomplete, song_autocomplete,
)
from rasmai.bot.builders.charts.level import is_constant
from rasmai.bot.core import bot, heavy_cooldown, light_cooldown, private_only
from rasmai.bot.builders.areas import build_areas
from rasmai.bot.builders.history import build_lastplay, build_progress, build_recent
from rasmai.bot.builders.results import load_analysis, run_simple_command
from rasmai.bot.builders.results.view import failure_text
from rasmai.storage.db import get_connected_account
from rasmai.bot.commands.choices import DIFFICULTY_CHOICES, SORT_CHOICES, level_autocomplete

logger = logging.getLogger(__name__)


async def _lookup(interaction: discord.Interaction, what: str, build) -> None:
    """Shared body of /chart and /charts: load the analysis when there is one, build, post, remember the message.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction

    :param what: What to look up.
    :type what: str
    :param build: Builds the reply.
    """
    await interaction.response.defer(ephemeral=private_only(interaction))
    user_id = str(interaction.user.id)
    try:
        cached = cache_get(user_id)
        if cached is None and get_connected_account(user_id):
            cached = await load_analysis(interaction)
        embed, files, view = await build(cached)
        await interaction.edit_original_response(content=None, embed=embed, attachments=files, view=view)
        if view is not None:
            try:
                view.message = await interaction.original_response()
            except discord.HTTPException:
                pass
    except Exception as error:
        logger.exception("%s lookup failed", what)
        await interaction.edit_original_response(content=failure_text("Couldn't look that up.", error), embed=None, attachments=[], view=None)


@bot.tree.command(name="chart", description="One chart: your score, the prediction and what each rank is worth")
@light_cooldown
@app_commands.describe(name="Song title, artist or charter (start typing for suggestions)", difficulty="Open this difficulty (default: the chart that matters most)")
@app_commands.choices(difficulty=DIFFICULTY_CHOICES[:5])
@app_commands.autocomplete(name=song_autocomplete)
async def chart(interaction: discord.Interaction, name: str, difficulty: Optional[app_commands.Choice[str]] = None):
    await _lookup(interaction, "chart", lambda cached: build_song(
        cached, name, owner_id=interaction.user.id, difficulty=difficulty.value if difficulty else None))


@bot.tree.command(name="charts", description="Browse charts by trait or level, with your scores beside them")
@light_cooldown
@app_commands.describe(
    pattern="A trait, in Japanese or English: streams, 乱打, hand swaps, slide-heavy, dense charts (leave empty to see them all)",
    level="Level like 13 or 13+, or a constant like 13.8",
    difficulty="Only this difficulty",
    sort="Order of a level list",
)
@app_commands.autocomplete(pattern=pattern_autocomplete, level=level_autocomplete)
@app_commands.choices(difficulty=DIFFICULTY_CHOICES[:5], sort=SORT_CHOICES)
async def charts_command(interaction: discord.Interaction, pattern: Optional[str] = None, level: Optional[str] = None,
                         difficulty: Optional[app_commands.Choice[str]] = None, sort: Optional[app_commands.Choice[str]] = None):
    owner = interaction.user.id
    chosen_level = (level or "").strip() or None
    if chosen_level and chosen_level not in LEVEL_PATTERN and not is_constant(chosen_level):
        await interaction.response.send_message(f"`{chosen_level[:12]}` is not a maimai level. Try one like `13` or `13+`, or a constant like `13.8`.", ephemeral=True)
        return
    wanted = difficulty.value if difficulty else None
    if pattern or not chosen_level:
        # the pattern browser works without a linked account; scores join the list when there is one
        await _lookup(interaction, "patterns", lambda cached: build_patterns(cached, owner, pattern or "", chosen_level, wanted))
        return
    await run_simple_command(interaction, "Something went wrong listing that level.",
                             lambda cached: build_level(cached, owner, chosen_level, sort.value if sort else "weakest", 0))


@bot.tree.command(name="random", description="Pick a random chart to play")
@light_cooldown
@app_commands.describe(level="Only this level, like 13+", difficulty="Only this difficulty",
                       unplayed="Only charts you have never played")
@app_commands.autocomplete(level=level_autocomplete)
@app_commands.choices(difficulty=DIFFICULTY_CHOICES[:5])
async def random_chart(interaction: discord.Interaction, level: Optional[str] = None,
                       difficulty: Optional[app_commands.Choice[str]] = None, unplayed: bool = False):
    owner = interaction.user.id
    wanted = difficulty.value if difficulty else None
    await run_simple_command(interaction, "Something went wrong picking a chart.",
                             lambda cached: build_random(cached, owner, (level or "").strip() or None, wanted, unplayed))


@bot.tree.command(name="dxscore", description="Your DX score stars and the charts closest to the next one")
@heavy_cooldown
async def dxscore(interaction: discord.Interaction):
    await run_simple_command(interaction, "Something went wrong reading your DX scores.", lambda cached: build_dxscore(cached, interaction.user.id))


@bot.tree.command(name="b50", description="Your best 50: the charts that make up your rating")
@heavy_cooldown
async def b50(interaction: discord.Interaction):
    await run_simple_command(interaction, "Something went wrong building your best-50.", lambda cached: build_b50(cached, interaction.user.id))


@bot.tree.command(name="top", description="Your best 50: the charts that make up your rating (same as /b50)")
@heavy_cooldown
async def top(interaction: discord.Interaction):
    await run_simple_command(interaction, "Something went wrong building your best-50.", lambda cached: build_b50(cached, interaction.user.id))


@bot.tree.command(name="recent", description="Your last sessions: every play, new bests and what counted; or one play in full")
@heavy_cooldown
@app_commands.describe(play="Show one play in full with its judgements: 1 = newest, 2 = the one before, and so on")
async def recent(interaction: discord.Interaction, play: Optional[app_commands.Range[int, 1, 50]] = None):
    owner = interaction.user.id
    if play:
        await run_simple_command(interaction, "Something went wrong reading that play.", lambda cached: build_lastplay(cached, owner, play))
        return
    await run_simple_command(interaction, "Something went wrong reading your recent plays.", lambda cached: build_recent(cached, owner))


@bot.tree.command(name="area", description="Area travel: your distance in each area, the next reward, and how many plays away it is")
@heavy_cooldown
async def area(interaction: discord.Interaction):
    await run_simple_command(interaction, "Something went wrong reading your areas.", build_areas)


@bot.tree.command(name="progress", description="Your rating over time")
@heavy_cooldown
async def progress(interaction: discord.Interaction):
    await run_simple_command(interaction, "Something went wrong reading your history.", build_progress)
