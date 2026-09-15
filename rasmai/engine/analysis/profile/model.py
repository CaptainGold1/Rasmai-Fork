import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rasmai.engine.analysis.rating import ACHIEVEMENT_CAP, BEST_HEADROOM, _normal_cdf


# a best this far under what the player scores at that level, from a play or two, is a run that was
# dropped, not the chart's difficulty for them: measured in between-chart spreads, and never less than the gap
DROPPED_BEST_SPREADS = 2.0


DROPPED_BEST_GAP = 2.0


DROPPED_BEST_PLAYS = 2


@dataclass
class PlayProfile:
    """What the player's own history says about how they play."""

    # skill curve: expected achievement at a given chart constant
    curve_intercept: float = 101.0
    curve_slope: float = -0.15
    consistency: float = 0.6          # how far the player's scores scatter between *different* charts
    run_consistency: float = 0.5      # how far one run on a chart falls from the next on that same chart
    sample_size: int = 0

    comfort_constant: float = 0.0     # highest constant where SS (99%) is expected
    reach_constant: float = 0.0       # highest constant where S (97%) is expected
    played_ceiling: float = 0.0       # hardest constant with any score, a failed attempt included; shown, never searched from
    chart_ceiling: float = 15.0       # hardest constant in the database, so a search never reaches past the game
    hardest_s: float = 0.0            # hardest constant with an S (97%) or better: the real ceiling

    chart_type_bias: Dict[str, float] = field(default_factory=dict)   # std/dx
    genre_bias: Dict[str, float] = field(default_factory=dict)
    difficulty_bias: Dict[str, float] = field(default_factory=dict)
    # how far this player's scores on each tier sit from the shared curve at the same
    # constant: a Master 13 and an Expert 13 are not the same chart to the same hands
    difficulty_offset: Dict[str, float] = field(default_factory=dict)

    fc_rate: float = 0.0
    ap_rate: float = 0.0
    dx_score_rate: float = 0.0        # mean dxScore/maxDxScore over recent plays
    accuracy_focus: float = 0.5       # 0 = tech/clear player, 1 = score grinder

    recent_keys: Dict[Tuple[str, str, str], int] = field(default_factory=dict)
    recent_grind: Dict[Tuple[str, str, str], int] = field(default_factory=dict)
    history: Dict[Tuple[str, str, str], List[float]] = field(default_factory=dict)  # oldest -> newest
    play_counts: Dict[Tuple[str, str, str], int] = field(default_factory=dict)      # official per-chart
    active_days: int = 0
    new_version_share: float = 0.0    # fraction of recent plays on current-version charts

    # what the chart database says about the charts they choose, rather than how they score:
    # how old those charts are, what re-rating has done to their best 50, notes actually hit
    habits: Dict[str, Any] = field(default_factory=dict)

    # per half-level bucket: (typical good score, number of charts, best score)
    bucket_stats: Dict[float, Tuple[float, int, float]] = field(default_factory=dict)
    dense_ceiling: float = 0.0        # hardest level with enough charts to trust the curve

    # corrections learned from the player's recorded plays against earlier predictions
    sigma_scale: float = 1.0          # >1: their runs scatter more than the model said
    calibration_shift: float = 0.0    # where the upper third of their runs actually sits against the curve
    tier_shift: Dict[str, float] = field(default_factory=dict)
    calibration: Dict[str, Any] = field(default_factory=dict)
    # chart attributes the player scores above or below their own curve on
    traits: List[Dict[str, Any]] = field(default_factory=list)
    trait_axes: List[Dict[str, Any]] = field(default_factory=list)   # every group with enough charts, threshold or not

    def _local_expectation(self, constant: float) -> Tuple[Optional[float], float]:
        """Kernel-smoothed typical score from the buckets around `constant`, and how much data backs it.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :returns: ``(typical score, how much data backs it)``, or ``(None, 0.0)``.
        :rtype: Tuple[Optional[float], float]
        """
        if not self.bucket_stats:
            return None, 0.0
        numerator = denominator = 0.0
        for bucket, (representative, count, _best) in self.bucket_stats.items():
            weight = min(count, 10) * math.exp(-((bucket - constant) / 0.6) ** 2)
            numerator += weight * representative
            denominator += weight
        if denominator < 1e-9:
            return None, 0.0
        return numerator / denominator, denominator

    def _own_ceiling(self, constant: float) -> Optional[float]:
        """The most the player's own scores support at this level, between the populated buckets either side.

        Only buckets with four or more charts count, so one lucky score cannot pin the curve down,
        and nothing is returned above the hardest such bucket: that is extrapolation, which the
        dense-ceiling drop-off handles instead.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :returns: The ceiling, or ``None`` above the player's populated range.
        :rtype: Optional[float]
        """
        populated = [c for c, (_r, n, _b) in self.bucket_stats.items() if n >= 4]
        if not populated:
            return None
        below = [c for c in populated if c <= constant]
        above = [c for c in populated if c >= constant]
        if not below or not above:
            return None
        low, high = max(below), min(above)
        if low == high:
            return self.bucket_stats[low][0]
        start, end = self.bucket_stats[low][0], self.bucket_stats[high][0]
        return start + (end - start) * (constant - low) / (high - low)

    def expected_accuracy(self, constant: float) -> float:
        """What the player scores at this level when a run goes well.

        The straight-line fit is corrected by the player's own results near this
        level where they exist, and drops off above the hardest level they have
        real data on, so a thin top end never promises S ranks. Where the player has
        played a level properly, the curve may not promise much beyond what they have
        actually scored there: the smoothing reaches over a level or more, and without
        this a handful of charts at the very top borrow the scores of easier ones.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :returns: The achievement a good run should land.
        :rtype: float
        """
        line = self.curve_intercept + self.curve_slope * constant
        local, weight = self._local_expectation(constant)
        if local is not None:
            blend = weight / (weight + 3.0)
            line = blend * local + (1.0 - blend) * line
        if self.dense_ceiling and constant > self.dense_ceiling:
            line -= 0.8 * (constant - self.dense_ceiling)
        ceiling = self._own_ceiling(constant)
        if ceiling is not None:
            line = min(line, ceiling + 0.3)
        return min(ACHIEVEMENT_CAP, line)

    def expected_for(self, constant: float, difficulty: str) -> float:
        """The curve at this constant, shifted by how the player does on this difficulty tier and by what their plays taught the model.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param difficulty: The difficulty tier, such as ``"master"``.
        :type difficulty: str
        :returns: The achievement a good run should land on this tier.
        :rtype: float
        """
        tier = str(difficulty or "").lower()
        return min(ACHIEVEMENT_CAP, self.expected_accuracy(constant) + self.difficulty_offset.get(tier, 0.0)
                   + self.calibration_shift + self.tier_shift.get(tier, 0.0))

    def sigma_at(self, constant: float) -> float:
        """Spread to use when the chart itself is unknown to the player: charts differ, and so do runs.

        This is the right width for a chart they have never played, where how hard *this* chart is
        for them is part of the uncertainty. For a chart they already hold a score on, that part is
        already known and `run_sigma_at` is the one to use.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :returns: The spread to use at this constant.
        :rtype: float
        """
        sigma = max(0.3, self.consistency)
        if self.dense_ceiling and constant > self.dense_ceiling:
            sigma *= 1.0 + 0.5 * (constant - self.dense_ceiling)
        if self.sample_size < 40:
            sigma = max(sigma, 0.8)
        return min(3.0, sigma * self.sigma_scale)

    def run_sigma_at(self, constant: float) -> float:
        """Spread of one run on a chart the player has already scored, where only the run varies.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :returns: The spread to use at this constant.
        :rtype: float
        """
        sigma = max(0.25, self.run_consistency)
        if self.dense_ceiling and constant > self.dense_ceiling:
            # past the level they have real data on, this chart's own difficulty is a guess again
            sigma = max(sigma, self.sigma_at(constant))
        return min(3.0, sigma * self.sigma_scale)

    @property
    def search_ceiling(self) -> float:
        """The hardest constant the player has shown they can play: an S, or where the curve still expects one.

        Searches for unplayed charts reach up from here. `played_ceiling` is the wrong anchor for
        that: one failed attempt at a 15 would have a 12,000 player offered 15s as charts to try.

        :rtype: float
        """
        anchor = max(self.hardest_s, self.reach_constant)
        return anchor if anchor > 0 else self.played_ceiling

    def best_near(self, constant: float, window: float = 0.7) -> float:
        """Best score on any chart at least (constant - window) hard.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param window: How far below ``constant`` still counts as nearby, in constants.
        :type window: float
        :returns: The best achievement scored at or above that difficulty.
        :rtype: float
        """
        best = 0.0
        for bucket, (_rep, _count, bucket_best) in self.bucket_stats.items():
            if bucket >= constant - window:
                best = max(best, bucket_best)
        return best

    def rank_ceiling(self, constant: float, slack: float = 1.0) -> float:
        """Highest achievement worth targeting here: S and above need a score like it nearby.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param slack: How far past the player's best nearby score a target may reach.
        :type slack: float
        :returns: The highest achievement worth targeting.
        :rtype: float
        """
        return self.best_near(constant) + slack

    def feasibility(self, constant: float, target_accuracy: float, difficulty: str = "") -> float:
        """Rough probability the player can reach target_accuracy on this chart.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param target_accuracy: The achievement being aimed at.
        :type target_accuracy: float
        :param difficulty: The difficulty tier, such as ``"master"``.
        :type difficulty: str
        :returns: The probability of reaching the target.
        :rtype: float
        """
        expected = self.expected_for(constant, difficulty) if difficulty else self.expected_accuracy(constant)
        return _normal_cdf((expected - target_accuracy) / self.sigma_at(constant))

    def plays_for(self, key: Tuple[str, str, str]) -> int:
        """Official play count when known, else how often it shows in recent plays.

        :param key: The chart, as ``(title, chart type, difficulty)``.
        :type key: Tuple[str, str, str]
        :returns: How many times the chart has been played.
        :rtype: int
        """
        official = self.play_counts.get(key)
        if official is not None and official >= 0:
            return max(official, self.recent_grind.get(key, 0))
        return self.recent_grind.get(key, 0)

    def first_pass(self, constant: float, difficulty: str) -> Tuple[float, float]:
        """What a first run on a chart at this level lands, and its spread: the curve less a sight-read's cost.

        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param difficulty: The difficulty tier, such as ``"master"``.
        :type difficulty: str
        :rtype: Tuple[float, float]
        """
        sigma = max(0.3, self.sigma_at(constant))
        return min(ACHIEVEMENT_CAP, self.expected_for(constant, difficulty) - 0.35 - 0.4 * sigma), sigma

    def dropped_best(self, key: Tuple[str, str, str], constant: float, best_accuracy: float) -> bool:
        """Whether the best held on this chart is one dropped run rather than the chart's difficulty for the player.

        NEK held 76% on a 13.0 they score ~97 on at that level; a week later it was 95%. One or two plays
        that ended that far under the curve say nothing about the chart, so the model reads the chart as
        untried instead of pinning its expectation to the bad run. A chart ground a dozen times to the
        same low score is genuinely that hard for them, and play counts are what tell the two apart.

        :param key: The chart, as ``(title, chart type, difficulty)``.
        :type key: Tuple[str, str, str]
        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param best_accuracy: The best achievement the player already holds on the chart.
        :type best_accuracy: float
        :rtype: bool
        """
        if best_accuracy <= 0 or self.plays_for(key) > DROPPED_BEST_PLAYS:
            return False
        if len(self.history.get(key) or ()) > DROPPED_BEST_PLAYS:
            return False
        gap = max(DROPPED_BEST_GAP, DROPPED_BEST_SPREADS * self.sigma_at(constant))
        return best_accuracy < self.expected_for(constant, key[2]) - gap

    def chart_expectation(
        self, key: Tuple[str, str, str], constant: float, best_accuracy: float
    ) -> Tuple[float, float]:
        """What this player scores on *this* chart when they try, and how sure we are.

        :param key: The chart, as ``(title, chart type, difficulty)``.
        :type key: Tuple[str, str, str]
        :param constant: The chart's internal difficulty constant.
        :type constant: float
        :param best_accuracy: The best achievement the player already holds on the chart.
        :type best_accuracy: float
        :returns: ``(expected achievement, spread)`` for this chart.
        :rtype: Tuple[float, float]
        """
        if self.dropped_best(key, constant, best_accuracy):
            return self.first_pass(constant, key[2])
        curve = self.expected_for(constant, key[2])      # the key's third part is the difficulty tier
        sigma = self.run_sigma_at(constant)
        # a score on the chart is proof of at least one play, whether or not the count was ever read;
        # without this the model treats a chart they have scored as one they have never touched
        plays = max(self.plays_for(key), 1 if best_accuracy > 0 else 0)
        expected = curve
        if best_accuracy > 0 and plays > 0:
            weight = plays / (plays + 3.0)
            expected = curve - weight * max(0.0, curve - best_accuracy)
            # the next run varies by the run spread; where the player stands on this chart is itself
            # estimated from the plays behind their best, so a chart played once carries the extra
            # uncertainty of a single sample and one played often carries almost none
            sigma = sigma * math.sqrt(1.0 + 1.0 / plays)
        if best_accuracy > 0:
            # Someone whose best is well above the curve is good at this chart.
            expected = max(expected, best_accuracy - 0.5 * sigma)
            # ...and nobody beats their own best by much in one run: the curve may promise a
            # little more than the best, never a rank step. On held-out plays the uncapped
            # centre priced targets above the best at 33% that landed 12% of the time.
            expected = min(expected, best_accuracy + BEST_HEADROOM * sigma)
        history = self.history.get(key)
        if history and len(history) >= 2 and history[-1] > history[0]:
            expected += min(0.4, (history[-1] - history[0]) * 0.25)
        return min(ACHIEVEMENT_CAP, expected), sigma

    def chart_feasibility(
        self, key: Tuple[str, str, str], constant: float, best_accuracy: float, target_accuracy: float
    ) -> float:
        expected, sigma = self.chart_expectation(key, constant, best_accuracy)
        return _normal_cdf((expected - target_accuracy) / sigma)

    def affinity(self, chart_type: str, genre: str, difficulty: str) -> float:
        value = 1.0
        value *= self.chart_type_bias.get(chart_type, 1.0)
        value *= self.genre_bias.get(genre, 1.0)
        value *= self.difficulty_bias.get(difficulty, 1.0)
        return value

    def curve_points(self, step: float = 0.1) -> List[Dict[str, float]]:
        """The fitted curve as points, from the easiest chart scored to the hardest that exists.

        The dashboard draws this against the player's own scores, so what the model believes and
        what they actually did can be read off one picture.

        :param step: Constant between points.
        :type step: float
        :rtype: List[Dict[str, float]]
        """
        low = min((c for c, (_r, n, _b) in self.bucket_stats.items() if n), default=1.0)
        high = max(self.chart_ceiling, self.played_ceiling or 0.0)
        if high <= low:
            return []
        points = []
        for tick in range(int(round(low * 10)), int(round(high * 10)) + 1, max(1, int(round(step * 10)))):
            constant = tick / 10.0
            points.append({"c": round(constant, 1),
                           "e": round(self.expected_accuracy(constant), 3),
                           "s": round(self.sigma_at(constant), 3)})
        return points

    def summary(self) -> Dict[str, Any]:
        style = "balanced"
        if self.accuracy_focus >= 0.65:
            style = "score grinder"
        elif self.accuracy_focus <= 0.35:
            style = "clear hunter"
        favourite_type = max(self.chart_type_bias, key=self.chart_type_bias.get) if self.chart_type_bias else ""
        favourite_genre = max(self.genre_bias, key=self.genre_bias.get) if self.genre_bias else ""
        return {
            "style": style,
            "comfortConstant": round(self.comfort_constant, 1),
            "reachConstant": round(self.reach_constant, 1),
            "playedCeiling": round(self.played_ceiling, 1),
            "hardestS": round(self.hardest_s, 1),
            "consistency": round(self.consistency, 2),
            "expectedAt13": round(self.expected_accuracy(13.0), 2),
            "curve": self.curve_points(),
            "expectedAt14": round(self.expected_accuracy(14.0), 2),
            "difficultyOffsets": {tier: round(value, 2) for tier, value in sorted(self.difficulty_offset.items())},
            "traits": list(self.traits),
            "traitAxes": list(self.trait_axes),
            "calibration": dict(self.calibration),
            "denseCeiling": round(self.dense_ceiling, 1),
            "fcRate": round(self.fc_rate, 3),
            "apRate": round(self.ap_rate, 3),
            "dxScoreRate": round(self.dx_score_rate, 3),
            "favouriteChartType": favourite_type,
            "favouriteGenre": favourite_genre,
            "newVersionShare": round(self.new_version_share, 2),
            "habits": dict(self.habits),
            "activeDays": self.active_days,
            "sampleSize": self.sample_size,
            "playCountsKnown": sum(1 for v in self.play_counts.values() if v >= 0),
        }
