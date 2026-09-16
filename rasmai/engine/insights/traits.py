from typing import Any, Dict, List, Optional, Sequence, Tuple

from rasmai.engine.analysis import ChartIndex, ChartRef, PlayProfile
from rasmai.engine.insights.tags import NOT_A_SKILL, _is_technique, chart_traits


TRAIT_MIN_CHARTS = 8         # a group needs this many distinct charts before it is measured at all


TRAIT_CONFIRM_CHARTS = 12    # and this many before a split of the player's own data can confirm it


TRAIT_SPLITS = 3             # random halvings the sign has to survive, both halves each time


_TAG_PENALTY = 10.0          # ridge weight on a tag: shrinks a group of n charts by about n / (n + 10)


_CONTROL_PENALTY = 1e-3


def _trait_observations(scored: Sequence[Any], chart_index: ChartIndex, profile: PlayProfile,
                        recorded_plays: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Every score the player made, as a residual against their own curve with the chart it was on.

    The best on each chart is one observation; every recorded play is another, with the plays
    of one chart sharing one unit of weight so a grinded chart does not outvote the rest."""
    charts: Dict[Tuple[str, str, str], ChartRef] = {}
    out: List[Dict[str, Any]] = []
    for song in scored:
        key = (str(song.name).casefold(), (str(getattr(song, "chart_type", "")).lower() or "std"),
               str(getattr(song, "difficulty_type", "")).lower())
        chart = chart_index.get(key)
        if chart is None:
            continue
        charts[key] = chart
        residual = float(song.accuracy) - profile.expected_for(float(song.difficulty), chart.difficulty)
        if residual < -12:
            continue                  # a dropped run says nothing about the chart's traits
        out.append({"key": key, "chart": chart, "residual": residual, "play": 0, "weight": 1.0})
    plays_by_chart: Dict[Tuple[str, str, str], List[float]] = {}
    for play in recorded_plays or []:
        parts = str(play.get("key", "")).split("|")
        if len(parts) != 3:
            continue
        key = (parts[0], parts[1] or "std", parts[2])
        chart = charts.get(key) or chart_index.get(key)
        if chart is None:
            continue
        charts.setdefault(key, chart)
        residual = float(play.get("achievement") or 0) - profile.expected_for(chart.constant, chart.difficulty)
        if residual < -12:
            continue
        plays_by_chart.setdefault(key, []).append(residual)
    for key, residuals in plays_by_chart.items():
        weight = 1.0 / len(residuals)
        for residual in residuals:
            out.append({"key": key, "chart": charts[key], "residual": residual, "play": 1, "weight": weight})
    return out


class _TraitDesign:
    """The regression laid out once: controls per observation, one tag row per distinct chart.

    A fit is then a matrix solve, and a permutation of the tags is a permutation of the chart
    rows, so the null distribution costs a few dozen solves rather than a few dozen rebuilds."""

    CONTROLS = 5      # intercept, is a play, log plays, constant, carries any pattern tag

    def __init__(self, observations: Sequence[Dict[str, Any]], tags: Sequence[Tuple[str, str]], profile: PlayProfile,
                 reading: bool = False):
        import math
        import numpy as np
        self.np = np
        self.tags = list(tags)
        index = {tag: i for i, tag in enumerate(self.tags)}
        keys = sorted({o["key"] for o in observations}, key=str)
        key_row = {key: i for i, key in enumerate(keys)}
        self.n_keys = len(keys)
        self.tagvec = np.zeros((len(keys), len(self.tags)))
        self.has_pattern = np.zeros(len(keys))
        for o in observations:
            row = key_row[o["key"]]
            if self.tagvec[row].any() or self.has_pattern[row]:
                continue
            for tag in chart_traits(o["chart"], reading):
                if tag[0] == "pattern":
                    self.has_pattern[row] = 1.0
                col = index.get(tag)
                if col is not None:
                    self.tagvec[row, col] = 1.0
        self.key_idx = np.array([key_row[o["key"]] for o in observations])
        mean_constant = sum(o["chart"].constant for o in observations) / len(observations)
        self.controls = np.zeros((len(observations), self.CONTROLS))
        self.controls[:, 0] = 1.0
        self.controls[:, 1] = [float(o["play"]) for o in observations]
        self.controls[:, 2] = [math.log1p(max(0, profile.plays_for(o["key"]))) for o in observations]
        self.controls[:, 3] = [o["chart"].constant - mean_constant for o in observations]
        self.y = np.array([o["residual"] for o in observations])
        self.w = np.array([o["weight"] for o in observations])
        self.penalty = np.full(self.CONTROLS + len(self.tags), _TAG_PENALTY)
        self.penalty[: self.CONTROLS] = _CONTROL_PENALTY

    def fit(self, permutation=None, rows=None):
        """Tag coefficients; `permutation` reassigns every chart's tags to another chart, `rows` restricts the observations."""
        np = self.np
        key_idx = self.key_idx if rows is None else self.key_idx[rows]
        chart_rows = key_idx if permutation is None else permutation[key_idx]
        controls = self.controls if rows is None else self.controls[rows]
        controls = controls.copy()
        controls[:, 4] = self.has_pattern[chart_rows]
        x = np.hstack([controls, self.tagvec[chart_rows]])
        y = self.y if rows is None else self.y[rows]
        w = self.w if rows is None else self.w[rows]
        xtw = x.T * w
        beta = np.linalg.solve(xtw @ x + np.diag(self.penalty), xtw @ y)
        return beta[self.CONTROLS:]


# shuffles of the tags across charts that give each trait its chance level. A p-value can only
# land on k/(n+1), so too few shuffles puts the whole gate on one shuffle's luck: at 80 the only
# value under 0.02 was 1/81, meaning zero of 80 allowed, and real traits on hundreds of charts
# were being refused because a single shuffle beat them. This many resolves the threshold properly
# and settles on the same answer as twice as many, for about half a second per analysis.
TRAIT_PERMUTATIONS = 400


TRAIT_P = 0.02               # a trait's offset has to be rarer than this under shuffled tags


def trait_residuals(scored: Sequence[Any], chart_index: ChartIndex, profile: PlayProfile,
                    recorded_plays: Optional[Sequence[Dict[str, Any]]] = None,
                    reading: bool = False) -> List[Dict[str, Any]]:
    """How far the player's scores sit from their own curve, per chart attribute, from every score they made.

    All tags are fitted together, so tags that ride on the same charts stop counting several
    times, and play count, difficulty and "this chart has pattern tags at all" are held fixed.
    Each trait is then tested against the player's own data two ways: its offset has to be
    larger than all but a few percent of the offsets that shuffled tags produce, and it has to
    keep its sign in both halves of the player's charts, three random splits over. Traits that
    fail stay in the list for the record and are hidden from the lists and the wheel.

    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param scored: The player's charts that carry a score.
    :type scored: Sequence[Any]
    :param recorded_plays: Every stored play, as the history table returns them.
    :type recorded_plays: Optional[Sequence[Dict[str, Any]]]
    :param reading: Whether traits measured from the charts themselves join the community's tags.
    :type reading: bool
    :rtype: List[Dict[str, Any]]
    """
    import numpy as np
    observations = _trait_observations(scored, chart_index, profile, recorded_plays)
    if not observations:
        return []
    charts_by_tag: Dict[Tuple[str, str], set] = {}
    plays_by_tag: Dict[Tuple[str, str], int] = {}
    for o in observations:
        for tag in chart_traits(o["chart"], reading):
            if not _is_technique(*tag):
                continue
            charts_by_tag.setdefault(tag, set()).add(o["key"])
            if o["play"]:
                plays_by_tag[tag] = plays_by_tag.get(tag, 0) + 1
    tags = sorted((tag for tag, keys in charts_by_tag.items() if len(keys) >= TRAIT_MIN_CHARTS), key=str)
    if not tags:
        return []
    design = _TraitDesign(observations, tags, profile, reading)
    full = design.fit()
    # chance level: the same fit with every chart wearing another chart's tags
    exceed = np.zeros(len(tags))
    for seed in range(TRAIT_PERMUTATIONS):
        rng = np.random.default_rng(1000 + seed)
        exceed += np.abs(design.fit(permutation=rng.permutation(design.n_keys))) >= np.abs(full)
    p_values = (exceed + 1.0) / (TRAIT_PERMUTATIONS + 1.0)
    # stability: the same sign out of both halves of the player's charts, every split
    agree = np.ones(len(tags), dtype=bool)
    for seed in range(TRAIT_SPLITS):
        rng = np.random.default_rng(seed)
        half = np.zeros(design.n_keys, dtype=bool)
        half[rng.permutation(design.n_keys)[: design.n_keys // 2]] = True
        for side in (True, False):
            rows = np.nonzero(half[design.key_idx] == side)[0]
            if len(rows) < 8:
                agree[:] = False
                break
            part = design.fit(rows=rows)
            agree &= (np.sign(part) == np.sign(full)) & (np.abs(part) >= 0.1)
    out: List[Dict[str, Any]] = []
    for i, tag in enumerate(tags):
        n = len(charts_by_tag[tag])
        offset = round(float(full[i]), 2)
        verified = bool(agree[i] and p_values[i] <= TRAIT_P and n >= TRAIT_CONFIRM_CHARTS and abs(offset) >= TRAIT_THRESHOLD)
        out.append({
            "dimension": tag[0], "label": tag[1], "offset": offset, "count": n, "plays": plays_by_tag.get(tag, 0),
            "p": round(float(p_values[i]), 3),
            "verified": verified,
            # points one way on the player's data without passing the gate: shown as a hint, never used by the model
            "leaning": bool(not verified and abs(offset) >= TRAIT_LEAN_OFFSET and p_values[i] <= TRAIT_LEAN_P),
        })
    out.sort(key=lambda trait: trait["offset"])
    return out


TRAIT_THRESHOLD = 0.5      # a group has to sit this far from the player's own middle before it is worth naming


TRAIT_LEAN_OFFSET = 0.3    # this far out, and rarer than one in ten under shuffled tags, is worth showing as a lean


TRAIT_LEAN_P = 0.10


RADAR_MIN = 3              # axes a wheel needs before it is drawn


RADAR_FILL = 6             # axes a wheel is filled up to with even traits when confirmed and leaning ones fall short


def notable(axes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The traits worth telling the player about: far enough from their middle, and confirmed on their own data.

    :param axes: The traits the wheel is drawn on.
    :type axes: Sequence[Dict[str, Any]]
    :rtype: List[Dict[str, Any]]
    """
    return [axis for axis in axes if axis.get("verified") and abs(float(axis["offset"])) >= TRAIT_THRESHOLD
            and axis["dimension"] not in NOT_A_SKILL]


def leaning(axes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Traits that lean one way on the player's data without passing the confirmation gate, weakest side first.

    :param axes: Every trait group measured.
    :type axes: Sequence[Dict[str, Any]]
    :rtype: List[Dict[str, Any]]
    """
    return sorted([axis for axis in axes if axis.get("leaning") and not axis.get("verified")
                   and axis["dimension"] not in NOT_A_SKILL], key=lambda axis: float(axis["offset"]))


def even(axes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Traits the player plays no differently from the rest: enough charts to tell, and inside the lean threshold.

    :param axes: Every trait group measured.
    :type axes: Sequence[Dict[str, Any]]
    :rtype: List[Dict[str, Any]]
    """
    return sorted([axis for axis in axes if not axis.get("verified") and not axis.get("leaning")
                   and int(axis.get("count") or 0) >= TRAIT_CONFIRM_CHARTS and abs(float(axis["offset"])) < TRAIT_LEAN_OFFSET
                   and axis["dimension"] not in NOT_A_SKILL],
                  key=lambda axis: -int(axis["count"]))


def practice_for(axis: Dict[str, Any], chart_index: ChartIndex, profile: PlayProfile, scored: Sequence[Any],
                 limit: int = 3) -> List[Dict[str, Any]]:
    """Charts to practise a pattern trait on, inside the player's own working band.

    Charts the player already holds a score on come first, so a rerun shows the change; the
    rest fill in from the hardest down.

    :param axis: The trait, as `trait_residuals` returns it; only a pattern trait has charts to name.
    :type axis: Dict[str, Any]
    :param chart_index: The chart database to look constants and metadata up in.
    :type chart_index: ChartIndex
    :param profile: How the player plays, as measured from their scores.
    :type profile: PlayProfile
    :param scored: The player's charts that carry a score.
    :type scored: Sequence[Any]
    :param limit: Most charts to name.
    :type limit: int
    :rtype: List[Dict[str, Any]]
    """
    if axis.get("dimension") not in ("pattern", "slide", "touch", "density", "tempo", "hold"):
        return []
    from rasmai.engine import patterns
    tag = str(axis["label"]).split(" (")[0]
    low = profile.comfort_constant - 0.5
    high = max(profile.reach_constant, profile.comfort_constant + 0.3) + 0.2
    mine: Dict[Any, Any] = {}
    for song in scored:
        ref = chart_index.get((song.name, song.chart_type, song.difficulty_type), getattr(song, "level", None))
        if ref is not None:
            mine[ref.key] = song
    rows = []
    for chart in patterns.charts_with(chart_index, tag, reading=profile.reading):
        if not (low - 1e-9 <= chart.constant <= high + 1e-9):
            continue
        song = mine.get(chart.key)
        rows.append((0 if song is not None else 1, abs(chart.constant - profile.comfort_constant), chart.title.casefold(), chart, song))
    rows.sort(key=lambda row: row[:3])
    return [{"title": chart.title, "chart_type": chart.chart_type, "difficulty": chart.difficulty, "level": chart.level,
             "constant": chart.constant, "cover": chart.cover,
             "accuracy": float(song.accuracy or 0) if song is not None else None}
            for _played, _constant, _title, chart, song in rows[:limit]]


def radar_axes(axes: Sequence[Dict[str, Any]], limit: int = 8, tentative: bool = True) -> List[Dict[str, Any]]:
    """The axes a radar is drawn on: traits about play (patterns, note mix, tempo, density), both halves of the wheel.

    :param axes: The traits the wheel is drawn on.
    :type axes: Sequence[Dict[str, Any]]
    :param limit: Most entries to return.
    :type limit: int
    :param tentative: Whether leaning traits join the confirmed ones on the wheel, and even ones fill a wheel with too few axes.
    :type tentative: bool
    :rtype: List[Dict[str, Any]]
    """
    pool = [axis for axis in axes if (axis.get("verified") or (tentative and axis.get("leaning"))) and axis["dimension"] not in NOT_A_SKILL]
    if tentative and len(pool) < RADAR_FILL:
        # a wheel with two or three points is barely a shape: the groups the player plays evenly sit on the middle ring and round it out
        fillers = [axis for axis in even(axes) if axis["dimension"] not in NOT_A_SKILL]
        fillers.sort(key=lambda axis: -abs(float(axis["offset"])))
        pool += [{**axis, "filler": True} for axis in fillers[:max(0, RADAR_FILL - len(pool))]]
    if len(pool) < RADAR_MIN:
        return []

    def pick(want: int, best_first: bool) -> List[Dict[str, Any]]:
        ordered = sorted(pool, key=lambda axis: -float(axis["offset"]) if best_first else float(axis["offset"]))
        return [axis for axis in ordered if (float(axis["offset"]) > 0) == best_first][:want]

    half = limit // 2
    chosen = pick(half, True) + pick(limit - half, False)
    if len(chosen) < limit:
        rest = [axis for axis in sorted(pool, key=lambda a: -abs(float(a["offset"]))) if axis not in chosen]
        chosen += rest[:limit - len(chosen)]
    return sorted(chosen, key=lambda axis: -float(axis["offset"]))


def chart_trait_offset(traits: Sequence[Dict[str, Any]], chart: ChartRef, reading: bool = False) -> float:
    """The traits' combined verdict on one chart: negative where the player tends to lose points.

    :param traits: The traits measured from the player's scores.
    :type traits: Sequence[Dict[str, Any]]
    :param chart: The chart being judged.
    :type chart: ChartRef
    :rtype: float
    """
    if not traits:
        return 0.0
    lookup = {(t["dimension"], t["label"]): float(t["offset"]) for t in traits}
    return sum(lookup.get(trait, 0.0) for trait in chart_traits(chart, reading))
