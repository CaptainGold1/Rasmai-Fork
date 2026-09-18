from typing import Any, Dict, Iterable, List, Sequence, Tuple

from rasmai.engine.simai.parse import Chart, Note
from rasmai.engine.simai.techniques import techniques

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
    # the fan is not a loop: it leaves one star and arrives as three, and it is counted on its own
    # as wifiSlides, so it is no longer folded in here
    spins = sum(1 for n in slides if any(loop in n.shape for loop in LOOPS))
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
        **techniques(notes),
    }


# What each measured feature is called when a chart sits in the top quarter of the game for it.
# Only the demanding side is named: a chart light on slides asks nothing of the hand for them.
#
# A fourth entry sets a fixed bar instead of a quarterly one, for a measure most charts score zero
# on: three charts in four never change tempo, so the top quarter of them is still zero and a
# quartile would name every chart in the game or none of it.
#
# Every measure read from the notes themselves is put through two gates before it is named here.
# It has to rise with a chart's level, or it is measuring easiness; and where maiノーツ's editors
# tag charts for the thing it claims to find, it has to run higher on those charts, which is the
# nearest thing to an answer key there is.
#
# Both gates were run again over 1,350 charts read out of the cached repository, across every level
# rather than only the hard end, because a pattern is introduced somewhere and gets denser from
# there: that is what "rises with level" is meant to catch. Level correlation, then the tag:
#
#   streams          +0.61  乱打 4.1x          circles          +0.60  速い回転 2.9x
#   delayedSlides    +0.58  ウミユリ配置 5.0x   trills           +0.55  トリル 5.1x
#   chainedSlides    +0.54  (no tag with a big enough sample)
#   gallops          +0.51  ハネリズム 7.3x     wifiSlides       +0.48  (no tag; the fan slide is
#   touchSweeps      +0.43  (see below)                                one letter and unmistakable)
#   trillsOverSlides +0.41  混フレ 3.1x        stationaryTrills +0.40  トリル 5.3x
#   touchClusters    +0.31  タッチ複合 3.2x     axisTrills       +0.27  軸押しトリル 20.0x
#   crossedLoops     +0.26  (魔法陣 is on five charts here, too few to judge on)
#   scatterTrills    +0.18  トリル 6.2x        mixedSpeedSlides +0.17  スライド難 10.5x
#   jacks            +0.03  縦連 1.9x
#
# jacks is the weak one: it barely rises with level, and it is kept because the tag it is checked
# against is unambiguous and it ran 3.3x higher on those charts among level 12 and above.
#
# Three of these - gallops, chainedSlides and touchClusters - were measured and left unnamed when
# the gate was run over 272 charts at level 12 and above alone, where they are flat. Over the whole
# game they rise clearly. Both readings are true: they tell a level 6 chart from a level 13 one, and
# they do not tell two level 13 charts apart.
#
# "longHolds" stays measured and unnamed: a hold over a second long marks a sparse chart, not a hard
# one, and what makes a hold hard is busyHands.
#
# Rotation had to be rewritten. "spins" reads the slide shapes, and on 272 charts at level 12 and
# above it falls with level (-0.27) and runs lower on the charts tagged 速い回転 than off them
# (0.62x), so it was naming something that is not rotation. "circles" reads the notes instead, and
# passes both gates.
#
# The last two came from the maimai chart browser's detector definitions, read against the same
# 3,712 charts of ours the manifest describes. Both cleared the gates on their own tags:
#
#   repeatedHeads  +0.39  連続同始点(8分未満) 11.6x (23 charts)
#   returnSlides   +0.31  往復スライド 8.5x (11 charts)
#
# Its third slide-head form, heads swapping between two buttons, rises with level harder than either
# (+0.45) but 連続（交互） is on eight charts here. Eight is under the ten every other measure was
# checked against, so it is not measured: a number that cannot be checked is not worth storing.
#
# "spins" (-0.27), "each" (-0.24) and "turnarounds" (-0.10) were named before the gates existed and
# are measured and unnamed now: all three fall with level over the hard charts, so a chart scoring
# high on them was being called demanding for being easy. They are still stored, so naming one again
# costs a line here rather than another crawl.
DEMANDS: Tuple[Tuple[str, str, str, float], ...] = (
    ("quickSlides", "slide", "fast slides", 0.0),
    ("multiTouch", "touch", "multi-touch", 0.0),
    ("busyHands", "pattern", "both hands at once", 0.0),
    ("peak", "density", "bursts", 0.0),
    ("reach", "pattern", "reaching across the screen", 0.0),
    ("tempoChanges", "tempo", "tempo changes", 1.0),
    ("streams", "pattern", "long streams", 0.0),
    ("trills", "pattern", "trills", 0.0),
    ("jacks", "pattern", "jacks", 0.0),
    ("touchSweeps", "touch", "touch sweeps", 0.0),
    ("circles", "pattern", "spinning round the ring", 0.0),
    ("delayedSlides", "slide", "delayed slides", 0.0),
    ("stationaryTrills", "pattern", "trills on the spot", 0.0),
    # a tenth of charts have one at all, so three quarters of the game scores zero and a quartile
    # would be zero with it. This bar is one full run in a chart of about a thousand notes, which is
    # the point at which the chart is asking for the thing rather than happening to contain it.
    ("scatterTrills", "pattern", "trills across the screen", 0.004),
    ("axisTrills", "pattern", "trills against a held button", 0.0),
    ("wifiSlides", "slide", "fan slides", 0.0),
    ("gallops", "pattern", "a bouncing rhythm", 0.0),
    ("chainedSlides", "slide", "chained slides", 0.0),
    ("touchClusters", "touch", "touch clusters", 0.0),
    ("trillsOverSlides", "pattern", "a trill over a slide", 0.0),
    ("crossedLoops", "slide", "overlapping loop slides", 0.0),
    # a fifth of hard charts have a mismatched pair at all, so the quartile of it is zero and the
    # trait could never be named. One pair in a chart of about a thousand notes is the bar.
    ("mixedSpeedSlides", "slide", "slides at different speeds", 0.001),
    ("repeatedHeads", "slide", "slides fired from one spot", 0.0),
    ("returnSlides", "slide", "a slide traced straight back", 0.0),
)

# a chart has to be in the top quarter of the game on a measure before that measure is named,
# the same bar the note mix has to clear
CUT = 0.75

# and the quarter is taken over charts at this level and above, as the note mix bands are
HARD = 12.0

# kept beside a reading but not measured from the notes: the chart's level, and how far the reading
# sits from the count its source publishes
BOOKKEEPING = ("lv", "off")

# bumped whenever a measure changes meaning, so stored readings taken by older code are dropped
# rather than compared against levels they were never measured for. The charts themselves are kept,
# so a bump costs a re-read of what is already held and not another crawl.
VERSION = 6


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
            if key not in BOOKKEEPING:
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
