from typing import List, Optional, Tuple

from rasmai.engine.analysis.rating import calculate_rating, rank_for
from rasmai.engine.analysis.charts import ChartIndex
from rasmai.engine.analysis.profile import PlayProfile
from rasmai.engine.analysis.pools import Best50
from rasmai.engine.analysis.picks.model import ScoredCandidate


def _unplayed_candidates(
    profile: PlayProfile,
    best50: Best50,
    chart_index: ChartIndex,
    played_keys: set,
    current_version: int,
    scan_window: float = 1.5,
    span: Optional[Tuple[float, float]] = None,
) -> List[ScoredCandidate]:
    """Unplayed charts that would enter the best-50 at the predicted score.

    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param best50: The player's two rating pools.
    :type best50: Best50
    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param played_keys: Every chart the player already has a score on.
    :type played_keys: set
    :param current_version: The game version the player is on.
    :type current_version: int
    :param scan_window: How far below the player's ceiling to search, in constants.
    :type scan_window: float
    :returns: The unplayed charts worth a first pass.
    :rtype: List[ScoredCandidate]
    """
    results: List[ScoredCandidate] = []
    if not profile.sample_size:
        return results

    upper = profile.search_ceiling + 0.3
    lower = max(0.0, profile.reach_constant - scan_window)
    if best50.new_pool.headroom() or best50.old_pool.headroom():
        # An unfilled best-50 means even comfortable charts are worth points.
        lower = max(0.0, min(lower, profile.comfort_constant - 3.0))
    if span:
        lower, upper = span         # the player named the constants they want to see; the window is theirs

    for key, chart in chart_index.items():
        if key in played_keys or chart.locked or not chart_index.playable(chart):
            continue
        if chart.difficulty not in ("expert", "master", "remaster"):
            continue
        if not (lower <= chart.constant <= upper):
            continue

        is_new = bool(current_version) and chart.version == current_version
        expected = profile.expected_for(chart.constant, chart.difficulty)
        expected = max(0.0, expected - 0.35 - 0.4 * profile.sigma_at(chart.constant))
        floor = 80.0 if best50.pool_for(is_new).headroom() > 0 else 94.0
        if expected < floor:
            continue

        expected_rating = calculate_rating(chart.constant, expected)
        rating_gain = best50.gain_if(key, is_new, expected_rating)
        if rating_gain <= 0:
            continue

        feasibility = profile.feasibility(chart.constant, expected, chart.difficulty)
        affinity = profile.affinity(chart.chart_type, chart.genre, chart.difficulty)
        proximity = 1.0 / (1.0 + abs(chart.constant - profile.comfort_constant) / 3.0)
        score = rating_gain * feasibility * affinity * proximity * 0.7
        if is_new and best50.new_pool.headroom() > 0:
            score *= 1.4

        results.append(ScoredCandidate(
            title=chart.title,
            chart_type=chart.chart_type,
            difficulty_type=chart.difficulty,
            level=chart.level,
            constant=chart.constant,
            genre=chart.genre,
            artist=chart.artist,
            cover=chart.cover,
            is_new=is_new,
            is_unplayed=True,
            current_accuracy=0.0,
            current_rating=0,
            target_accuracy=expected,
            target_rating=expected_rating,
            target_rank=rank_for(expected),
            current_rank="-",
            chart_gain=expected_rating,
            rating_gain=rating_gain,
            feasibility=feasibility,
            affinity=affinity,
            score=score,
            fc_status="NONE",
            category="unplayed",
            reason=f"unplayed, ~{rank_for(expected)} on first passes for +{rating_gain}",
            expected=expected,
        ))

    results.sort(key=lambda candidate: candidate.score, reverse=True)
    return results[:25]
