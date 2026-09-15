from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
import statistics

from rasmai.engine.analysis import ChartIndex, calculate_rating, loose_title

YEAR = 365.25


def _played_at(play: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(play.get("playedAt") or "")[:19])
    except ValueError:
        return None


def _released(chart: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(getattr(chart, "released", "") or ""))
    except ValueError:
        return None


def chart_age(recent_plays: Sequence[Dict[str, Any]], chart_index: ChartIndex) -> Dict[str, Any]:
    """How old the charts a player picks are, from the plays on their record.

    Someone who plays the newest thing on the cabinet and someone working through ten years of back
    catalogue both look the same on a score page; the gap between a chart's release and the day it
    was played is what tells them apart.

    :param recent_plays: The plays as the site listed them.
    :type recent_plays: Sequence[Dict[str, Any]]
    :param chart_index: The chart database to look charts up in.
    :type chart_index: ChartIndex
    :rtype: Dict[str, Any]
    """
    ages = []
    for play in recent_plays:
        when = _played_at(play)
        key = (str(play.get("songName", "")).casefold(), str(play.get("musicType", "")).lower() or "std",
               str(play.get("difficulty", "")).lower())
        chart = chart_index.get(key)
        out = _released(chart) if chart is not None else None
        if when and out:
            ages.append(max(0.0, (when - out).days / YEAR))
    if len(ages) < 5:
        return {}
    ages.sort()
    return {
        "plays": len(ages),
        "medianYears": round(statistics.median(ages), 1),
        "freshShare": round(sum(1 for age in ages if age <= 1.0) / len(ages), 2),
        # the quarter they picked that was newest, which is where a release chaser shows up
        "newestQuarterYears": round(statistics.median(ages[: max(1, len(ages) // 4)]), 1),
    }


def rerate_effect(songs: Sequence[Any], chart_index: ChartIndex, best50: Any) -> Dict[str, Any]:
    """What the player's rating owes to charts being re-rated rather than to playing them.

    A constant is revised now and then, and every score on that chart is worth more or less from
    that day on without the player touching it. This is the difference between their best 50 as it
    stands and the same scores under the constants those charts first shipped with.

    :param songs: The player's charts that carry a score.
    :type songs: Sequence[Any]
    :param chart_index: The chart database to look charts up in.
    :type chart_index: ChartIndex
    :param best50: The player's best-50 pools.
    :type best50: Any
    :rtype: Dict[str, Any]
    """
    try:
        from rasmai.scraping import dxdata
        stored = dxdata.cached()
        revised = stored.get("constants") or {}
        # the history is keyed by version name, and those do not sort into the order they came out
        # in: the earliest constant has to be found by release date or the wrong one is compared
        order = {str(name): str(date) for name, date in (stored.get("versions") or [])}
    except Exception:                    # the stat is a nicety; the profile must build without it
        return {}
    if not revised or not order:
        return {}
    in_pool = set(best50.new_pool.in_pool) | set(best50.old_pool.in_pool)
    moved, delta = 0, 0
    for song in songs:
        accuracy = float(getattr(song, "accuracy", 0) or 0)
        if accuracy <= 0:
            continue
        key = (str(getattr(song, "name", "")).casefold(), str(getattr(song, "chart_type", "")).lower() or "std",
               str(getattr(song, "difficulty_type", "")).lower())
        if key not in in_pool:
            continue
        chart = chart_index.get(key)
        if chart is None:
            continue
        history = revised.get(f"{loose_title(chart.title)}|{chart.chart_type}|{chart.difficulty}")
        if not history:
            continue
        dated = [version for version in history if version in order]
        if not dated:
            continue
        first = history[min(dated, key=lambda version: order[version])]
        if abs(float(first) - chart.constant) < 0.05:
            continue
        moved += 1
        delta += calculate_rating(chart.constant, accuracy) - calculate_rating(float(first), accuracy)
    if not moved:
        return {}
    return {"charts": moved, "rating": delta}


def notes_struck(chart_index: ChartIndex, play_counts: Dict[Tuple[str, str, str], int]) -> Dict[str, Any]:
    """How many notes the player has actually hit, counting every recorded clear of every chart.

    :param chart_index: The chart database to look charts up in.
    :type chart_index: ChartIndex
    :param play_counts: How many times the player has cleared each chart.
    :type play_counts: Dict[Tuple[str, str, str], int]
    :rtype: Dict[str, Any]
    """
    notes, counted = 0, 0
    for key, plays in (play_counts or {}).items():
        if plays <= 0:
            continue
        chart = chart_index.get(key)
        if chart is None or not chart.notes:
            continue
        counted += 1
        notes += chart.notes * plays
    if not counted:
        return {}
    return {"notes": notes, "charts": counted}


WARM_UP_PLAYS = 120        # plays carrying a track number before the question can be asked at all


WARM_UP_P = 0.05           # and the gap has to be this unlikely by chance before it is stated


def warm_up(recorded_plays: Sequence[Dict[str, Any]], chart_index: ChartIndex, profile: Any,
            bests: Dict[Tuple[str, str, str], float]) -> Dict[str, Any]:
    """Whether the first track of a credit scores differently from the ones after it.

    Every play records which track of the credit it was, so the warm-up question is answerable:
    does someone play worse cold? Scores are compared against what the model expected of that
    exact chart, so the answer is not just "they pick harder songs first". Bad runs make the mean
    useless, hence a rank test on the two groups, and nothing is said unless it clears the bar.

    :param recorded_plays: Stored plays, each with a chart key, an achievement and a track number.
    :type recorded_plays: Sequence[Dict[str, Any]]
    :param chart_index: The chart database to look charts up in.
    :type chart_index: ChartIndex
    :param profile: The player's own curve, for what each chart was worth to them.
    :type profile: Any
    :param bests: The best achievement the player holds on each chart.
    :type bests: Dict[Tuple[str, str, str], float]
    :rtype: Dict[str, Any]
    """
    import math

    import numpy as np

    first: List[float] = []
    later: List[float] = []
    for play in recorded_plays or []:
        track = int(play.get("track") or 0)
        raw = str(play.get("chart_key") or "")
        parts = raw.split("|")
        if not track or len(parts) != 3:
            continue
        key = (parts[0].casefold(), parts[1].lower(), parts[2].lower())
        chart = chart_index.get(key)
        achievement = float(play.get("achievement") or 0)
        if chart is None or chart.constant <= 0 or achievement <= 0:
            continue
        expected, _spread = profile.chart_expectation(key, chart.constant, bests.get(key, 0.0))
        (first if track == 1 else later).append(achievement - expected)
    if len(first) + len(later) < WARM_UP_PLAYS or len(first) < 30 or len(later) < 30:
        return {}

    # a rank test, because one abandoned run would swamp a comparison of averages
    values = np.array(first + later)
    ranks = values.argsort().argsort().astype(float) + 1.0
    n1, n2 = len(first), len(later)
    u = ranks[:n1].sum() - n1 * (n1 + 1) / 2.0
    mean_u = n1 * n2 / 2.0
    spread_u = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
    if spread_u <= 0:
        return {}
    z = (u - mean_u) / spread_u
    p_value = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
    if p_value > WARM_UP_P:
        return {}
    gap = float(np.median(first) - np.median(later))
    return {
        "firstTrack": round(float(np.median(first)), 2),
        "laterTracks": round(float(np.median(later)), 2),
        "gap": round(gap, 2),
        "plays": n1 + n2,
        "p": round(p_value, 3),
        # negative: they play worse cold, so the first track is worth spending on something easy
        "colder": gap < 0,
    }


def play_habits(songs: Sequence[Any], recent_plays: Sequence[Dict[str, Any]], chart_index: ChartIndex,
                play_counts: Dict[Tuple[str, str, str], int], best50: Any,
                recorded_plays: Optional[Sequence[Dict[str, Any]]] = None,
                profile: Any = None) -> Dict[str, Any]:
    """The three things the chart database can say about how someone plays, rather than how well.

    Each part is left out when there is not enough behind it to mean anything, so a page can show
    what is there and say nothing about the rest.

    :rtype: Dict[str, Any]
    """
    bests: Dict[Tuple[str, str, str], float] = {}
    for song in songs:
        key = (str(getattr(song, "name", "")).casefold(), str(getattr(song, "chart_type", "")).lower() or "std",
               str(getattr(song, "difficulty_type", "")).lower())
        bests[key] = max(bests.get(key, 0.0), float(getattr(song, "accuracy", 0) or 0))
    warm = warm_up(recorded_plays or [], chart_index, profile, bests) if profile is not None else {}
    out: Dict[str, Any] = {}
    for name, value in (("age", chart_age(recent_plays, chart_index)),
                        ("rerates", rerate_effect(songs, chart_index, best50)),
                        ("notes", notes_struck(chart_index, play_counts)),
                        ("warmUp", warm)):
        if value:
            out[name] = value
    return out
