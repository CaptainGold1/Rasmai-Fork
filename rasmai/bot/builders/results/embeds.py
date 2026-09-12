from datetime import datetime
from typing import List, Optional, Tuple
import asyncio
import discord

from rasmai.engine import analysis, insights
from rasmai.images import posters
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.core import try_render
from rasmai.bot.ui.formatting import (
    stamp,
    chart_link, TIER_NAMES, TIER_SHORT, _fit, add_profile_fields, add_row_break, format_picks_markdown,
    format_plan_markdown, format_plan_verdict, format_try_markdown, level_text, message_files, progress_bar,
)
from rasmai.images.render import cover_html_factory, generate_poster_html
from rasmai.storage.db import load_judgements, since_last_look
from rasmai.engine.judgements import judgement_profile
from rasmai.bot.builders.traits import judgement_summary


async def _image(cached: CachedAnalysis, key: str, html_factory) -> Optional[bytes]:
    if key not in cached.images:
        cached.images[key] = await try_render(await asyncio.to_thread(html_factory))
    return cached.images[key]


def _today() -> str:
    return datetime.now().strftime("%d %B %Y")


def since_last_line(cached: CachedAnalysis) -> str:
    """One small line under the headline: rating change, plays and new bests since the previous read that differed.

    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :rtype: str
    """
    player = cached.analyzer.player
    try:
        moved = since_last_look(cached.user_id, int(player.rating or 0), int(player.total_play_count or 0))
    except Exception:
        return ""
    if not moved or (not moved["plays"] and not moved["ratingDelta"]):
        return ""
    try:
        when = stamp(datetime.fromisoformat(moved["since"]), "R")
    except ValueError:
        when = "last time"
    bits = [f"rating {moved['ratingDelta']:+}" if moved["ratingDelta"] else "rating unchanged"]
    if moved["plays"]:
        bits.append(f"{moved['plays']} play{'s' if moved['plays'] != 1 else ''}")
    if moved["newBests"]:
        bits.append(f"{moved['newBests']} new best{'s' if moved['newBests'] != 1 else ''}")
    return f"\n-# since {when}: " + " · ".join(bits)


async def build_analyze(cached: CachedAnalysis, challenge: str = "balanced", level: Optional[str] = None) -> Tuple[discord.Embed, List[discord.File]]:
    a = cached.analyzer
    player = a.player
    scope = analysis.describe_span(level) if level else ""
    recs, summary = cached.analysis_for(challenge, level if scope else None)
    summary = summary or {}
    plan = cached.plan_for(None, False, challenge)
    shot = None
    if recs:
        shot = await _image(cached, f"analyze:{challenge}:{scope}", lambda: generate_poster_html(
            recs, player.name, player.rating, player.fc, player.fc_plus, player.clears,
            player.avatar_base64, a.jacket_path, plan=plan, image_gain=summary.get("reachableGain"), scope=scope,
        ))
    files, avatar_url = message_files(player, shot, "rasmai.png")

    if not recs:
        embed = discord.Embed(
            title=f"Rating {player.rating}",
            description=(f"Nothing at **{scope}** moves your best-50 at the {analysis.challenge_for(challenge).label.lower()} level. "
                         "Try a bolder level, a wider range, or drop the filter." if scope else
                         "I couldn't find anything worth recommending yet. That usually means very few scores on the account - play a few more charts and try again."),
            color=discord.Color.from_rgb(240, 192, 74),
        )
        embed.set_author(name=player.name, icon_url=avatar_url)
        return embed, files

    movers = summary.get("ratingMoves", 0)
    reachable = summary.get("reachableGain", 0)
    embed = discord.Embed(
        title=f"Rating {player.rating}",
        description=(
            f"**+{reachable}** within reach today across **{movers}** charts"
            + (f" · **+{plan.total}** on the road to **{plan.goal_rating}**" if plan and plan.steps else "")
        ),
        color=discord.Color.from_rgb(240, 192, 74),
    )
    embed.set_author(name=player.name, icon_url=avatar_url)
    if summary.get("fallbackFrom"):
        embed.description += "\n-# no easier step moves your best-50 right now, so these are the balanced targets"
    embed.description += since_last_line(cached)
    embed.add_field(name=f"Play these now · {analysis.challenge_for(challenge).label.lower()}" + (f" · {scope}" if scope else ""),
                    value=format_picks_markdown(recs, limit=6), inline=True)
    to_try = format_try_markdown(recs, limit=4) if any(r.category == "try" for r in recs) else ""
    if to_try:
        embed.add_field(name="Worth a first run", value=to_try, inline=True)
    if plan and plan.steps:
        embed.add_field(name=f"Road to {plan.goal_rating}",
                        value=_fit([format_plan_verdict(plan), format_plan_markdown(plan, limit=6)]), inline=True)
    add_row_break(embed)
    add_profile_fields(embed, summary)
    footer = f"{len(a.songs)} charts · {len(a.recent_songs)} recent plays"
    if shot is None:
        footer += " · poster unavailable right now"
    embed.set_footer(text=footer)
    return embed, files


PLAN_PAGE = 12


async def build_plan(cached: CachedAnalysis, target: Optional[int], stretch: bool, page: int,
                     challenge: str = "balanced", difficulty: Optional[str] = None,
                     min_level: Optional[str] = None) -> Tuple[discord.Embed, List[discord.File], int]:
    a = cached.analyzer
    player = a.player
    plan = cached.plan_for(target, stretch, challenge, difficulty, min_level)
    limits = [TIER_NAMES.get(difficulty, str(difficulty).title())] if difficulty else []
    if min_level:
        limits.append(f"level {min_level} and up")
    limit_label = " · ".join(limits)
    # a route that falls short is worth little on its own, so name the bolder level that covers it
    bolder = "" if plan.reached else (await asyncio.to_thread(cached.bolder_level, target, stretch, challenge, difficulty, min_level) or "")
    bolder_label = analysis.challenge_for(bolder).label if bolder else ""
    steps = plan.steps
    pages = max(1, (len(steps) + PLAN_PAGE - 1) // PLAN_PAGE)
    page = max(0, min(page, pages - 1))
    shot = await _image(cached, f"plan:{target}:{stretch}:{challenge}:{difficulty or ''}:{min_level or ''}",
                        lambda: posters.plan_poster_html(
                            plan, player.name, cached.start_rating, player.avatar_base64,
                            cover_html_factory(a.jacket_path), stretch=stretch, date_text=_today(),
                            bolder_label=bolder_label, limit_label=limit_label,
                        ))
    files, avatar_url = message_files(player, shot, "rasmai-route.png")

    bar = progress_bar(plan.total, plan.needed)
    pct = 100 if plan.reached else (100 * plan.total // max(1, plan.needed))
    embed = discord.Embed(
        title=f"Road to {plan.goal_rating}",
        description=(
            f"`{bar}` **{pct}%**\n"
            f"**+{plan.total}** of **+{plan.needed}** across **{len(steps)}** charts"
            + ("" if plan.reached else f" · **{plan.shortfall}** short")
            + (f"\n-# only **{limit_label}**" if limit_label else "")
            + f"\n-# {'stretch targets' if stretch else 'grind targets, 25% odds or better'} · "
            f"about **{plan.average_stretch:+.1f}%** above your usual · worth ~+{plan.expected_gain:.0f} by odds"
        ),
        color=discord.Color.from_rgb(240, 192, 74),
    )
    embed.set_author(name=player.name, icon_url=avatar_url)
    if steps:
        start = page * PLAN_PAGE + 1
        embed.add_field(name=f"Steps {start}-{min(start + 5, len(steps))}", value=format_plan_markdown(plan, limit=6, start=start), inline=True)
        if len(steps) >= start + 6:
            embed.add_field(name=f"Steps {start + 6}-{min(start + 11, len(steps))}", value=format_plan_markdown(plan, limit=6, start=start + 6), inline=True)
    elif limit_label:
        embed.add_field(name="Nothing on the route yet",
                        value=f"No **{limit_label}** chart moves your best-50 at this level. Widen the filter or pick bolder targets.",
                        inline=False)
    else:
        embed.add_field(name="Nothing on the route yet", value="Play a few more charts and try again.", inline=False)
    if getattr(plan, "fallback_from", None):
        embed.description += "\n-# no easier step moves your best-50 right now, so this is the balanced route"
    if bolder_label:
        embed.description += (f"\n-# **{bolder_label}** targets cover the full **+{plan.needed}** on charts you"
                              f" already play · switch with the Targets menu below")
    credits = insights.plan_credits(plan) if steps else 0
    embed.set_footer(text=f"Σ = running total · page {page + 1}/{pages}" + (f" · about {credits} credits at these odds" if credits else "") + " · full route in the image")
    return embed, files, page


FOCUS_LABELS = {"weak": "where you lose points", "strong": "where you shine"}


NEW_PAGE = 12
NEW_PAGES = 3


async def build_new(cached: CachedAnalysis, difficulty: Optional[str], challenge: str = "balanced",
                    focus: Optional[str] = None, level: Optional[str] = None, page: int = 0) -> Tuple[discord.Embed, List[discord.File], int]:
    a = cached.analyzer
    player = a.player
    profile = a.play_profile
    mode = analysis.challenge_for(challenge)
    focus = focus if focus in FOCUS_LABELS else None
    level_span = analysis.level_range(level)
    level = str(level).strip() if level_span else None
    picks = analysis.recommend_unplayed(a.songs, profile, a.best50, a.chart_index, a.current_version,
                                        difficulty=difficulty, limit=NEW_PAGE * NEW_PAGES, challenge=mode.key, focus=focus, level=level)
    pages = max(1, (len(picks) + NEW_PAGE - 1) // NEW_PAGE)
    page = max(0, min(page, pages - 1))
    label = TIER_NAMES.get(difficulty, "EXPERT AND UP") if difficulty else "EXPERT AND UP"
    if level:
        label += f" · LV {level}"
    if focus:
        label += f" · {FOCUS_LABELS[focus].upper()}"
    lower, upper = level_span if level_span else analysis.unplayed_window(profile, mode.key)
    shot = None
    if picks:
        shot = await _image(cached, f"new:{difficulty}:{level or ''}:{challenge}:{focus or ''}", lambda: posters.new_poster_html(
            picks[:NEW_PAGE], player.name, cached.start_rating, player.avatar_base64,
            cover_html_factory(a.jacket_path), label, lower, upper, date_text=_today(),
        ))
    files, avatar_url = message_files(player, shot, "rasmai-new.png")

    embed = discord.Embed(
        title=f"New charts to try · {label}",
        description=(
            (f"Never played · level **{level}** ({lower:.1f} to {upper:.1f}) · first-pass estimates\n" if level else
             f"Never played · lv **{lower:.1f}** to **{upper:.1f}** · first pass should land AAA or better\n")
            + "-# charts that would enter your best-50 come first"
        ),
        color=discord.Color.from_rgb(33, 195, 227),
    )
    embed.set_author(name=player.name, icon_url=avatar_url)
    if focus:
        traits = [tr for tr in (profile.traits or []) if (float(tr["offset"]) < 0) == (focus == "weak")]
        if traits:
            named = ", ".join(f"{tr['label']} ({float(tr['offset']):+.1f})" for tr in traits[:3])
            embed.description += f"\n-# leaning into {FOCUS_LABELS[focus]}: {named}"
    if not picks and focus:
        embed.add_field(name="Nothing fits this focus", value="No unplayed chart in your range carries the traits you " + ("lose" if focus == "weak" else "gain") + " points on. Try without a focus, or another difficulty.", inline=False)
    elif not picks and level:
        embed.add_field(name="Nothing left", value=f"Every level {level} chart at this difficulty has been played already, or none exists. Try another level or difficulty.", inline=False)
    elif not picks:
        embed.add_field(name="Nothing in range", value="Every chart at this difficulty inside your range has been played already, or would land below AAA on a first pass. Try another difficulty, or ask for a level.", inline=False)
    else:
        lines: List[str] = []
        for index, pick in enumerate(picks[page * NEW_PAGE:(page + 1) * NEW_PAGE], page * NEW_PAGE + 1):
            short = TIER_SHORT.get(pick.difficulty, pick.difficulty[:3].upper())
            worth = f"**+{pick.rating_gain}**" if pick.rating_gain > 0 else "banks"
            lines.append(
                f"`{index:>2}` {chart_link(pick.title, pick.chart_type, pick.difficulty, pick.cover)} {short} {level_text(pick.level, pick.constant)} {pick.chart_type.upper()}\n"
                f"-# ~{pick.expected_accuracy:.1f}% {pick.expected_rank} · {worth} · {pick.odds_of_s * 100:.0f}% S"
            )
        embed.add_field(name="Start with these", value=_fit(lines[:6]), inline=True)
        if len(lines) > 6:
            embed.add_field(name="Then", value=_fit(lines[6:12]), inline=True)
    embed.set_footer(text=(f"page {page + 1}/{pages} · " if pages > 1 else "") + f"{len(a.songs)} charts known · first-pass estimates · the first twelve have jackets in the image")
    return embed, files, page


async def build_profile(cached: CachedAnalysis) -> Tuple[discord.Embed, List[discord.File]]:
    a = cached.analyzer
    player = a.player
    summary = a.analysis_summary or {}
    shot = await _image(cached, "profile", lambda: posters.profile_poster_html(
        summary, a.play_profile, a.songs, player.name, cached.start_rating, player.avatar_base64,
        len(a.recent_songs), date_text=_today(),
    ))
    files, avatar_url = message_files(player, shot, "rasmai-profile.png")
    embed = discord.Embed(title="Play Profile", color=discord.Color.blurple())
    embed.set_author(name=player.name, icon_url=avatar_url)
    add_profile_fields(embed, summary)
    add_row_break(embed)
    traits = (summary.get("profile") or {}).get("traits") or []
    weak = [tr for tr in traits if float(tr["offset"]) < 0][:4]
    strong = [tr for tr in reversed(traits) if float(tr["offset"]) > 0][:4]
    if weak:
        embed.add_field(name="Where you lose points",
                        value="\n".join(f"- **{float(tr['offset']):+.1f}** on {tr['label']} · {tr['count']} charts" for tr in weak)
                        + "\n-# against your own curve · `/new focus` picks charts to work on them",
                        inline=False)
    if strong:
        embed.add_field(name="Where you shine",
                        value="\n".join(f"- **{float(tr['offset']):+.1f}** on {tr['label']} · {tr['count']} charts" for tr in strong), inline=False)
    judged = judgement_profile(load_judgements(cached.user_id))
    if judged:
        embed.add_field(name="Judgements, measured", value=judgement_summary(judged), inline=False)
    calibration = (summary.get("profile") or {}).get("calibration") or {}
    if calibration.get("plays", 0) >= 15:
        predicted = calibration.get("newBestPredicted")
        actual = calibration.get("newBestActual")
        odds_line = (f" · new-best odds said **{predicted * 100:.0f}%**, **{actual * 100:.0f}%** happened"
                     if predicted is not None and actual is not None else "")
        embed.add_field(name="Model check",
                        value=f"**{calibration['coverage'] * 100:.0f}%** of your last {calibration['plays']} recorded plays landed inside the predicted range{odds_line}"
                              f"\n-# spread scaled ×{calibration['sigmaScale']:.2f}, centre shifted {calibration['shift']:+.2f}: the odds you see already include this",
                        inline=False)
    quick_wins = summary.get("quickWins") or []
    stretch = summary.get("stretchGoals") or []
    unplayed = summary.get("newChartsToTry") or []
    if quick_wins:
        embed.add_field(name="Quick wins", value="\n".join(f"- {t}" for t in quick_wins[:6]), inline=False)
    if stretch:
        embed.add_field(name="Stretch goals", value="\n".join(f"- {t}" for t in stretch[:6]), inline=False)
    if unplayed:
        embed.add_field(name="Never played, worth a shot", value="\n".join(f"- {t}" for t in unplayed[:6]), inline=False)
    if not (quick_wins or stretch or unplayed):
        embed.add_field(name="Nothing easy left", value="Every chart in your best-50 is already near your ceiling. Pushing your skill curve up is the only way forward.", inline=False)
    embed.set_footer(text=f"Based on {len(a.songs)} charts and {len(a.recent_songs)} recent plays · skill curve in the image")
    return embed, files


SESSION_DEFAULT = 6


def session_for(cached: CachedAnalysis, credits: int, challenge: str, difficulty: Optional[str]):
    key = f"session:{credits}:{challenge}:{difficulty or ''}"
    if key not in cached.extras:
        a = cached.analyzer
        cached.extras[key] = insights.build_session(
            a.songs, a.play_profile, a.best50, a.chart_index, a.current_version, cached.start_rating,
            credits=credits, challenge=challenge, difficulty=difficulty,
        )
    return cached.extras[key]


async def build_session(cached: CachedAnalysis, credits: int, challenge: str = "balanced",
                        difficulty: Optional[str] = None) -> Tuple[discord.Embed, List[discord.File]]:
    """Tonight's credits, each spent where it is worth the most rating.

    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :param credits: How many credits the session is worth.
    :type credits: int
    :param challenge: How bold the targets are: ``"easy"``, ``"balanced"``, ``"hard"`` or ``"extreme"``.
    :type challenge: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: Optional[str]
    :rtype: Tuple[discord.Embed, List[discord.File]]
    """
    a = cached.analyzer
    player = a.player
    credits = max(1, min(20, int(credits or SESSION_DEFAULT)))
    session = await asyncio.to_thread(session_for, cached, credits, challenge, difficulty)
    mode = analysis.challenge_for(challenge)
    limit_label = TIER_NAMES.get(difficulty, str(difficulty).title()) if difficulty else ""
    target_kind = f"{mode.label.lower()} targets"
    shot = None
    if session.plays:
        shot = await _image(cached, f"session:{credits}:{challenge}:{difficulty or ''}", lambda: posters.session_poster_html(
            session, player.name, cached.start_rating, player.avatar_base64, cover_html_factory(a.jacket_path),
            date_text=_today(), target_kind=target_kind, limit_label=limit_label,
        ))
    files, avatar_url = message_files(player, shot, "rasmai-session.png")
    embed = discord.Embed(
        title=f"Tonight's session · {credits} credit{'s' if credits != 1 else ''}",
        description=(
            f"Worth about **+{session.expected_total:.0f}** rating · **{session.any_lands * 100:.0f}%** chance at least one target lands"
            f" · {session.distinct_charts} chart{'s' if session.distinct_charts != 1 else ''}"
            + (f"\n-# only **{limit_label}**" if limit_label else "")
            + "\n-# each credit goes where gain × odds is highest · a repeat is worth it only if the first try missed · warm-ups first"
        ),
        color=discord.Color.from_rgb(255, 61, 143),
    )
    embed.set_author(name=player.name, icon_url=avatar_url)
    if not session.plays:
        embed.add_field(name="Nothing tonight", value="No chart moves your best-50 at these odds. Try bolder targets, or `/new` for fresh charts.", inline=False)
    else:
        lines: List[str] = []
        for index, play in enumerate(session.plays, 1):
            o = play.option
            short = TIER_SHORT.get(o.difficulty_type, o.difficulty_type[:3].upper())
            now = "new" if o.is_unplayed else f"{o.current_accuracy:.2f}"
            retry = f" · try {play.attempt}" if play.attempt > 1 else ""
            lines.append(
                f"`{index:>2}` {chart_link(o.title, o.chart_type, o.difficulty_type, o.cover)} {short} {level_text(o.level, o.constant)}{retry}\n"
                f"-# {now} → **{o.target_accuracy:.2f}** {o.target_rank} · {o.feasibility * 100:.0f}% · **+{play.gain}** if it lands · worth +{play.expected:.1f}"
            )
        embed.add_field(name="Play order", value=_fit(lines[:7]), inline=True)
        if len(lines) > 7:
            embed.add_field(name="Then", value=_fit(lines[7:14]), inline=True)
        if len(lines) > 14:
            embed.add_field(name="And", value=_fit(lines[14:20]), inline=True)
    embed.set_footer(text=f"{target_kind} · odds from your own history · full list in the image")
    return embed, files
