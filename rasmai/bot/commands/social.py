from typing import Optional
import logging

import discord
from discord import app_commands

from rasmai.bot.core import bot, heavy_cooldown, light_cooldown
from rasmai.bot.state.prefs import get_prefs, update_prefs
from rasmai.bot.builders.results import run_simple_command
from rasmai.bot.builders.social import build_compare, build_export, build_leaderboard, settings_embed
from rasmai.security import public_reason
from rasmai.storage.db import get_guild_settings, set_guild_settings
from rasmai.bot.commands.choices import CHALLENGE_CHOICES, DIFFICULTY_CHOICES, EXPORT_CHOICES, LAYOUT_CHOICES

logger = logging.getLogger(__name__)


@bot.tree.command(name="compare", description="Compare your scores with another player who opted in")
@heavy_cooldown
@app_commands.describe(user="Who to compare with")
async def compare(interaction: discord.Interaction, user: discord.User):
    await run_simple_command(interaction, "Something went wrong comparing.", lambda cached: build_compare(cached, user))


@bot.tree.command(name="leaderboard", description="Rating leaderboard for players in this server who opted in")
@light_cooldown
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def leaderboard(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("Leaderboards only work inside a server.", ephemeral=True)
        return
    if not interaction.is_guild_integration():
        await interaction.response.send_message(
            "I need to be added to this server to read who is in it. Every other command works here as-is.",
            ephemeral=True,
        )
        return
    if get_guild_settings(str(interaction.guild_id)).get("leaderboard") is False:
        await interaction.response.send_message("Leaderboards are turned off in this server. Someone with **Manage Server** can turn them on with `/server leaderboard:True`.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        embed, files, view = await build_leaderboard(interaction.guild, interaction.user.id)
    except Exception as error:
        logger.exception("leaderboard failed")
        await interaction.edit_original_response(content=f"Couldn't build the leaderboard.\n-# Details: {public_reason(error)}")
        return
    await interaction.edit_original_response(embed=embed, attachments=files, view=view)
    if view is not None:
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass


@bot.tree.command(name="settings", description="Your defaults and who can see your scores")
@app_commands.describe(
    layout="Default layout for the result commands",
    challenge="Default ambition of the targets, from easier through to long shots",
    new_difficulty="Default difficulty for /new",
    compare="Let other people run /compare against you",
    leaderboard="Show up on /leaderboard in servers you share with the bot",
    history="Read your recent plays once a day so none fall off the list (needs your account linked)",
    notify="DM you when the daily read finds new bests or your rating moved",
)
@app_commands.choices(layout=LAYOUT_CHOICES, challenge=CHALLENGE_CHOICES, new_difficulty=DIFFICULTY_CHOICES)
async def settings(interaction: discord.Interaction, layout: Optional[app_commands.Choice[str]] = None,
                   challenge: Optional[app_commands.Choice[str]] = None,
                   new_difficulty: Optional[app_commands.Choice[str]] = None,
                   compare: Optional[bool] = None, leaderboard: Optional[bool] = None, history: Optional[bool] = None,
                   notify: Optional[bool] = None):
    user_id = str(interaction.user.id)
    changes = {
        "layout": layout.value if layout else None,
        "challenge": challenge.value if challenge else None,
        "new_difficulty": new_difficulty.value if new_difficulty else None,
        "compare": compare,
        "leaderboard": leaderboard,
        "history": history,
        "notify": notify,
    }
    changed = any(value is not None for value in changes.values())
    prefs = update_prefs(user_id, **changes) if changed else get_prefs(user_id)
    await interaction.response.send_message(embed=settings_embed(prefs, changed, user_id=user_id), ephemeral=True)


@bot.tree.command(name="server", description="Switches for this server: whether /leaderboard is available here")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(leaderboard="Allow /leaderboard in this server (default on)")
async def server_settings(interaction: discord.Interaction, leaderboard: Optional[bool] = None):
    guild_id = str(interaction.guild_id)
    current = get_guild_settings(guild_id)
    if leaderboard is not None:
        current["leaderboard"] = leaderboard
        set_guild_settings(guild_id, current)
    board = "on" if current.get("leaderboard", True) else "off"
    saved = " · saved" if leaderboard is not None else ""
    await interaction.response.send_message(
        f"**Server settings{saved}**\n`/leaderboard` here: **{board}**\n-# people still choose for themselves whether they appear on it, with `/settings leaderboard`",
        ephemeral=True)


@bot.tree.command(name="export", description="Download your scores as a file")
@heavy_cooldown
@app_commands.describe(format="File format")
@app_commands.choices(format=EXPORT_CHOICES)
async def export(interaction: discord.Interaction, format: Optional[app_commands.Choice[str]] = None):
    fmt = format.value if format else "json"

    async def build(cached):
        file = build_export(cached, fmt)
        embed = discord.Embed(title="Your scores", description=f"Every chart with a score, as {fmt.upper()}. Only you can see this message.",
                              color=discord.Color.blurple())
        return embed, [file], None

    await run_simple_command(interaction, "Something went wrong exporting.", build, ephemeral=True)
