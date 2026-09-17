from typing import Dict, List, Optional, Any

from rasmai.bot.state.cache import CachedAnalysis
from rasmai.engine import analysis
from rasmai.scraping.mai_notes import english_label as mainotes_english
from rasmai.engine import insights
from rasmai.util import _json_safe


def picks_payload(cached: CachedAnalysis, challenge: str, level: str = "") -> Dict[str, Any]:
    a = cached.analyzer
    challenge = challenge if challenge in analysis.CHALLENGES else "balanced"
    level = str(level or "").strip()[:24]
    scope = analysis.describe_span(level) if level else ""
    recommendations, summary = cached.analysis_for(challenge, level if scope else None)
    plan = cached.plan_for(None, False, challenge)
    new_charts = analysis.recommend_unplayed(a.songs, a.play_profile, a.best50, a.chart_index, a.current_version,
                                             difficulty=None, limit=12, challenge=challenge, level=level if scope else None)
    span = analysis.constant_span(level) if scope else None
    low, high = span if span else analysis.unplayed_window(a.play_profile, challenge)
    return _json_safe({
        "challenge": challenge,
        "label": analysis.challenge_for(challenge).label,
        "level": level if scope else "", "scope": scope,
        "recommendations": recommendations[:60],
        "summary": summary,
        "plan": {
            "goal": plan.goal_rating, "start": plan.start_rating, "needed": plan.needed, "total": plan.total,
            "reached": plan.reached, "shortfall": plan.shortfall, "averageStretch": plan.average_stretch,
            "fallbackFrom": plan.fallback_from, "steps": plan.steps,
        },
        "newCharts": new_charts,
        "newWindow": [round(low, 1), round(high, 1)],
    })


def new_charts_payload(cached: CachedAnalysis, challenge: str, difficulty: str, level: str = "",
                       focus: str = "") -> Dict[str, Any]:
    a = cached.analyzer
    challenge = challenge if challenge in analysis.CHALLENGES else "balanced"
    wanted = difficulty if difficulty in ("basic", "advanced", "expert", "master", "remaster") else None
    span = analysis.level_range(level)
    wanted_level = level.strip() if span else None
    wanted_focus = focus if focus in ("weak", "strong") else None
    picks = analysis.recommend_unplayed(a.songs, a.play_profile, a.best50, a.chart_index, a.current_version,
                                        difficulty=wanted, limit=40, challenge=challenge, level=wanted_level,
                                        focus=wanted_focus)
    low, high = span if span else analysis.unplayed_window(a.play_profile, challenge)
    return _json_safe({
        "challenge": challenge, "label": analysis.challenge_for(challenge).label,
        "difficulty": wanted or "any", "level": wanted_level or "any", "focus": wanted_focus or "none",
        "window": [round(low, 1), round(high, 1)], "picks": picks,
        "traits": [{"label": mainotes_english(t["label"]), "offset": t["offset"], "count": t["count"]}
                   for t in (analysis.focus_traits(a.play_profile) if a.play_profile else [])
                   if (float(t["offset"]) < 0) == (wanted_focus == "weak")][:4] if wanted_focus else [],
    })


def trait_practice(cached: CachedAnalysis, traits: int = 3) -> List[Dict[str, Any]]:
    """For each pattern the player scores below their curve on, confirmed or leaning, a few charts in their band to practise it on.

    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :param traits: Most patterns to cover.
    :type traits: int
    :rtype: List[Dict[str, Any]]
    """
    a = cached.analyzer
    profile = a.play_profile
    if profile is None:
        return []
    axes = profile.trait_axes or []
    weak = sorted([t for t in insights.notable(axes) + insights.leaning(axes) if float(t["offset"]) < 0 and t["dimension"] == "pattern"],
                  key=lambda t: float(t["offset"]))
    out = []
    for trait in weak[:traits]:
        rows = insights.practice_for(trait, a.chart_index, profile, a.songs)
        if rows:
            out.append({"label": trait["label"], "english": mainotes_english(str(trait["label"])), "tag": str(trait["label"]).split(" (")[0],
                        "verified": bool(trait.get("verified")), "offset": trait["offset"], "count": trait["count"], "charts": rows})
    return _json_safe(out)


def _englished(profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Give every trait an English wording alongside the one it is stored under.

    A pattern is stored as ``"乱打 (streams)"`` so the community's own word stays its identity;
    the site shows the gloss, so the split happens here rather than in the browser.

    :param profile: The profile as the analysis summarised it.
    :type profile: Optional[Dict[str, Any]]
    Each trait also says whether it was read from the chart's own notes or written by an editor. The
    two can now carry the same wording - the editors' トリル is shown as "trills" and so is the
    measure taken off the notation - and a reader looking at two rows saying "trills" should be able
    to tell which is which.

    :returns: The same profile with ``english`` and ``read`` fields on each trait.
    :rtype: Optional[Dict[str, Any]]
    """
    if not profile:
        return profile
    from rasmai.engine.simai.features import DEMANDS
    measured = {label for _key, _dimension, label, _fixed in DEMANDS}
    out = dict(profile)
    for field in ("traits", "traitAxes"):
        rows = out.get(field) or []
        out[field] = [{**row, "english": mainotes_english(str(row.get("label") or "")),
                       "read": str(row.get("label") or "") in measured} for row in rows]
    return out
