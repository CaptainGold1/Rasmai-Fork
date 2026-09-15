from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple
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


def play_habits(songs: Sequence[Any], recent_plays: Sequence[Dict[str, Any]], chart_index: ChartIndex,
                play_counts: Dict[Tuple[str, str, str], int], best50: Any) -> Dict[str, Any]:
    """The three things the chart database can say about how someone plays, rather than how well.

    Each part is left out when there is not enough behind it to mean anything, so a page can show
    what is there and say nothing about the rest.

    :rtype: Dict[str, Any]
    """
    out: Dict[str, Any] = {}
    for name, value in (("age", chart_age(recent_plays, chart_index)),
                        ("rerates", rerate_effect(songs, chart_index, best50)),
                        ("notes", notes_struck(chart_index, play_counts))):
        if value:
            out[name] = value
    return out
