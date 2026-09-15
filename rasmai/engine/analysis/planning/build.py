from typing import Any, List, Optional, Sequence

from rasmai.engine.analysis.rating import _normal_cdf, calculate_rating, challenge_for, rank_for
from rasmai.engine.analysis.charts import ChartIndex, level_floor
from rasmai.engine.analysis.profile import PlayProfile
from rasmai.engine.analysis.pools import Best50
from rasmai.engine.analysis.unplayed import unplayed_window
from rasmai.engine.analysis.planning.model import GAP_STEPS, Plan, PlanOption, PlanStep, next_milestone
from rasmai.engine.analysis.planning.predict import played_keys, target_tiers


def _plan_options(
    songs: Sequence[Any],
    profile: PlayProfile,
    chart_index: ChartIndex,
    current_version: int,
    min_feasibility: float,
    include_unplayed: bool,
    stretch_sigmas: float,
    slack: float = 1.0,
) -> List[PlanOption]:
    """Every (chart, target rank) pair the player could plausibly chase.

    :param songs: The player's scored charts.
    :type songs: Sequence[Any]
    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param current_version: The game version the player is on.
    :type current_version: int
    :param min_feasibility: Drop targets the player lands less often than this.
    :type min_feasibility: float
    :param include_unplayed: Whether charts the player has never touched may be used.
    :type include_unplayed: bool
    :param stretch_sigmas: How many spreads above the expected score a target may sit.
    :type stretch_sigmas: float
    :param slack: How far past the player's best nearby score a target may reach.
    :type slack: float
    :returns: Every plausible ``(chart, target)`` pair.
    :rtype: List[PlanOption]
    """
    options: List[PlanOption] = []
    played = played_keys(songs, chart_index)

    def tiers_for(accuracy: float, expected: float, sigma: float, constant: float, played: bool = True):
        return target_tiers(profile, accuracy, expected, sigma, constant, stretch_sigmas, slack, played=played)

    for song in songs:
        difficulty_type = str(getattr(song, "difficulty_type", "")).lower()
        if difficulty_type == "utage":
            continue
        constant = float(getattr(song, "difficulty", 0) or 0)
        accuracy = float(getattr(song, "accuracy", 0) or 0)
        if constant <= 0 or accuracy <= 0:
            continue
        chart_type = str(getattr(song, "chart_type", "")).lower() or "std"
        key = (str(song.name).casefold(), chart_type, difficulty_type)
        chart = chart_index.get(key)
        genre = chart.genre if chart else str(getattr(song, "genre", ""))
        expected, sigma = profile.chart_expectation(key, constant, accuracy)
        affinity = profile.affinity(chart_type, genre, difficulty_type)
        plays = profile.plays_for(key)
        for rank_name, threshold in tiers_for(accuracy, expected, sigma, constant,
                                              played=not profile.dropped_best(key, constant, accuracy)):
            feasibility = _normal_cdf((expected - threshold) / sigma)
            if feasibility < min_feasibility:
                continue
            options.append(PlanOption(
                key=key, title=song.name, chart_type=chart_type, difficulty_type=difficulty_type,
                level=str(getattr(song, "level", "") or (chart.level if chart else "")),
                constant=constant, cover=str(getattr(song, "cover_url", "")),
                is_new=bool(getattr(song, "is_new", False)), is_unplayed=False,
                current_accuracy=accuracy, current_rank=rank_for(accuracy),
                target_accuracy=threshold, target_rank=rank_name,
                target_rating=calculate_rating(constant, threshold),
                feasibility=feasibility, affinity=affinity,
                above_curve=threshold - expected, plays=plays, expected=expected,
            ))

    if include_unplayed and profile.sample_size:
        options.extend(unplayed_plan_options(
            profile, chart_index, played, current_version, min_feasibility, stretch_sigmas, slack,
            max(0.0, profile.reach_constant - 1.0), profile.search_ceiling + 0.3,
        ))
    return options


def unplayed_plan_options(
    profile: PlayProfile,
    chart_index: ChartIndex,
    played: set,
    current_version: int,
    min_feasibility: float,
    stretch_sigmas: float,
    slack: float,
    lower: float,
    upper: float,
) -> List[PlanOption]:
    """Charts the player has never touched, as plan steps, within a constant window.

    A first pass on an unfamiliar chart lands below the player's curve, so the
    estimate is discounted; the targets are still the player's own rank ceiling.

    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param played: Whether the player has a score on the chart.
    :type played: set
    :param current_version: The game version the player is on.
    :type current_version: int
    :param min_feasibility: Drop targets the player lands less often than this.
    :type min_feasibility: float
    :param stretch_sigmas: How many spreads above the expected score a target may sit.
    :type stretch_sigmas: float
    :param slack: How far past the player's best nearby score a target may reach.
    :type slack: float
    :param lower: Lowest chart constant to consider.
    :type lower: float
    :param upper: Highest chart constant to consider.
    :type upper: float
    :returns: The unplayed charts that could serve as steps.
    :rtype: List[PlanOption]
    """
    options: List[PlanOption] = []
    global_sigma = max(0.5, profile.consistency)
    for key, chart in chart_index.items():
        if key in played or chart.difficulty not in ("expert", "master", "remaster"):
            continue
        if not chart_index.playable(chart) or not (lower <= chart.constant <= upper):
            continue
        if chart.locked:
            continue      # played charts are already gone above, so this one is still behind an unlock
        is_new = bool(current_version) and chart.version == current_version
        local_sigma = max(global_sigma, profile.sigma_at(chart.constant))
        expected = profile.expected_for(chart.constant, chart.difficulty) - 0.35 - 0.4 * local_sigma
        affinity = profile.affinity(chart.chart_type, chart.genre, chart.difficulty)
        for rank_name, threshold in target_tiers(profile, 0.0, expected, local_sigma, chart.constant,
                                                 stretch_sigmas, slack, played=False):
            if threshold < 97.0:
                continue
            feasibility = _normal_cdf((expected - threshold) / local_sigma)
            if feasibility < min_feasibility:
                continue
            options.append(PlanOption(
                key=key, title=chart.title, chart_type=chart.chart_type,
                difficulty_type=chart.difficulty, level=chart.level, constant=chart.constant,
                cover=chart.cover, is_new=is_new, is_unplayed=True,
                current_accuracy=0.0, current_rank="-",
                target_accuracy=threshold, target_rank=rank_name,
                target_rating=calculate_rating(chart.constant, threshold),
                feasibility=feasibility, affinity=affinity,
                above_curve=threshold - expected, plays=0, expected=expected,
            ))
    return options


def build_plan(
    songs: Sequence[Any],
    profile: PlayProfile,
    best50: Best50,
    chart_index: ChartIndex,
    current_version: int,
    start_rating: int,
    goal_rating: Optional[int] = None,
    max_steps: int = 40,
    stretch: bool = False,
    include_unplayed: bool = True,
    challenge: str = "balanced",
    difficulty: Optional[str] = None,
    min_level: Optional[str] = None,
) -> Plan:
    """Greedy route from the current rating to a goal.

    `difficulty` holds the route to one chart difficulty, `min_level` to charts at
    that level or above; both narrow what may be chosen, never how it is judged.

    :param songs: The player's scored charts.
    :type songs: Sequence[Any]
    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param best50: The player's two rating pools.
    :type best50: Best50
    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param current_version: The game version the player is on.
    :type current_version: int
    :param start_rating: The rating the route starts from.
    :type start_rating: int
    :param goal_rating: The rating to reach, or ``None`` for the next milestone.
    :type goal_rating: Optional[int]
    :param max_steps: Most steps the route may hold.
    :type max_steps: int
    :param stretch: Whether to allow targets beyond the challenge level's usual reach.
    :type stretch: bool
    :param include_unplayed: Whether charts the player has never touched may be used.
    :type include_unplayed: bool
    :param challenge: How bold the targets are: ``"easy"``, ``"balanced"``, ``"hard"`` or ``"extreme"``.
    :type challenge: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: Optional[str]
    :param min_level: Hold the route to charts at this displayed level and above.
    :type min_level: Optional[str]
    :returns: The route, step by step.
    :rtype: Plan
    """
    goal = goal_rating or next_milestone(start_rating)
    mode = challenge_for(challenge)
    simulated = Best50(best50.new_pool.clone(), best50.old_pool.clone())
    min_feasibility = 0.06 if stretch else mode.plan_min_feasibility
    stretch_sigmas = 2.5 if stretch else mode.plan_sigmas
    slack = 2.5 if stretch else mode.slack
    options = _plan_options(
        songs, profile, chart_index, current_version, min_feasibility, include_unplayed, stretch_sigmas, slack
    )
    wanted = str(difficulty or "").lower() or None
    floor = level_floor(min_level)

    def allowed(option: PlanOption) -> bool:
        if wanted and option.difficulty_type != wanted:
            return False
        return option.constant >= floor - 1e-9

    if wanted or floor:
        options = [option for option in options if allowed(option)]

    steps: List[PlanStep] = []
    used: set = set()
    cumulative = 0
    needed = max(0, goal - start_rating)

    def take(pool: Sequence[PlanOption], shy_of_unplayed: bool, fills_gap: bool) -> bool:
        """Add the best remaining option from this pool; False when none is left.

        :param pool: The rating pool to draw from.
        :type pool: Sequence[PlanOption]
        :param shy_of_unplayed: Whether to hold back charts the player has never touched.
        :type shy_of_unplayed: bool
        :param fills_gap: Whether the step is there to close the remaining gap.
        :type fills_gap: bool
        :rtype: bool
        """
        nonlocal cumulative
        best: Optional[PlanOption] = None
        best_gain = 0
        best_value = 0.0
        for option in pool:
            if option.key in used:
                continue
            gain = simulated.gain_if(option.key, option.is_new, option.target_rating)
            if gain <= 0:
                continue
            value = gain * option.feasibility * option.affinity
            if shy_of_unplayed and option.is_unplayed:
                value *= 0.7      # a chart already in hand beats an unfamiliar one of equal worth
            if value > best_value:
                best, best_gain, best_value = option, gain, value
        if best is None:
            return False
        simulated.pool_for(best.is_new).apply(best.key, best.target_rating)
        used.add(best.key)
        cumulative += best_gain
        steps.append(PlanStep(option=best, gain=best_gain, cumulative=cumulative, fills_gap=fills_gap))
        return True

    while len(steps) < max_steps and cumulative < needed:
        if not take(options, True, False):
            break

    # The charts the player already has ran out before the goal. Charts they have
    # never touched can still cover the rest, so search wider than the ordinary
    # window - as far up as this challenge level reaches - and add them until the
    # gap closes. These steps are marked so the reply can point them out.
    if include_unplayed and cumulative < needed and profile.sample_size:
        # these get their own allowance: a route that spent every slot on played charts
        # and still fell short is exactly the case where new charts are worth naming
        room = len(steps) + GAP_STEPS
        low, high = unplayed_window(profile, mode.key)
        fillers = unplayed_plan_options(
            profile, chart_index, played_keys(songs, chart_index), current_version,
            max(0.05, min_feasibility * 0.6), stretch_sigmas, slack, low, high,
        )
        if wanted or floor:
            fillers = [option for option in fillers if allowed(option)]
        while len(steps) < room and cumulative < needed:
            if not take(fillers, False, True):
                break

    return Plan(goal_rating=goal, start_rating=start_rating, steps=steps)
