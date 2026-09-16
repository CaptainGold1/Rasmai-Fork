from typing import Any, Dict, Iterable, List, Sequence, Tuple

from rasmai.engine.simai.parse import Chart, Note

# how far apart two ring buttons are, going the short way round: 1 and 8 are neighbours
RING = 8

# a slide that travels in under this many seconds has to be chased rather than followed
QUICK_SLIDE = 0.35

# a hold kept down this long stops being a note and starts being a hand you have lost
LONG_HOLD = 1.0

# loops. A p or q leaves the ring and comes back round, so it reads as a spin rather than a line
LOOPS = ("pp", "qq", "p", "q")


def _gap(a: str, b: str) -> int:
    """How far apart two ring buttons are, the short way round; 0 when either is a touch area."""
    if not (a.isdigit() and b.isdigit()):
        return 0
    apart = abs(int(a) - int(b))
    return min(apart, RING - apart)


def _busy(notes: Sequence[Note]) -> float:
    """The share of notes struck while a hold or a slide from earlier is still running.

    This is the closest the notation gets to naming a one-handed passage: something is already
    pinned under one hand, and the note that arrives has to be taken with what is left.
    """
    running: List[float] = []
    caught = 0
    for note in notes:
        running = [end for end in running if end > note.time + 1e-6]
        if running:
            caught += 1
        if note.duration > 0 and note.kind in ("hold", "touch_hold", "slide"):
            running.append(note.time + note.duration)
    return caught / len(notes) if notes else 0.0


def _peak(notes: Sequence[Note], window: float = 1.0) -> float:
    """The most notes falling inside any one second."""
    times = [note.time for note in notes]
    best = 0
    start = 0
    for end in range(len(times)):
        while times[end] - times[start] > window:
            start += 1
        best = max(best, end - start + 1)
    return float(best)


def features(chart: Chart) -> Dict[str, float]:
    """What a chart asks of the hands, measured from its notes rather than taken on trust.

    Every number is a rate or a share, so a long chart and a short one can be compared.

    :param chart: The parsed chart.
    :type chart: Chart
    :rtype: Dict[str, float]
    """
    notes = chart.notes
    if not notes:
        return {}
    total = len(notes)
    seconds = max(chart.seconds, 1e-6)
    holds = [n for n in notes if n.kind in ("hold", "touch_hold")]
    slides = [n for n in notes if n.kind == "slide"]
    touches = [n for n in notes if n.kind in ("touch", "touch_hold")]
    held_time = sum(n.duration for n in holds)
    travelled = [n.duration for n in slides if n.duration > 0]
    by_moment: Dict[float, List[Note]] = {}
    for note in touches:
        by_moment.setdefault(round(note.time, 3), []).append(note)
    multi = sum(len(group) for group in by_moment.values() if len(group) > 1)
    spins = sum(1 for n in slides if any(loop in n.shape for loop in LOOPS) or "w" in n.shape)
    # a slide written with more than one corner that turns back on itself: out and back again
    turns = sum(1 for n in slides if len(n.shape) > 1 and _gap(n.position, n.end) <= 2)
    jumps = [_gap(a.position, b.position) for a, b in zip(notes, notes[1:])
             if a.position.isdigit() and b.position.isdigit() and b.time > a.time]
    return {
        "perSecond": total / seconds,
        "peak": _peak(notes),
        "each": sum(1 for n in notes if n.each > 1) / total,
        "heldShare": min(held_time / seconds, 1.0),
        "longHolds": sum(1 for n in holds if n.duration >= LONG_HOLD) / total,
        "slideSpeed": (sum(travelled) / len(travelled)) if travelled else 0.0,
        "quickSlides": (sum(1 for d in travelled if d <= QUICK_SLIDE) / len(travelled)) if travelled else 0.0,
        "multiTouch": multi / total,
        "spins": spins / total,
        "turnarounds": turns / total,
        "reach": (sum(jumps) / len(jumps)) if jumps else 0.0,
        "busyHands": _busy(notes),
        # every chart opens by stating its tempo, so only the markers after the first are changes
        "tempoChanges": float(max(0, chart.tempo_changes - 1)),
    }


# What each measured feature is called when a chart sits in the top quarter of the game for it.
# Only the demanding side is named: a chart light on slides asks nothing of the hand for them.
#
# A fourth entry sets a fixed bar instead of a quarterly one, for a measure most charts score zero
# on: three charts in four never change tempo, so the top quarter of them is still zero and a
# quartile would name every chart in the game or none of it.
#
# Every measure named here rises with a chart's level. "longHolds" is measured and deliberately not
# named: against 651 charts it runs the other way, at -0.43 with level, because a hold over a second
# long is a mark of a sparse chart rather than a hard one. What makes a hold hard is what arrives
# while it is still down, and that is busyHands, which runs at +0.55.
DEMANDS: Tuple[Tuple[str, str, str, float], ...] = (
    ("quickSlides", "slide", "charts with fast slides", 0.0),
    ("spins", "slide", "charts with spins", 0.0),
    ("turnarounds", "slide", "charts with slides that double back", 0.0),
    ("multiTouch", "touch", "charts with multi-touch", 0.0),
    ("busyHands", "pattern", "charts that keep both hands working", 0.0),
    ("each", "pattern", "charts with a lot struck together", 0.0),
    ("peak", "density", "charts with a hard burst", 0.0),
    ("reach", "pattern", "charts that throw you across the screen", 0.0),
    ("tempoChanges", "tempo", "charts that change tempo", 1.0),
)

# a chart has to be in the top quarter of the game on a measure before that measure is named,
# the same bar the note mix has to clear
CUT = 0.75

# and the quarter is taken over charts at this level and above, as the note mix bands are
HARD = 12.0

# bumped whenever a measure changes meaning, so stored readings taken by older code are dropped
# rather than compared against levels they were never measured for
VERSION = 1


def thresholds(rows: Iterable[Dict[str, float]]) -> Dict[str, float]:
    """The level each measure has to clear to count, taken from the charts themselves.

    These are quartiles of whatever has been read so far rather than fixed numbers, so they stay
    honest as the game grows and as more of it is parsed.

    :param rows: The measured features of every chart read.
    :type rows: Iterable[Dict[str, float]]
    :rtype: Dict[str, float]
    """
    columns: Dict[str, List[float]] = {}
    for row in rows:
        # the bar is set by the charts people actually get analysed on. Measured over everything,
        # a Basic chart with four holds in it lands in the top quarter for holds, which is true
        # and useless: an easy chart is not asking for anything.
        if float(row.get("lv") or 0) < HARD:
            continue
        for key, value in row.items():
            if key != "lv":
                columns.setdefault(key, []).append(float(value))
    out: Dict[str, float] = {}
    for key, values in columns.items():
        if len(values) < 40:
            continue                  # too little read to know where the top quarter sits
        values.sort()
        out[key] = values[int(len(values) * CUT)]
    return out


def traits(row: Dict[str, float], levels: Dict[str, float]) -> List[Tuple[str, str]]:
    """The demands a chart makes, as trait labels, from its measured features.

    :param row: One chart's features.
    :type row: Dict[str, float]
    :param levels: What each measure has to clear, as `thresholds` returns them.
    :type levels: Dict[str, float]
    :rtype: List[Tuple[str, str]]
    """
    out: List[Tuple[str, str]] = []
    for key, dimension, label, fixed in DEMANDS:
        level = fixed or levels.get(key) or 0.0
        if level > 0 and float(row.get(key) or 0) >= level:
            out.append((dimension, label))
    return out


def distil(chart: Chart) -> Dict[str, Any]:
    """One chart's features, rounded small enough to keep for every chart in the game."""
    return {key: round(value, 4) for key, value in features(chart).items()}
