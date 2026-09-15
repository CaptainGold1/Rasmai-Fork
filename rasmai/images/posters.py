import math
from html import escape
from typing import Any, Callable, Dict, List, Sequence

from rasmai.config import site_label
from rasmai.images.markup import render, render_each, styleimage, template

CoverFn = Callable[[str, str], str]

DIFFICULTY_STYLES = {
    "basic": ("BASIC", "#4bb85f"),
    "advanced": ("ADVANCED", "#e0a020"),
    "expert": ("EXPERT", "#e2455a"),
    "master": ("MASTER", "#a266e8"),
    "remaster": ("Re:MASTER", "#cbbbe8"),
    "utage": ("UTAGE", "#e2609a"),
}


def lvl(level: Any, constant: Any) -> str:
    """Level with its constant, escaped, for the image rows: `13+ · 13.8`.

    :param level: A displayed level such as ``"13"`` or ``"13+"``.
    :type level: Any
    :param constant: The chart's internal difficulty constant.
    :type constant: Any
    :rtype: str
    """
    try:
        value = float(constant or 0)
    except (TypeError, ValueError):
        value = 0.0
    return _esc(f"{level} · {value:.1f}" if value > 0 else str(level))


def tier(difficulty: str) -> tuple:
    return DIFFICULTY_STYLES.get(str(difficulty).strip().lower(), DIFFICULTY_STYLES["master"])


CSS = styleimage()


def _esc(text: Any) -> str:
    return escape(str(text or ""))


def _avatar(avatar_b64: str) -> str:
    if avatar_b64:
        return render("avatar", data=avatar_b64)
    return template("avatar-none")


def _page(eyebrow: str, name: str, avatar_b64: str, counters: Sequence[tuple], headline_value: str,
          headline_caption: str, body: str, foot_left: str, foot_right: str, body_class: str = "") -> str:
    return render(
        "page",
        css=CSS,
        body_class=body_class,
        avatar=_avatar(avatar_b64),
        eyebrow=_esc(eyebrow),
        name=_esc(name),
        counters=render_each("counter", [{"label": _esc(k), "value": _esc(v)} for k, v in counters]),
        headline_value=headline_value,
        headline_caption=_esc(headline_caption),
        body=body,
        foot_left=_esc(foot_left),
        foot_right=_esc(foot_right),
    )


def _plays(plays: int, unplayed: bool = False) -> str:
    if unplayed:
        return "never played"
    if plays <= 0:
        return "plays unknown"
    return f"{plays} play" if plays == 1 else f"{plays} plays"


# ---------------------------------------------------------------- /plan

def plan_poster_html(plan: Any, player_name: str, player_rating: int, avatar_b64: str,
                     cover_html: CoverFn, stretch: bool = False, date_text: str = "",
                     bolder_label: str = "", limit_label: str = "") -> str:
    steps = list(plan.steps)
    fill = min(100.0, 100.0 * plan.total / max(1, plan.needed))

    def rows(chunk: List[Any], start: int) -> str:
        return render_each("plan-row", [
            {
                "ink": tier(step.option.difficulty_type)[1],
                "row_class": "fresh" if step.option.is_unplayed else "",
                "flag": template("new-flag") if step.option.is_unplayed else "",
                "position": start + offset,
                "cover": cover_html(step.option.cover, "row-cover"),
                "title": _esc(step.option.title),
                "tier_label": tier(step.option.difficulty_type)[0],
                "level": lvl(step.option.level, step.option.constant),
                "plays": _plays(step.option.plays, step.option.is_unplayed),
                "expected": step.option.expected,
                "now": "new" if step.option.is_unplayed else f"{step.option.current_accuracy:.2f}",
                "target": step.option.target_accuracy,
                "current_rank": _esc(step.option.current_rank),
                "target_rank": _esc(step.option.target_rank),
                "odds": step.option.feasibility * 100,
                "gain": step.gain,
                "cumulative": step.cumulative,
            }
            for offset, step in enumerate(chunk)
        ])

    if steps:
        half = max(1, math.ceil(len(steps) / 2))
        columns = render("plan-columns", head=template("plan-head"),
                         left=rows(steps[:half], 1), right=rows(steps[half:], half + 1))
    else:
        columns = render("empty-note", message="No achievable steps yet - play a few more charts and try again.")

    body = render(
        "plan-body",
        bolder_note=render("plan-bolder", label=_esc(bolder_label), needed=plan.needed) if bolder_label else "",
        stretch_class=" stretch" if stretch else "",
        fill=fill,
        start_rating=player_rating,
        verdict=_esc(f"covers the full +{plan.needed}" if plan.reached
                     else f"+{plan.total} of +{plan.needed} · {plan.shortfall} short"),
        goal_rating=plan.goal_rating,
        step_count=len(steps),
        target_kind="stretch targets" if stretch else "grind targets, 25% odds or better",
        limit_note=f" &middot; {_esc(limit_label)} only" if limit_label else "",
        columns=columns,
    )
    counters = [
        ("Steps", str(len(steps))),
        ("By odds", f"~+{plan.expected_gain:.0f}"),
        ("Above usual", f"{plan.average_stretch:+.1f}%"),
    ]
    return _page(f"Road to {plan.goal_rating}", player_name, avatar_b64, counters,
                 f"+{plan.total}", f"of +{plan.needed} needed", body,
                 f"Rasmai · {site_label()} · maimai DX · best-50 aware", date_text)


# ---------------------------------------------------------------- /session

def session_poster_html(session: Any, player_name: str, player_rating: int, avatar_b64: str,
                        cover_html: CoverFn, date_text: str = "", target_kind: str = "", limit_label: str = "") -> str:
    plays = list(session.plays)

    def rows(chunk: List[Any], start: int) -> str:
        return render_each("plan-row", [
            {
                "ink": tier(play.option.difficulty_type)[1],
                "row_class": "fresh" if play.option.is_unplayed else "",
                "flag": (template("new-flag") if play.option.is_unplayed else "")
                        + (render("retry-flag", attempt=play.attempt) if play.attempt > 1 else ""),
                "position": start + offset,
                "cover": cover_html(play.option.cover, "row-cover"),
                "title": _esc(play.option.title),
                "tier_label": tier(play.option.difficulty_type)[0],
                "level": lvl(play.option.level, play.option.constant),
                "plays": _plays(play.option.plays, play.option.is_unplayed),
                "expected": play.option.expected,
                "now": "new" if play.option.is_unplayed else f"{play.option.current_accuracy:.2f}",
                "target": play.option.target_accuracy,
                "current_rank": _esc(play.option.current_rank),
                "target_rank": _esc(play.option.target_rank),
                "odds": play.option.feasibility * 100,
                "gain": play.gain,
                "cumulative": f"+{play.expected:.1f}",
            }
            for offset, play in enumerate(chunk)
        ])

    if plays:
        half = max(1, math.ceil(len(plays) / 2))
        columns = render("plan-columns", head=template("session-head"),
                         left=rows(plays[:half], 1), right=rows(plays[half:], half + 1))
    else:
        columns = render("empty-note", message="Nothing tonight moves your best-50 at these odds. Try bolder targets.")
    body = render(
        "session-body", credits=session.credits, expected=session.expected_total, any_lands=session.any_lands * 100,
        limit_note=f" &middot; {_esc(limit_label)} only" if limit_label else "", target_kind=_esc(target_kind), columns=columns,
    )
    counters = [("Credits", str(session.credits)), ("Charts", str(session.distinct_charts)),
                ("Any lands", f"{session.any_lands * 100:.0f}%")]
    return _page("Tonight's session", player_name, avatar_b64, counters, f"+{session.expected_total:.0f}",
                 "rating expected from these credits", body, f"Rasmai · {site_label()} · maimai DX · best-50 aware", date_text)


# ---------------------------------------------------------------- /new

def new_poster_html(picks: Sequence[Any], player_name: str, player_rating: int, avatar_b64: str,
                    cover_html: CoverFn, label: str, lower: float, upper: float, date_text: str = "") -> str:
    cards = render_each("new-card", [
        {
            "ink": tier(pick.difficulty)[1],
            "cover": cover_html(pick.cover, "card-cover"),
            "position": position,
            "tier_label": tier(pick.difficulty)[0],
            "level": lvl(pick.level, pick.constant),
            "chart_type": _esc(pick.chart_type.upper()),
            "title": _esc(pick.title),
            "expected": pick.expected_accuracy,
            "expected_rank": _esc(pick.expected_rank),
            "odds_of_s": pick.odds_of_s * 100,
            "worth": render("new-worth", gain=pick.rating_gain) if pick.rating_gain > 0 else template("new-worth-none"),
            "genre": _esc(pick.genre),
        }
        for position, pick in enumerate(picks, 1)
    ])
    if not cards:
        cards = render("empty-note", message="Nothing unplayed in range at this difficulty.")
    body = render("new-body", lower=lower, upper=upper, cards=cards)
    counters = [("Rating", str(player_rating)), ("Range", f"{lower:.1f}–{upper:.1f}")]
    return _page(f"New charts · {label}", player_name, avatar_b64, counters,
                 str(len(picks)), "charts to try", body,
                 f"Rasmai · {site_label()} · maimai DX · estimates are for a first pass", date_text)


# ---------------------------------------------------------------- /profile

def _skill_chart_svg(profile: Any, songs: Sequence[Any], width: int = 1480, height: int = 700) -> str:
    """The scatter of every score against chart constant, with the fitted curve over it.

    Drawn rather than templated: every coordinate here is computed.

    :param profile: How the player plays, as measured from their scores.
    :type profile: Any
    :param songs: The player's scored charts.
    :type songs: Sequence[Any]
    :param width: How wide to draw, in pixels.
    :type width: int
    :param height: How tall to draw, in pixels.
    :type height: int
    :rtype: str
    """
    pts = [
        (float(s.difficulty), float(s.accuracy), str(getattr(s, "difficulty_type", "")).lower())
        for s in songs
        if float(getattr(s, "difficulty", 0) or 0) > 0 and float(getattr(s, "accuracy", 0) or 0) > 0
        and str(getattr(s, "difficulty_type", "")).lower() != "utage"
    ]
    if not pts:
        return ""
    ml, mr, mt, mb = 96, 30, 24, 46
    x0, x1 = math.floor(min(p[0] for p in pts)), math.ceil(max(p[0] for p in pts)) + 0.5
    y0, y1 = 85.0, 101.0
    pw, ph = width - ml - mr, height - mt - mb

    def X(c: float) -> float:
        return ml + (c - x0) / (x1 - x0) * pw

    def Y(a: float) -> float:
        return mt + (y1 - min(max(a, y0), y1)) / (y1 - y0) * ph

    parts: List[str] = []
    for a, name in ((97.0, "S"), (98.0, "S+"), (99.0, "SS"), (99.5, "SS+"), (100.0, "SSS"), (100.5, "SSS+")):
        y = Y(a)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{width - mr}" y2="{y:.1f}" stroke="#2b2924" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Cascadia Mono,Consolas,monospace" font-size="12" fill="#9b968a">{a:g} {name}</text>')
    for a in (90.0, 95.0):
        y = Y(a)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{width - mr}" y2="{y:.1f}" stroke="#1f1d18" stroke-width="1"/>')
        parts.append(f'<text x="{ml - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Cascadia Mono,Consolas,monospace" font-size="12" fill="#5f5b52">{a:g}</text>')
    c = math.ceil(x0)
    while c <= x1:
        x = X(c)
        parts.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{height - mb}" stroke="#1f1d18" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{height - mb + 22}" text-anchor="middle" font-family="Cascadia Mono,Consolas,monospace" font-size="12" fill="#9b968a">{c}</text>')
        c += 1

    sigma = max(0.3, float(getattr(profile, "consistency", 0.8)))
    band_top, band_bot, line = [], [], []
    steps = 60
    for i in range(steps + 1):
        cx = x0 + (x1 - x0) * i / steps
        e = profile.expected_accuracy(cx)
        line.append(f"{X(cx):.1f},{Y(e):.1f}")
        band_top.append(f"{X(cx):.1f},{Y(min(101.0, e + sigma)):.1f}")
        band_bot.append(f"{X(cx):.1f},{Y(e - sigma):.1f}")
    parts.append(f'<polygon points="{" ".join(band_top + band_bot[::-1])}" fill="#f0c04a" opacity="0.10"/>')
    parts.append(f'<polyline points="{" ".join(line)}" fill="none" stroke="#f0c04a" stroke-width="3"/>')

    for cst, acc, dtype in pts:
        _l, ink = tier(dtype)
        op = 0.85 if acc >= y0 else 0.35
        parts.append(f'<circle cx="{X(cst):.1f}" cy="{Y(acc):.1f}" r="5" fill="{ink}" opacity="{op}"/>')

    for value, name in ((float(getattr(profile, "comfort_constant", 0)), "comfort"), (float(getattr(profile, "reach_constant", 0)), "reach")):
        if x0 <= value <= x1:
            x = X(value)
            parts.append(f'<line x1="{x:.1f}" y1="{mt}" x2="{x:.1f}" y2="{height - mb}" stroke="#5cd3e8" stroke-width="1.5" stroke-dasharray="6 6"/>')
            parts.append(f'<text x="{x + 6:.1f}" y="{mt + 16}" font-family="Cascadia Mono,Consolas,monospace" font-size="12" fill="#5cd3e8">{name} {value:.1f}</text>')

    return f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">{"".join(parts)}</svg>'


def profile_poster_html(summary: Dict[str, Any], profile: Any, songs: Sequence[Any], player_name: str,
                        player_rating: int, avatar_b64: str, recent_count: int, date_text: str = "") -> str:
    p = summary.get("profile", {})
    b = summary.get("best50", {})

    def bars(bias: Dict[str, float], limit: int = 7) -> str:
        items = sorted(bias.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        if not items:
            return template("bar-empty")
        return render_each("bar-row", [
            {
                "label": _esc(key),
                "negative": "" if (value - 1.0) >= 0 else "neg",
                "width": min(100.0, abs((value - 1.0) * 100) * 2.5),
                "percent": (value - 1.0) * 100,
            }
            for key, value in items
        ])

    def trait_bars(traits: Sequence[Dict[str, Any]], limit: int = 8) -> str:
        if not traits:
            return render("bar-empty").replace("not enough recent plays", "no trait stands out yet")
        ordered = sorted(traits, key=lambda t: abs(float(t["offset"])), reverse=True)[:limit]
        ordered.sort(key=lambda t: float(t["offset"]))
        return render_each("trait-row", [
            {
                "label": _esc(t["label"]),
                "negative": "neg" if float(t["offset"]) < 0 else "",
                "width": min(100.0, abs(float(t["offset"])) * 30),
                "value": float(t["offset"]),
            }
            for t in ordered
        ])

    calibration = p.get("calibration") or {}
    model_tile = ""
    if calibration.get("plays", 0) >= 15:
        model_tile = render(
            "profile-model", plays=calibration.get("plays", 0), coverage=float(calibration.get("coverage", 0)) * 100,
            predicted=float(calibration.get("newBestPredicted") or 0) * 100, actual=float(calibration.get("newBestActual") or 0) * 100,
            scale=float(calibration.get("sigmaScale", 1.0)), shift=float(calibration.get("shift", 0.0)),
        )

    habits = p.get("habits") or {}
    age = habits.get("age") or {}
    habits_tile = ""
    if age.get("plays", 0) >= 10:
        rerates, notes = habits.get("rerates") or {}, habits.get("notes") or {}
        habits_tile = render(
            "profile-habits",
            age=float(age.get("medianYears", 0)), fresh=float(age.get("freshShare", 0)) * 100,
            rerates=(f" &middot; re-rating has moved your best 50 by <b>{int(rerates['rating']):+d}</b> "
                     f"across {int(rerates['charts'])} charts" if rerates.get("charts") else ""),
            notes=(f" &middot; {int(notes['notes']):,} notes hit" if notes.get("notes") else ""),
        )

    open_slots = int(b.get("newSlotsOpen", 0)) + int(b.get("oldSlotsOpen", 0))
    legend = render_each("legend-swatch", [
        {"ink": ink, "label": label} for label, ink in
        (DIFFICULTY_STYLES["expert"], DIFFICULTY_STYLES["master"], DIFFICULTY_STYLES["remaster"], DIFFICULTY_STYLES["advanced"])
    ])
    body = render(
        "profile-body",
        chart=_skill_chart_svg(profile, songs),
        consistency=p.get("consistency", 0),
        legend=legend,
        style=_esc(str(p.get("style", "unknown")).title()),
        chart_type=_esc(str(p.get("favouriteChartType", "?")).upper()),
        genre=_esc(p.get("favouriteGenre", "?")),
        fc_rate=p.get("fcRate", 0) * 100,
        ap_rate=p.get("apRate", 0) * 100,
        dx_rate=p.get("dxScoreRate", 0) * 100,
        comfort=p.get("comfortConstant", 0),
        reach=p.get("reachConstant", 0),
        hardest_s=p.get("hardestS", 0),
        ceiling=p.get("playedCeiling", 0),
        at13=p.get("expectedAt13", 0),
        at14=p.get("expectedAt14", 0),
        recent_count=recent_count,
        active_days=p.get("activeDays", 0),
        play_counts_known=p.get("playCountsKnown", 0),
        best50=b.get("total", 0),
        new_total=b.get("newTotal", 0),
        old_total=b.get("oldTotal", 0),
        new_cutoff=b.get("newCutoff", 0),
        old_cutoff=b.get("oldCutoff", 0),
        slots=render("profile-slots", slots=open_slots) if open_slots else "",
        genre_bars=bars(getattr(profile, "genre_bias", {}) or {}),
        trait_bars=trait_bars(p.get("traits") or []),
        model_tile=model_tile,
        habits_tile=habits_tile,
    )
    counters = [
        ("FC", f"{p.get('fcRate', 0) * 100:.0f}%"),
        ("AP", f"{p.get('apRate', 0) * 100:.0f}%"),
        ("DX score", f"{p.get('dxScoreRate', 0) * 100:.0f}%"),
    ]
    return _page("Play profile", player_name, avatar_b64, counters, str(player_rating), "rating", body,
                 f"Rasmai · {site_label()} · maimai DX · best-50 aware", date_text)
