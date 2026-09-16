from typing import Dict

WEIGHTS = {"tap": 1, "hold": 2, "slide": 3, "touch": 1, "break": 5}      # shares of the 100% each note is worth


def note_losses(notes: Dict[str, Dict[str, int]], achievement: float,
                bonus_apart: bool = False) -> Dict[str, float]:
    """Percent of achievement lost per note type, summing to what was missing from 101%.

    The arithmetic follows maimai-score-details by SpiritsUnite (Apache-2.0, see THIRD_PARTY_NOTICES.md).
    A break is worth five shares plus an equal slice of the 1% bonus; a great keeps 80% of a note, a good
    50%, a break good 40% and a break miss nothing.

    Only a critical perfect earns a break its whole slice of the bonus: a plain perfect earns half.
    That slice is lost by anyone not hunting criticals, on a run with nothing else wrong with it, so
    `bonus_apart` puts it under "bonus" rather than letting it read as a break gone wrong.

    :param notes: Judgement counts per note type, as the play detail page lists them.
    :type notes: Dict[str, Dict[str, int]]
    :param achievement: The play's achievement.
    :type achievement: float
    :param bonus_apart: Whether the break bonus is reported on its own rather than charged to breaks.
    :type bonus_apart: bool
    :rtype: Dict[str, float]
    """
    counts = {kind: notes.get(kind) or {} for kind in WEIGHTS}
    total = sum(WEIGHTS[kind] * sum(int(v) for v in row.values()) for kind, row in counts.items())
    if total <= 0:
        return {}
    base = 100.0 / total
    breaks = sum(int(v) for v in counts["break"].values())
    lost: Dict[str, float] = {}
    for kind, row in counts.items():
        if not row:
            continue
        great, good, miss = int(row.get("great", 0)), int(row.get("good", 0)), int(row.get("miss", 0))
        if kind == "break":
            lost[kind] = good * 3 * base + miss * 5 * base
        else:
            lost[kind] = WEIGHTS[kind] * base * (great / 5 + good / 2 + miss)
    # the slice of the 1% each break keeps: all of it for a critical, half for a perfect, and the
    # rest as maimai-score-details has it
    bonus = 0.0
    if breaks:
        for judged, kept in (("perfect", 0.5), ("great", 0.4), ("good", 0.3), ("miss", 0.0)):
            bonus += int(counts["break"].get(judged, 0)) * (1.0 - kept) / breaks
    if "break" in lost:
        # anything the counts do not explain is a break's, since the page does not show what a
        # break scored beyond its judgement
        bonus += max(0.0, 101.0 - sum(lost.values()) - bonus - achievement)
    if bonus_apart:
        if bonus:
            lost["bonus"] = bonus
    elif "break" in lost:
        lost["break"] += bonus
    return lost
