from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rasmai.engine.analysis.rating import ACHIEVEMENT_CAP, _normal_cdf, calculate_rating, challenge_for, rank_for
from rasmai.engine.analysis.charts import ChartIndex, constant_span
from rasmai.engine.analysis.profile import PlayProfile
from rasmai.engine.analysis.pools import Best50

@dataclass
class UnplayedPick:
    title: str
    chart_type: str
    difficulty: str
    level: str
    constant: float
    genre: str
    artist: str
    cover: str
    is_new: bool
    expected_accuracy: float    # first-pass estimate
    expected_rank: str
    expected_rating: int
    rating_gain: int            # what it would add to the best-50 at that score
    odds_of_s: float            # chance of at least S (97%) first time
    affinity: float
    score: float
    target_accuracy: float = 0.0   # a strong first pass, as far above the estimate as the challenge level chases
    target_gain: int = 0           # what that pass would add to the best-50

def unplayed_window(profile: PlayProfile, challenge: str = "balanced") -> Tuple[float, float]:
    """Constant range /new searches at a challenge level.

    Easier starts where the player is comfortable; the others start just under
    the hardest constant they score well on. All reach past the hardest chart the
    player has shown they can play (an S, or where the curve still expects one) by
    the level's allowance; a chart they once failed does not move that bound.

    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param challenge: How bold the targets are: ``"easy"``, ``"balanced"``, ``"hard"`` or ``"extreme"``.
    :type challenge: str
    :returns: ``(lowest, highest)`` constant to search.
    :rtype: Tuple[float, float]
    """
    mode = challenge_for(challenge)
    lower = (profile.comfort_constant - 0.5) if mode.pick == "likely" else (profile.reach_constant - 0.7)
    # never reach past the hardest chart the game has: a ceiling of 15.0 must not read as 15.2
    upper = min(profile.search_ceiling + mode.new_reach, profile.chart_ceiling)
    return max(0.0, min(lower, upper)), upper

def focus_traits(profile: PlayProfile) -> List[Dict[str, Any]]:
    """The traits a "lean toward" filter may use: the confirmed ones, and the leanings, since most players have no confirmed one.

    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :rtype: List[Dict[str, Any]]
    """
    from rasmai.engine.insights import leaning
    return list(profile.traits or []) + leaning(profile.trait_axes or [])


def recommend_unplayed(
    songs: Sequence[Any],
    profile: PlayProfile,
    best50: Best50,
    chart_index: ChartIndex,
    current_version: int,
    difficulty: Optional[str] = None,
    limit: int = 15,
    challenge: str = "balanced",
    focus: Optional[str] = None,
    level: Optional[str] = None,
) -> List[UnplayedPick]:
    """Charts the player has never touched that sit inside their range.

    `focus` is "weak" for charts whose traits the player loses points on, "strong"
    for the ones they gain on; the pick is weighted by how much. `level` ("13+") asks
    for that displayed level instead of the challenge level's constant window, and
    the first-pass floor does not apply to it: the player asked to see that level.

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
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: Optional[str]
    :param limit: Most entries to return.
    :type limit: int
    :param challenge: How bold the targets are: ``"easy"``, ``"balanced"``, ``"hard"`` or ``"extreme"``.
    :type challenge: str
    :param focus: ``"weak"`` to lean into the player's weak traits, ``"strong"`` for their strengths.
    :type focus: Optional[str]
    :param level: A displayed level such as ``"13"`` or ``"13+"``.
    :type level: Optional[str]
    :returns: The picks, best first.
    :rtype: List[UnplayedPick]
    """
    if not profile.sample_size:
        return []
    span = constant_span(level) if level else None      # a level, one constant or a range; the window steps aside for it
    wanted_level = bool(span)
    mode = challenge_for(challenge)
    from rasmai.engine.insights import chart_trait_offset
    traits = focus_traits(profile)
    focus = focus if focus in ("weak", "strong") and traits else None
    # scraped titles differ from the database's in spacing and punctuation, so a played
    # chart is remembered under the database key it matches, not under its scraped name
    played: set = set()
    for song in songs:
        key = (
            str(getattr(song, "name", "")).casefold(),
            str(getattr(song, "chart_type", "")).lower() or "std",
            str(getattr(song, "difficulty_type", "")).lower(),
        )
        played.add(key)
        ref = chart_index.get(key)
        if ref is not None:
            played.add(ref.key)

    lower, upper = unplayed_window(profile, mode.key)
    wanted = difficulty.lower().strip() if difficulty else None

    picks: List[UnplayedPick] = []
    for key, chart in chart_index.items():
        if key in played or chart.locked or not chart_index.playable(chart):
            continue
        if wanted:
            if chart.difficulty != wanted:
                continue
        elif chart.difficulty not in ("expert", "master", "remaster"):
            continue
        if span:
            if not (span[0] <= chart.constant <= span[1]):
                continue
        elif not (lower <= chart.constant <= upper):
            continue

        sigma = profile.sigma_at(chart.constant)
        expected = profile.expected_for(chart.constant, chart.difficulty) - 0.35 - 0.4 * sigma
        if expected < mode.new_floor and not wanted_level:
            continue
        expected = min(ACHIEVEMENT_CAP, expected)
        is_new = bool(current_version) and chart.version == current_version
        expected_rating = calculate_rating(chart.constant, expected)
        gain = best50.gain_if(key, is_new, expected_rating)
        odds_s = _normal_cdf((expected - 97.0) / sigma)
        affinity = profile.affinity(chart.chart_type, chart.genre, chart.difficulty)
        trait_offset = chart_trait_offset(traits, chart) if focus else 0.0
        if focus == "weak" and trait_offset > -0.5:
            continue
        if focus == "strong" and trait_offset < 0.5:
            continue
        target = min(ACHIEVEMENT_CAP, expected + mode.sigmas * sigma)
        target_rating = calculate_rating(chart.constant, target)
        target_gain = best50.gain_if(key, is_new, target_rating)
        # the level decides what a pick is judged on, so the three lists actually differ:
        if mode.pick == "likely":
            # charts you will almost certainly S, close to where you are comfortable
            proximity = 1.0 / (1.0 + abs(chart.constant - profile.comfort_constant) / 2.0)
            score = (expected_rating * (0.3 + 0.7 * odds_s) * proximity + 8 * gain) * affinity
        elif mode.pick == "gain":
            # what a strong first pass would pay, so harder charts come forward
            score = (target_rating + 8 * target_gain) * affinity * (0.7 + 0.3 * odds_s)
        else:
            score = (expected_rating + 8 * gain) * affinity * (0.6 + 0.4 * odds_s)
        if focus:
            score *= 1.0 + min(3.0, abs(trait_offset)) * 0.5   # the more the trait matters, the sooner the chart

        picks.append(UnplayedPick(
            title=chart.title, chart_type=chart.chart_type, difficulty=chart.difficulty,
            level=chart.level, constant=chart.constant, genre=chart.genre, artist=chart.artist,
            cover=chart.cover, is_new=is_new,
            expected_accuracy=expected, expected_rank=rank_for(expected), expected_rating=expected_rating,
            rating_gain=gain, odds_of_s=odds_s, affinity=affinity, score=score,
            target_accuracy=target, target_gain=target_gain,
        ))

    # charts at one constant score identically often enough that the order between them would
    # otherwise come out of dictionary order and shuffle between reads; sorting by title first
    # gives every later sort a stable base to keep
    picks.sort(key=lambda pick: pick.title.casefold())

    # Rank coefficients jump at each rank, so any blended score ends up preferring the
    # easiest chart that lands an S. Each level therefore orders the list on its own terms.
    if mode.pick == "likely":
        # the charts you are most likely to S, first-pass estimate and all
        safe = [pick for pick in picks if pick.odds_of_s >= 0.5] or picks
        safe.sort(key=lambda pick: (pick.rating_gain > 0, round(pick.odds_of_s, 1), pick.score, pick.is_new), reverse=True)
        picks = safe
    elif mode.pick == "gain":
        # the hardest charts where an S is still within reach at this level's odds
        reachable = [pick for pick in picks if pick.target_accuracy >= 97.0] or picks
        reachable.sort(key=lambda pick: (pick.target_gain > 0, pick.constant, pick.score, pick.is_new), reverse=True)
        picks = reachable
    else:
        picks.sort(key=lambda pick: (pick.rating_gain > 0, pick.score, pick.is_new, pick.constant), reverse=True)

    # every chart at one constant gets the same first-pass estimate and the same odds, so the score
    # separates them by almost nothing and the list would collapse onto whichever constant wins:
    # twelve rows reading the same difficulty, the same estimate and the same odds, with nothing to
    # choose between them. Each pass spends the window and the genres first and only then loosens,
    # so a short list is filled by relaxing the limits rather than by one constant taking the rest.
    chosen: List[UnplayedPick] = []
    taken: set = set()
    genre_cap, constant_cap = max(2, limit // 3), max(2, limit // 6)
    # the genre limit gives way first: spending the window matters more than spreading the genres,
    # and relaxing both together would let one constant take the whole list on a single-genre pool
    passes = ((genre_cap, constant_cap), (limit, constant_cap), (limit, constant_cap * 2), (limit, limit))
    for genres_allowed, constants_allowed in passes:
        per_genre: Dict[str, int] = {}
        per_constant: Dict[float, int] = {}
        for pick in chosen:
            per_genre[pick.genre] = per_genre.get(pick.genre, 0) + 1
            per_constant[round(pick.constant, 1)] = per_constant.get(round(pick.constant, 1), 0) + 1
        for pick in picks:
            if len(chosen) >= limit:
                break
            mark = (pick.title, pick.chart_type, pick.difficulty)
            constant = round(pick.constant, 1)
            if mark in taken or per_genre.get(pick.genre, 0) >= genres_allowed or per_constant.get(constant, 0) >= constants_allowed:
                continue
            per_genre[pick.genre] = per_genre.get(pick.genre, 0) + 1
            per_constant[constant] = per_constant.get(constant, 0) + 1
            taken.add(mark)
            chosen.append(pick)
        if len(chosen) >= limit:
            break
    return chosen
