import statistics
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rasmai.engine.analysis.charts import ChartIndex
from rasmai.engine.analysis.profile.fit import _bias_map, _fit_skill_curve
from rasmai.engine.analysis.profile.model import PlayProfile


def build_play_profile(
    songs: Sequence[Any],
    recent_plays: Sequence[Dict[str, Any]],
    chart_index: ChartIndex,
    current_version: int,
    play_counts: Optional[Dict[Tuple[str, str, str], int]] = None,
    recorded_plays: Optional[Sequence[Dict[str, Any]]] = None,
    judgements: Optional[Sequence[Dict[str, Any]]] = None,
) -> PlayProfile:
    profile = PlayProfile()
    if play_counts:
        profile.play_counts = dict(play_counts)

    scored = [
        song for song in songs
        if getattr(song, "difficulty", 0) > 0
        and getattr(song, "accuracy", 0) > 0
        and getattr(song, "difficulty_type", "") != "utage"
    ]
    profile.sample_size = len(scored)
    if not scored:
        return profile

    points = [(float(song.difficulty), float(song.accuracy)) for song in scored]
    (profile.curve_intercept, profile.curve_slope, profile.consistency,
     profile.bucket_stats, profile.dense_ceiling) = _fit_skill_curve(points)
    # the fit measures how the player's charts differ from each other; how much one run differs from
    # the next is a separate, much smaller number, and only their own repeat plays can say what it is
    from rasmai.engine import insights as _insights      # imported here: insights reads the profile it is measuring
    profile.run_consistency = _insights.run_spread(recorded_plays or []) or _insights.DEFAULT_RUN_SPREAD

    # comfort (SS expected) and reach (S expected) come from the corrected curve,
    # never past the hardest chart that exists
    hardest = min(15.0, max((chart.constant for chart in chart_index.values()), default=15.0))
    profile.chart_ceiling = hardest
    grid = [i / 10.0 for i in range(10, int(hardest * 10) + 1)]
    profile.comfort_constant = max((c for c in grid if profile.expected_accuracy(c) >= 99.0), default=0.0)
    profile.reach_constant = max((c for c in grid if profile.expected_accuracy(c) >= 97.0), default=0.0)
    # a player who scores 98.5 everywhere never "expects" 99, and the fit would put their comfort at a 6 or an 8:
    # comfort is where they play well, and that is never more than a level below where they still land an S
    if profile.reach_constant > 0:
        profile.comfort_constant = max(profile.comfort_constant, round(profile.reach_constant - 1.0, 1))
    profile.played_ceiling = max(constant for constant, _a in points)
    profile.hardest_s = max((constant for constant, accuracy in points if accuracy >= 97.0), default=0.0)

    # Each difficulty tier gets its own offset from the curve: the median of the
    # player's residuals on that tier, pulled toward zero while the sample is thin.
    # The median, not the mean, so a couple of abandoned runs do not drag it down.
    residuals: Dict[str, List[float]] = {}
    for song in scored:
        tier = str(getattr(song, "difficulty_type", "")).lower()
        residuals.setdefault(tier, []).append(float(song.accuracy) - profile.expected_accuracy(float(song.difficulty)))
    raw: Dict[str, float] = {}
    for tier, values in residuals.items():
        if len(values) >= 3:
            shrink = len(values) / (len(values) + 12.0)
            raw[tier] = statistics.median(values) * shrink
    if raw:
        # centred on the player's own chart mix, so the curve keeps its level and only
        # the difference between tiers moves: what an Expert 13 costs against a Master 13
        weights = {tier: len(residuals[tier]) for tier in raw}
        centre = sum(raw[tier] * weights[tier] for tier in raw) / sum(weights.values())
        for tier, value in raw.items():
            profile.difficulty_offset[tier] = max(-6.0, min(6.0, value - centre))

    fc_states = {"FC", "FC+", "AP", "AP+"}
    ap_states = {"AP", "AP+"}
    fc_count = sum(1 for song in scored if str(getattr(song, "fc_status", "")).upper() in fc_states)
    ap_count = sum(1 for song in scored if str(getattr(song, "fc_status", "")).upper() in ap_states)
    profile.fc_rate = fc_count / len(scored)
    profile.ap_rate = ap_count / len(scored)

    type_counts: Dict[str, int] = {}
    genre_counts: Dict[str, int] = {}
    difficulty_counts: Dict[str, int] = {}
    dx_ratios: List[float] = []
    days: set = set()
    new_version_plays = 0

    for index, play in enumerate(recent_plays):
        title = str(play.get("songName", ""))
        if not title:
            continue
        chart_type = str(play.get("musicType", "")).lower() or "std"
        difficulty = str(play.get("difficulty", "")).lower()
        key = (title.casefold(), chart_type, difficulty)
        profile.recent_keys.setdefault(key, index)
        profile.recent_grind[key] = profile.recent_grind.get(key, 0) + 1
        raw_achievement = play.get("achievement")
        if raw_achievement and 0 < float(raw_achievement) / 10000.0 <= 101.0:
            # The record page lists newest first; keep history oldest -> newest.
            profile.history.setdefault(key, []).insert(0, float(raw_achievement) / 10000.0)

        type_counts[chart_type] = type_counts.get(chart_type, 0) + 1
        difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1

        chart = chart_index.get(key)
        if chart:
            if chart.genre:
                genre_counts[chart.genre] = genre_counts.get(chart.genre, 0) + 1
            if current_version and chart.version == current_version:
                new_version_plays += 1

        max_dx = play.get("maxDxScore") or 0
        if max_dx:
            dx_ratios.append(float(play.get("dxScore", 0)) / float(max_dx))

        played_at = play.get("playedAt")
        if isinstance(played_at, str):
            try:
                played_at = datetime.fromisoformat(played_at)
            except ValueError:
                played_at = None
        if isinstance(played_at, datetime):
            days.add(played_at.date())

    # Fall back to the full score table when the recent-play list is thin.
    if len(recent_plays) < 10:
        for song in scored:
            chart_type = str(getattr(song, "chart_type", "")).lower() or "std"
            difficulty = str(getattr(song, "difficulty_type", "")).lower()
            type_counts[chart_type] = type_counts.get(chart_type, 0) + 1
            difficulty_counts[difficulty] = difficulty_counts.get(difficulty, 0) + 1

    profile.chart_type_bias = _bias_map(type_counts)
    profile.genre_bias = _bias_map(genre_counts, strength=0.25)
    profile.difficulty_bias = _bias_map(difficulty_counts, strength=0.20)
    profile.dx_score_rate = statistics.fmean(dx_ratios) if dx_ratios else 0.0
    profile.active_days = len(days)
    if recent_plays:
        profile.new_version_share = new_version_plays / len(recent_plays)

    high_score_rate = sum(1 for song in scored if float(song.accuracy) >= 99.0) / len(scored)
    profile.accuracy_focus = max(0.0, min(1.0, 0.5 + (high_score_rate - profile.fc_rate)))

    # The model checks itself against the plays it has seen land, then reads the
    # player's traits off the corrected curve.
    from rasmai.engine import insights
    if recorded_plays:
        insights.apply_calibration(profile, insights.calibrate(profile, recorded_plays, chart_index))
    profile.trait_axes = insights.trait_residuals(scored, chart_index, profile, recorded_plays)
    if judgements:
        # the judgement pages measure the same thing from the other side: not which charts cost points
        # but which notes did. Both are offsets against the player's own middle, so they share a list.
        from rasmai.engine.judgements import judgement_traits
        profile.trait_axes = sorted(profile.trait_axes + judgement_traits(judgements),
                                    key=lambda trait: trait["offset"])
    profile.traits = insights.notable(profile.trait_axes)

    return profile


def detect_current_version(
    songs: Sequence[Any],
    chart_index: ChartIndex,
    minimum_charts: int = 8,
) -> int:
    """Highest game version the player actually has charts from.

    :param songs: The player's scored charts.
    :type songs: Sequence[Any]
    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param minimum_charts: How many charts a version needs before it counts.
    :type minimum_charts: int
    :returns: The version number, or 0 when no version has enough charts.
    :rtype: int
    """
    counts: Dict[int, int] = {}
    for song in songs:
        key = (
            str(getattr(song, "name", "")).casefold(),
            str(getattr(song, "chart_type", "")).lower() or "std",
            str(getattr(song, "difficulty_type", "")).lower(),
        )
        chart = chart_index.get(key)
        if chart and chart.version:
            counts[chart.version] = counts.get(chart.version, 0) + 1
    eligible = [version for version, count in counts.items() if count >= minimum_charts]
    if eligible:
        return max(eligible)
    return max(counts) if counts else 0
