from typing import Optional

import discord
from discord import app_commands

from rasmai.bot.core import bot
from rasmai.bot.ui.login import send_login_card
from rasmai.bot.tasks.presence import describe
from rasmai.bot.ui.views import DeleteAccountView
from rasmai.config import DISCORD_BOT_INVITE, MAIMAI_BASE_URLS, get_public_base_url
from rasmai.storage.db import get_connected_account
from rasmai.bot.commands.choices import REGION_CHOICES


@bot.tree.command(name="help", description="What this bot does and how to use it")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Rasmai",
        description=(
            "I read your maimai DX scores and work out what to play next to raise "
            "your rating - based on how *you* actually play, not a generic list."
        ),
        color=discord.Color.from_rgb(124, 92, 255),
    )
    embed.add_field(
        name="Getting started",
        value=(
            "**`/login`** - connect your maimai account (once, takes a minute)\n"
            "**`/refresh`** - read your scores again now; other commands reuse the saved copy while a quick check says nothing changed"
        ),
        inline=False,
    )
    embed.add_field(
        name="What to play",
        value=(
            "**`/analyze`** - your recommendation poster, ranked best first; `challenge` sets how bold, `level` holds it to a level, a constant or a range\n"
            "**`/plan`** - your route to the next thousand (or any target)\n"
            "**`/session`** - tonight's credits, each spent where it pays the most\n"
            "**`/new`** - charts you haven't played that fit your level, leaning into your weak spots if you like\n"
            "**`/random`** - a random chart, filtered by level or difficulty"
        ),
        inline=False,
    )
    embed.add_field(
        name="Your scores",
        value=(
            "**`/profile`** - how you play, and how well the model has predicted you; the Traits button shows what your own scores confirm\n"
            "**`/b50`** or **`/top`** - the 50 charts that make up your rating\n"
            "**`/chart`** - one chart: your score, the prediction, what each rank is worth, and what the chart asks of you; the Song button opens the whole song, Last play your newest run of it with its judgements\n"
            "**`/charts`** - browse by pattern (streams, hand swaps, slow rotations) or by level, with your scores beside each chart\n"
            "**`/dxscore`** - DX stars and the charts closest to the next one\n"
            "**`/recent`** - your last sessions, new bests marked; pick a play from the menu under it, or pass `play:1`, to see one in full with its judgements\n"
            "**`/progress`** - your rating over time, and when the next thousand lands at your pace\n"
            "**`/area`** - area travel: distance in each area, the next reward, and how many plays away it is"
        ),
        inline=False,
    )
    embed.add_field(
        name="With others",
        value=(
            "**`/compare`** - your scores against a player who opted in\n"
            "**`/leaderboard`** - opted-in players in this server\n"
            "**`/settings`** - defaults, a daily read that keeps your history complete, and who can see you\n"
            "**`/export`** - your scores as JSON or CSV · **`/delete-account`** - delete everything stored about you"
        ),
        inline=False,
    )
    site = get_public_base_url()
    embed.add_field(
        name="Server and more",
        value=(
            "**`/invite`** - add the bot to a server or your account · **`/ping`** - is maimai DX NET up, and when the next maintenance is\n"
            "**`/server`** - switches for this server (Manage Server)"
            + f"\nEverything here is also on the web: [{site.split('://', 1)[-1]}/me]({site}/me/), sign in with Discord"
        ),
        inline=False,
    )
    embed.add_field(
        name="How picks are chosen",
        value=(
            "Every chart is scored by the rating you'd **actually** gain once your "
            "best-50 is counted - a big jump on a chart outside your best-50 is worth "
            "nothing, so I don't suggest it. That's weighted by how likely you are to "
            "hit the target, read off your own accuracy curve, and by what you like playing.\n"
            "-# the numbers are a starting point. Knowing what a chart asks of you, and noticing what cost you on the last run, is the part that makes you better"
        ),
        inline=False,
    )
    embed.set_footer(text="The first command after a session reads your scores, which takes 20-40 seconds")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="login", description="Connect your maimai account to the bot")
@app_commands.describe(region="Which maimai region you play in (default International)")
@app_commands.choices(region=REGION_CHOICES)
async def login(interaction: discord.Interaction, region: Optional[app_commands.Choice[str]] = None):
    chosen = region.value if region else "intl"
    if chosen not in MAIMAI_BASE_URLS:
        chosen = "intl"
    await send_login_card(interaction, chosen)


@bot.tree.command(name="ping", description="Check that the bot is responding")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="Pong",
        description=f"Round trip to Discord: **{latency}ms**\n\nmaimai servers: {describe()}",
        color=discord.Color.green() if latency < 200 else discord.Color.orange(),
    )
    embed.set_footer(text="maintenance is 01:00-02:00 JST daily, 01:00-04:00 on Wednesdays")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="invite", description="Add Rasmai to your server or to your account, or open the web dashboard")
async def invite(interaction: discord.Interaction):
    site = get_public_base_url()
    embed = discord.Embed(title="Rasmai", color=discord.Color.from_rgb(255, 61, 143))
    if DISCORD_BOT_INVITE:
        embed.add_field(name="Add Rasmai", value=f"[Install the bot]({DISCORD_BOT_INVITE})\n-# add it to a server, or to your own account so the commands work in DMs and in every server you are in", inline=False)
    else:
        embed.add_field(name="Add Rasmai", value="No invite link is set up on this instance.", inline=False)
    embed.add_field(name="Your scores on the web", value=f"[{site.split('://', 1)[-1]}/me]({site}/me/) · sign in with Discord", inline=False)
    view = discord.ui.View()
    if DISCORD_BOT_INVITE:
        view.add_item(discord.ui.Button(label="Invite", url=DISCORD_BOT_INVITE))
    view.add_item(discord.ui.Button(label="Dashboard", url=f"{site}/me/"))
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="delete-account", description="Delete your maimai account and everything stored about it")
async def delete_account(interaction: discord.Interaction):
    account = get_connected_account(str(interaction.user.id))
    if not account:
        await interaction.response.send_message("There is no linked account to delete.", ephemeral=True)
        return
    await interaction.response.send_message(
        "Delete your maimai account? This removes the stored session, your profile, scores, play history, "
        "judgement pages, areas and settings. It cannot be undone.",
        view=DeleteAccountView(interaction.user.id), ephemeral=True,
    )
