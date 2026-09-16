from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional
import asyncio
import csv
import io
import json
import logging

import discord

from rasmai.engine.analysis import rank_for
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.ui.formatting import TIER_SHORT, _fit, level_text, message_files, chart_link
from rasmai.bot.state.prefs import get_prefs
from rasmai.bot.state.snapshots import compact_snapshot, snapshot_charts
from rasmai.bot.core import try_render
from rasmai.images.cards import compare_image_html, leaderboard_image_html
from rasmai.images.render import cover_html_factory
from rasmai.storage.db import accounts_with_setting, get_connected_account, load_play_history, load_rating_history, quiet_read_status
from rasmai.bot.tasks.history_watch import describe_quiet_read
from rasmai.util import _json_safe

logger = logging.getLogger(__name__)


def _level_bucket(level: str) -> str:
    return str(level or "").strip()


# ---------------------------------------------------------------- /compare

async def build_compare(cached: CachedAnalysis, other: discord.abc.User) -> Tuple[discord.Embed, List[discord.File], None]:
    a = cached.analyzer
    me = a.player
    files, avatar_url = message_files(me, None, "")
    other_id = str(other.id)
    embed = discord.Embed(title="Compare", color=discord.Color.from_rgb(162, 102, 232))
    embed.set_author(name=me.name, icon_url=avatar_url)
    if other_id == cached.user_id:
        embed.description = "Pick someone else - comparing you with yourself is a draw."
        return embed, files, None
    if not get_prefs(other_id).get("compare"):
        embed.description = (f"{other.mention} hasn't opened their scores for comparison. "
                             "They can switch it on with `/settings compare:True`.")
        return embed, files, None
    account = get_connected_account(other_id)
    theirs = snapshot_charts((account or {}).get("latestSnapshot"))
    snapshot = (account or {}).get("latestSnapshot") or {}
    if not theirs:
        embed.description = f"{other.mention} hasn't run `/analyze` since linking, so there's nothing to compare yet."
        return embed, files, None

    mine_rows = snapshot_charts(compact_snapshot(a))
    mine = {(r["name"].casefold(), r["chart_type"], r["difficulty_type"]): r for r in mine_rows}
    them = {(r["name"].casefold(), r["chart_type"], r["difficulty_type"]): r for r in theirs}
    common = sorted(set(mine) & set(them))
    my_leads = [(mine[k]["accuracy"] - them[k]["accuracy"], k) for k in common if mine[k]["accuracy"] > them[k]["accuracy"]]
    their_leads = [(them[k]["accuracy"] - mine[k]["accuracy"], k) for k in common if them[k]["accuracy"] > mine[k]["accuracy"]]
    their_name = snapshot.get("name") or other.display_name
    their_rating = int(snapshot.get("rating") or 0)

    embed.title = f"{me.name} vs {their_name}"
    embed.description = (f"**{me.rating}** vs **{their_rating}** rating · "
                         f"best-50 **{a.best50.total if a.best50 else 0}** vs **{snapshot.get('best50', 0)}**\n"
                         f"**{len(common)}** charts in common · you lead **{len(my_leads)}**, they lead **{len(their_leads)}**, "
                         f"{len(common) - len(my_leads) - len(their_leads)} tied")

    def side(rows: Dict[Any, Dict[str, Any]], name: str, rating: int, total_plays: int) -> str:
        played = len(rows)
        sss = sum(1 for r in rows.values() if r["accuracy"] >= 100.0)
        ss = sum(1 for r in rows.values() if 99.0 <= r["accuracy"] < 100.0)
        fc = sum(1 for r in rows.values() if str(r.get("fc_status") or "").upper() not in ("", "NONE"))
        hardest = max((float(r.get("constant") or 0) for r in rows.values() if r["accuracy"] >= 97.0), default=0.0)
        return (f"rating **{rating}**\n{played} charts · {total_plays or '?'} plays\n"
                f"{sss} SSS · {ss} SS · {fc} FC\nhardest S: **{hardest:.1f}**")

    embed.add_field(name=me.name, value=side(mine, me.name, int(me.rating or 0), int(me.total_play_count or 0)), inline=True)
    embed.add_field(name=their_name, value=side(them, their_name, their_rating, int(snapshot.get("totalPlayCount") or 0)), inline=True)

    levels = ["12", "12+", "13", "13+", "14", "14+"]
    level_lines = []
    for level in levels:
        keys = [k for k in common if _level_bucket(mine[k]["level"]) == level]
        if len(keys) < 3:
            continue
        my_avg = sum(mine[k]["accuracy"] for k in keys) / len(keys)
        their_avg = sum(them[k]["accuracy"] for k in keys) / len(keys)
        arrow = "▲" if my_avg > their_avg else ("▼" if my_avg < their_avg else "=")
        level_lines.append(f"`{level:>3}` {my_avg:.2f} vs {their_avg:.2f} {arrow} · {len(keys)} charts")
    if level_lines:
        embed.add_field(name="Average on shared charts", value="\n".join(level_lines), inline=False)

    def gaps(items: List[Tuple[float, Any]], source: Dict[Any, Dict[str, Any]]) -> str:
        items.sort(reverse=True)
        return _fit([
            f"{chart_link(source[k]['name'], k[1], k[2], source[k].get('cover', ''))} {TIER_SHORT.get(k[2], '')} {level_text(source[k]['level'], source[k].get('constant'))} · +{gap:.2f}"
            for gap, k in items[:5]
        ]) if items else "-"

    embed.add_field(name="Your biggest leads", value=gaps(my_leads, mine), inline=True)
    embed.add_field(name="Their biggest leads", value=gaps(their_leads, them), inline=True)

    def stats(rows: Dict[Any, Dict[str, Any]], name: str, rating: int, best50: int, plays: int, leads: int) -> Dict[str, Any]:
        return {
            "name": name, "rating": rating, "best50": best50, "charts": len(rows), "plays": plays, "leads": leads,
            "sss": sum(1 for r in rows.values() if r["accuracy"] >= 100.0),
            "ss": sum(1 for r in rows.values() if 99.0 <= r["accuracy"] < 100.0),
            "fc": sum(1 for r in rows.values() if str(r.get("fc_status") or "").upper() not in ("", "NONE")),
            "hardest": max((float(r.get("constant") or 0) for r in rows.values() if r["accuracy"] >= 97.0), default=0.0),
        }

    def lead_rows(items: List[Tuple[float, Any]], source: Dict[Any, Dict[str, Any]], other: Dict[Any, Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for gap, k in sorted(items, reverse=True)[:6]:
            ref = a.chart_index.get(k)
            out.append({"title": source[k]["name"], "difficulty": k[2], "level": source[k]["level"], "gap": gap,
                        "mine": mine[k]["accuracy"], "theirs": them[k]["accuracy"], "cover": ref.cover if ref else ""})
        return out

    level_stats = []
    for level in levels:
        keys = [k for k in common if _level_bucket(mine[k]["level"]) == level]
        if len(keys) >= 3:
            level_stats.append((level, sum(mine[k]["accuracy"] for k in keys) / len(keys), sum(them[k]["accuracy"] for k in keys) / len(keys), len(keys)))
    image_key = f"compare:{other_id}:{snapshot.get('recordedAt', '')}"
    if image_key not in cached.images:
        cached.images[image_key] = await try_render(compare_image_html(
            stats(mine, me.name, int(me.rating or 0), a.best50.total if a.best50 else 0, int(me.total_play_count or 0), len(my_leads)),
            stats(them, their_name, their_rating, int(snapshot.get("best50") or 0), int(snapshot.get("totalPlayCount") or 0), len(their_leads)),
            level_stats, lead_rows(my_leads, mine, them), lead_rows(their_leads, them, mine), len(common),
            cover_html_factory(a.jacket_path), me.avatar_base64, date_text=datetime.now().strftime("%d %B %Y"),
        ))
    files, avatar_url = message_files(me, cached.images[image_key], "rasmai-compare.png")
    embed.set_author(name=me.name, icon_url=avatar_url)
    try:
        recorded = datetime.fromisoformat(str(snapshot.get("recordedAt")))
        embed.timestamp = recorded if recorded.tzinfo else recorded.astimezone()
    except ValueError:
        pass
    embed.set_footer(text="their scores as of their last /analyze")
    return embed, files, None


# ---------------------------------------------------------------- /leaderboard

LEADERBOARD_PAGE = 20


async def build_leaderboard(guild: discord.Guild, owner_id: Optional[int] = None, page: int = 0
                            ) -> Tuple[discord.Embed, List[discord.File], Optional[discord.ui.View]]:
    embed = discord.Embed(title=f"Rating leaderboard · {guild.name}", color=discord.Color.from_rgb(240, 192, 74))
    accounts = accounts_with_setting("leaderboard")
    if not accounts:
        embed.description = "Nobody has opted in yet. `/settings leaderboard:True` puts you on the board."
        return embed, [], None
    by_id = {acc["userId"]: acc for acc in accounts}
    ids = list(by_id)
    members: List[discord.Member] = []
    for start in range(0, len(ids), 100):
        chunk = [int(i) for i in ids[start:start + 100]]
        try:
            members.extend(await guild.query_members(user_ids=chunk, limit=100))
        except (discord.HTTPException, asyncio.TimeoutError) as error:
            logger.warning(f"query_members failed: {error}")
    rows = []
    for member in members:
        acc = by_id.get(str(member.id))
        profile = (acc or {}).get("officialProfile") or {}
        rating = int(profile.get("rating") or 0)
        if rating <= 0:
            continue
        rows.append((rating, member.display_name, profile.get("name") or "", acc.get("region", "intl")))
    if not rows:
        embed.description = "Nobody in this server has opted in yet. `/settings leaderboard:True` puts you on the board."
        return embed, [], None
    rows.sort(key=lambda r: -r[0])
    pages = max(1, (len(rows) + LEADERBOARD_PAGE - 1) // LEADERBOARD_PAGE)
    page = max(0, min(page, pages - 1))
    start = page * LEADERBOARD_PAGE
    lines = []
    for position, (rating, display, maimai_name, region) in enumerate(rows[start:start + LEADERBOARD_PAGE], start + 1):
        tag = f"`{position:>2}`"
        who = f"**{display}**" + (f" · {maimai_name}" if maimai_name and maimai_name != display else "")
        lines.append(f"{tag} {who} · **{rating}**" + (f" ({region.upper()})" if region != "intl" else ""))
    embed.description = "\n".join(lines)
    embed.set_footer(text=(f"page {page + 1}/{pages} · " if pages > 1 else "") + f"{len(rows)} opted-in players in this server · ratings from each player's last /analyze")
    shot = await try_render(leaderboard_image_html(guild.name, rows[:20], date_text=datetime.now().strftime("%d %B %Y")))
    files = [discord.File(io.BytesIO(shot), filename="rasmai-leaderboard.png")] if shot else []
    from rasmai.bot.ui.views import PagedView

    async def draw(wanted: int):
        return await build_leaderboard(guild, owner_id, wanted)

    return embed, files, PagedView(owner_id, page, pages, draw) if owner_id is not None and pages > 1 else None


# ---------------------------------------------------------------- /settings

LAYOUT_LABELS = {"both": "Image + text", "image": "Image only", "embed": "Text only"}
CHALLENGE_LABELS = {"easy": "Easier", "balanced": "Balanced", "hard": "Challenging", "extreme": "Long shots"}
NEW_LABELS = {"any": "Expert and up", "master": "Master", "remaster": "Re:Master", "expert": "Expert", "advanced": "Advanced", "basic": "Basic"}


def settings_embed(prefs: Dict[str, Any], changed: bool, user_id: str = "") -> discord.Embed:
    embed = discord.Embed(title="Your settings" + (" · saved" if changed else ""), color=discord.Color.blurple())
    embed.add_field(name="Default layout", value=f"**{LAYOUT_LABELS.get(prefs['layout'], prefs['layout'])}**\n-# what `/analyze`, `/plan`, `/new` and `/profile` send unless you pick `output`", inline=False)
    embed.add_field(name="Default targets", value=f"**{CHALLENGE_LABELS.get(prefs.get('challenge', 'balanced'), 'Balanced')}**\n-# easier: about a coin flip per target · balanced: one in four · challenging: one in six · long shots: one in ten", inline=False)
    embed.add_field(name="Default /new difficulty", value=f"**{NEW_LABELS.get(prefs['new_difficulty'], prefs['new_difficulty'])}**", inline=False)
    embed.add_field(name="Open to /compare", value=("**On** - anyone can compare their scores with yours" if prefs["compare"] else "**Off** - nobody can compare against you"), inline=True)
    embed.add_field(name="Server leaderboards", value=("**On** - you appear on `/leaderboard` in servers you share with the bot" if prefs["leaderboard"] else "**Off** - you never appear on leaderboards"), inline=True)
    if prefs.get("history"):
        status = describe_quiet_read(quiet_read_status(user_id)) if user_id else ""
        embed.add_field(name="Daily history read",
                        value=f"**On** - the bot reads your recent plays once a day so the per-chart history and the model check stay complete\n-# {status}",
                        inline=False)
    else:
        embed.add_field(name="Daily history read",
                        value="**Off** - plays are recorded only when you run a command; maimai shows the last fifty, so busy weeks lose some",
                        inline=False)
    if prefs.get("notify"):
        embed.add_field(name="Daily note", value="**On** - a DM when the daily read finds new bests or a moved rating" +
                        ("" if prefs.get("history") else "\n-# needs the daily history read on to have anything to say"), inline=False)
    else:
        embed.add_field(name="Daily note", value="**Off** - the daily read stays silent", inline=False)
    embed.set_footer(text="change any of these with the command's options · the social ones are off by default")
    return embed


# ---------------------------------------------------------------- /export

def build_export(cached: CachedAnalysis, fmt: str) -> discord.File:
    a = cached.analyzer
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["title", "chart_type", "difficulty", "level", "constant", "achievement", "rank", "rating",
                         "fc", "fs", "dx_score", "current_version", "plays"])
        for row in snapshot_charts(compact_snapshot(a)):
            key = (row["name"].casefold(), row["chart_type"], row["difficulty_type"])
            plays = a.play_counts.get(key, 0)
            writer.writerow([row["name"], row["chart_type"], row["difficulty_type"], row["level"], row["constant"],
                             row["accuracy"], rank_for(float(row["accuracy"])), row["rating"], row["fc_status"], row["fs_status"],
                             row["dx_score"], int(bool(row["is_new"])), plays if plays > 0 else ""])
        data = buffer.getvalue().encode("utf-8-sig")
        return discord.File(io.BytesIO(data), filename=f"rasmai-scores-{stamp}.csv")
    payload = compact_snapshot(a)
    payload["playCounts"] = {"|".join(k): v for k, v in a.play_counts.items() if v > 0}
    payload["recentPlays"] = list(a.recent_songs or [])
    payload["playHistory"] = load_play_history(cached.user_id)
    payload["ratingHistory"] = load_rating_history(cached.user_id)
    data = json.dumps(_json_safe(payload), ensure_ascii=False, indent=2).encode("utf-8")
    return discord.File(io.BytesIO(data), filename=f"rasmai-scores-{stamp}.json")
