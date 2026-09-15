import math
import re
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# (minimum achievement, rank name, rating coefficient) - the official DX table
RANK_TABLE: List[Tuple[float, str, float]] = [
    (100.5, "SSS+", 22.4),
    (100.0, "SSS", 21.6),
    (99.5, "SS+", 21.1),
    (99.0, "SS", 20.8),
    (98.0, "S+", 20.3),
    (97.0, "S", 20.0),
    (94.0, "AAA", 16.8),
    (90.0, "AA", 15.2),
    (80.0, "A", 13.6),
    (75.0, "BBB", 12.8),
    (70.0, "BB", 12.4),
    (60.0, "B", 12.0),
    (50.0, "C", 10.4),
    (0.0, "D", 9.5),
]

# Scores exactly one unit under a rank boundary use their own coefficient.
BORDERLINE_COEFFICIENTS: Dict[float, float] = {
    100.4999: 22.2, 99.9999: 21.4, 99.4999: 21.0, 98.9999: 20.6, 96.9999: 17.6, 59.9999: 11.2,
}

ACHIEVEMENT_CAP = 100.5

# How far above their own best the model lets a good run sit, in sigmas. Zero: the centre of a
# prediction never sits above a score the player has already proved, because assuming improvement
# without evidence is what made targets look cheap. A run above the best is still perfectly
# possible, it just costs the spread; and a chart whose history shows real improvement is lifted
# afterwards by that history rather than by an assumption. Measured over 246 recorded runs, moving
# this from 0.3 to 0 called the exact rank right 64% of the time instead of 61% on runs that beat
# the player's best, and 42% instead of 39% on runs that did not.
BEST_HEADROOM = 0.0

# Targets worth aiming for, best first.
RANK_TARGETS: List[Tuple[str, float]] = [
    ("SSS+", 100.5),
    ("SSS", 100.0),
    ("SS+", 99.5),
    ("SS", 99.0),
    ("S+", 98.0),
    ("S", 97.0),
    ("AAA", 94.0),
    ("AA", 90.0),
]

@dataclass(frozen=True)
class Challenge:
    """How far above a player's usual scores the targets sit."""
    key: str
    label: str
    sigmas: float            # target ceiling: expected + sigmas * spread (0 = 50% odds, 0.67 = 25%, 1.3 = 10%, 2.2 = 1.5%)
    min_feasibility: float   # drop targets with lower odds
    slack: float             # how far past the best nearby score an S+ target may sit
    plan_min_feasibility: float
    plan_sigmas: float
    new_floor: float         # /new: lowest acceptable first-pass estimate
    new_reach: float         # /new: how far past the hardest cleared constant to look
    pick: str = "value"      # which rank to chase: "likely" (best odds), "value" (gain x odds) or "gain"

CHALLENGES: Dict[str, Challenge] = {
    "easy": Challenge("easy", "Easier", 0.35, 0.3, 0.5, 0.35, 0.4, 97.0, -0.7, pick="likely"),
    "balanced": Challenge("balanced", "Balanced", 1.0, 0.16, 1.0, 0.2, 1.0, 94.0, 0.3, pick="value"),
    "hard": Challenge("hard", "Challenging", 1.3, 0.08, 2.0, 0.1, 1.8, 92.0, 0.8, pick="gain"),
    "extreme": Challenge("extreme", "Long shots", 2.2, 0.03, 3.0, 0.04, 2.6, 90.0, 1.3, pick="gain"),
}

def challenge_for(key: Optional[str]) -> Challenge:
    return CHALLENGES.get(str(key or "balanced"), CHALLENGES["balanced"])

def rank_for(accuracy: float) -> str:
    for minimum, name, _coefficient in RANK_TABLE:
        if accuracy >= minimum:
            return name
    return "D"

def rating_coefficient(accuracy: float) -> float:
    for borderline, coefficient in BORDERLINE_COEFFICIENTS.items():
        if abs(accuracy - borderline) < 5e-5:
            return coefficient
    for minimum, _name, coefficient in RANK_TABLE:
        if accuracy >= minimum:
            return coefficient
    return RANK_TABLE[-1][2]

def calculate_rating(constant: float, accuracy: float) -> int:
    if not (math.isfinite(constant) and math.isfinite(accuracy)):
        return 0      # a score that never parsed is worth nothing, not a crash
    if constant <= 0 or accuracy <= 0:
        return 0
    capped = min(accuracy, ACHIEVEMENT_CAP)
    return int(math.floor(constant * (capped / 100.0) * rating_coefficient(capped)))

def accuracy_for_rating(constant: float, wanted_rating: int) -> Optional[float]:
    """Lowest achievement that scores at least `wanted_rating` on this chart.

    :param constant: The chart's internal difficulty constant.
    :type constant: float
    :param wanted_rating: The rating the achievement has to reach.
    :type wanted_rating: int
    :returns: The achievement needed, or ``None`` when the rating is out of reach.
    :rtype: Optional[float]
    """
    if constant <= 0:
        return None
    bands = list(reversed(RANK_TABLE))  # lowest rank first
    for index, (minimum, _name, coefficient) in enumerate(bands):
        band_top = bands[index + 1][0] if index + 1 < len(bands) else ACHIEVEMENT_CAP
        needed = wanted_rating * 100.0 / (constant * coefficient)
        if needed < minimum:
            needed = minimum
        if needed <= band_top + 1e-9 and needed <= ACHIEVEMENT_CAP + 1e-9:
            # Guard against floor() rounding leaving us one point short.
            candidate = min(ACHIEVEMENT_CAP, round(needed, 4))
            while candidate <= ACHIEVEMENT_CAP and calculate_rating(constant, candidate) < wanted_rating:
                candidate = round(candidate + 0.0001, 4)
            if candidate <= ACHIEVEMENT_CAP and calculate_rating(constant, candidate) >= wanted_rating:
                return candidate
    return None

_normal_cdf = statistics.NormalDist().cdf

def parse_constant(raw: Any) -> float:
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    match = re.match(r"(\d+)(\+?)", text)
    if not match:
        return 0.0
    base = float(match.group(1))
    return base + (0.6 if match.group(2) else 0.0)

def version_major(raw: Any) -> int:
    text = str(raw or "").strip()
    if len(text) < 2 or not text[:2].isdigit():
        return 0
    return int(text[:2])
