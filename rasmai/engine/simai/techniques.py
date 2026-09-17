from typing import Dict, List, Sequence

from rasmai.engine.simai.parse import Note

# Techniques the community has names for, found in the note stream rather than taken from a tag.
# Everything here works on struck notes in time order: a slide's body is not struck, it is followed,
# so it is left out and only the star that fires it counts.
RING = 8

# Rotation took three goes. A slide that travels far round the ring and a run of slides continuing
# the same way round both failed against the charts the editors tag for it, and were dropped. What
# works is the plain reading: struck notes stepping round the ring without turning back, which runs
# 1.8 times higher on the charts tagged 速い回転 and 1.6 on 遅い回転. That is "circles" below.

# two notes this close are one movement rather than two: a sixteenth at 180 BPM is 0.083s
TOGETHER = 0.18

# and a run holds together while its gaps stay this even
EVEN = 0.35

# how many notes a run needs before it is that technique rather than a coincidence
TRILL_RUN = 4
JACK_RUN = 3
STREAM_RUN = 8

# and an axis trill needs this many before the button being held can be told from a coincidence
AXIS_RUN = 5

# two buttons this far apart are not a rocking motion but a reach across the machine
SCATTER_APART = 3

# a slide that loops away from the ring and back, rather than crossing it in a line
LOOPS = ("pp", "qq", "p", "q", "s", "z")

# one slide taking this many times longer than the one beside it is two hands on two rhythms
SPEED_APART = 2.0

# and a trill is walking round rather than scattering while each note stays this near the one
# two before it
TRAVEL_STEP = 2

def _struck(notes: Sequence[Note]) -> List[Note]:
    """The notes a hand has to strike, in time order; a slide is followed, not struck."""
    return [n for n in notes if n.kind != "slide"]


def _runs(notes: Sequence[Note]) -> List[List[Note]]:
    """Stretches of notes played fast enough and evenly enough to be one movement."""
    out: List[List[Note]] = []
    run: List[Note] = []
    last = 0.0
    for note in notes:
        gap = note.time - run[-1].time if run else 0.0
        if run and gap <= TOGETHER and gap > 1e-6 and (not last or abs(gap - last) <= last * EVEN):
            run.append(note)
            last = gap
        else:
            if len(run) > 1:
                out.append(run)
            run = [note]
            last = 0.0
    if len(run) > 1:
        out.append(run)
    return out


def _alternating(run: Sequence[Note]) -> bool:
    """A B A B: two places, swapped every note."""
    spots = [n.position for n in run]
    return len(set(spots)) == 2 and all(spots[i] != spots[i + 1] for i in range(len(spots) - 1))


def _same_spot(run: Sequence[Note]) -> bool:
    return len({n.position for n in run}) == 1


def _axis(run: Sequence[Note]) -> bool:
    """One hand pinned to a button while the other moves about: 1 3 1 4 1 5.

    It reads as a trill, and it is one, but the hand that stays put is doing something different
    from the hand that travels, which is why the editors give it a name of its own.
    """
    spots = [n.position for n in run]
    if len(spots) < AXIS_RUN:
        return False
    for offset in (0, 1):
        held, other = spots[offset::2], spots[1 - offset::2]
        if len(held) >= 3 and len(set(held)) == 1 and len(set(other)) > 1 and held[0] not in other:
            return True
    return False


def _chains(slides: Sequence[Note]) -> int:
    """Slides that carry on from one another: a star ending where the next begins.

    That is one movement continued rather than two started, which is what the editors call a
    single-stroke slide.
    """
    chained = 0
    run: List[Note] = []
    for note in slides:
        if run and run[-1].end == note.position and note.time - run[-1].time <= 1.5:
            run.append(note)
        else:
            chained += len(run) if len(run) >= 2 else 0
            run = [note]
    return chained + (len(run) if len(run) >= 2 else 0)


# a walk round the ring is this many notes before it is going somewhere rather than wandering, and
# each step stays under this much of the ring and comes no slower than this
CIRCLE_RUN = 5
CIRCLE_STEP = 2
CIRCLE_GAP = 0.5


def _apart(a: str, b: str) -> int:
    """Ring steps between two buttons, the short way round; 0 when either is a pad."""
    if not (a.isdigit() and b.isdigit()):
        return 0
    step = abs(int(a) - int(b))
    return min(step, RING - step)


def _step(a: str, b: str) -> int:
    """Which way round the ring the hand moved, and how far; 0 when either is a pad."""
    if not (a.isdigit() and b.isdigit()):
        return 0
    step = (int(b) - int(a)) % RING
    return step - RING if step > RING // 2 else step


def _trill_kind(run: Sequence[Note]) -> str:
    """Which sort of alternation a run is: stationary, travelling, scattered, or none of them.

    A stationary trill rocks between the same two buttons. A travelling one keeps alternating while
    the pair walks round the cabinet. A scattered one alternates across buttons that are nowhere
    near each other, so the hands cross the whole machine rather than rock in place.
    """
    spots = [n.position for n in run]
    if len(spots) < TRILL_RUN or any(spots[i] == spots[i + 1] for i in range(len(spots) - 1)):
        return ""
    if not all(s.isdigit() for s in spots):
        return ""
    if len(set(spots)) == 2:
        return "scatter" if _apart(spots[0], spots[1]) >= SCATTER_APART else "stationary"
    # more than two places: it is a trill that walks when the hand keeps reversing, each note near
    # the one two before it. A run that never reverses is not a trill at all, it is a stream going
    # round the ring, and reading it as one put a fifth of every stream in the trill column.
    steps = [_step(spots[i], spots[i + 1]) for i in range(len(spots) - 1)]
    if not all(step and (step > 0) != (steps[i + 1] > 0) for i, step in enumerate(steps[:-1])):
        return ""
    if all(_apart(spots[i], spots[i + 2]) <= TRAVEL_STEP for i in range(len(spots) - 2)):
        return "travelling"
    return ""


def _circles(struck: Sequence[Note]) -> int:
    """Notes stepping round the ring the same way for long enough to be a turn of the machine."""
    spun = 0
    walk: List[Note] = []
    for note in struck:
        step = _step(walk[-1].position, note.position) if walk else 0
        was = _step(walk[-2].position, walk[-1].position) if len(walk) > 1 else step
        if (walk and note.time - walk[-1].time <= CIRCLE_GAP and step and abs(step) <= CIRCLE_STEP
                and (step > 0) == (was > 0)):
            walk.append(note)
            continue
        spun += len(walk) if len(walk) >= CIRCLE_RUN else 0
        walk = [note]
    return spun + (len(walk) if len(walk) >= CIRCLE_RUN else 0)


def _over_slides(runs: Sequence[Sequence[Note]], slides: Sequence[Note]) -> int:
    """Trills played while a slide from earlier is still travelling.

    One hand is following the star and cannot help, so the trill is being played by the other hand
    on its own. That is a different thing from the same trill with both hands free.
    """
    busy = 0
    for run in runs:
        if not _trill_kind(run):
            continue
        start, end = run[0].time, run[-1].time
        if any(s.duration > 0 and s.time <= end and s.time + s.duration >= start for s in slides):
            busy += len(run)
    return busy


def _crossed(slides: Sequence[Note]) -> int:
    """Looping slides on screen at the same time as one another.

    A loop on its own is a shape to follow. Two of them overlapping is where the arms have to cross,
    which is what the magic-circle charts are named for.
    """
    loops = [s for s in slides if s.duration > 0 and any(loop in s.shape for loop in LOOPS)]
    return sum(1 for a, b in zip(loops, loops[1:]) if b.time < a.time + a.duration - 1e-3)


def _mixed_speed(slides: Sequence[Note]) -> int:
    """Slides travelling at once at speeds too different to hold one rhythm between the hands."""
    mixed = 0
    for a, b in zip(slides, slides[1:]):
        if a.duration <= 0 or b.duration <= 0 or b.time >= a.time + a.duration - 1e-3:
            continue
        quick, slow = sorted((a.duration, b.duration))
        if slow >= quick * SPEED_APART:
            mixed += 1
    return mixed


def techniques(notes: Sequence[Note]) -> Dict[str, float]:
    """How much of a chart is each named technique, as a share of its notes.

    Every number is a share so a long chart and a short one can be compared, and so the measures sit
    beside the others without a scale of their own.

    :param notes: Every note in the chart, in time order.
    :type notes: Sequence[Note]
    :rtype: Dict[str, float]
    """
    total = len(notes)
    if not total:
        return {}
    struck = _struck(notes)
    slides = [n for n in notes if n.kind == "slide"]
    runs = _runs(struck)
    trill = jack = stream = stationary = scatter = axis = 0
    for run in runs:
        if _axis(run):
            axis += len(run)
        if _same_spot(run) and len(run) >= JACK_RUN:
            jack += len(run)
            continue
        kind = _trill_kind(run)
        if kind:
            trill += len(run)
            if kind == "stationary":
                stationary += len(run)
            elif kind == "scatter":
                scatter += len(run)
        elif len(run) >= STREAM_RUN:
            stream += len(run)
    # a gallop is a long-short limp rather than an even run: one gap about twice the next, again
    # and again
    gallop = 0
    times = [n.time for n in struck]
    gaps = [b - a for a, b in zip(times, times[1:])]
    for i in range(len(gaps) - 2):
        one, two, three = gaps[i], gaps[i + 1], gaps[i + 2]
        if not (0 < one <= 0.5 and 0 < two <= 0.5 and 0 < three <= 0.5):
            continue
        if 1.6 <= one / two <= 3.4 and 1.6 <= three / two <= 3.4:
            gallop += 1
    chained = _chains(slides)
    # touch pads walked in sequence, three or more in a row
    pads = [n for n in struck if n.kind in ("touch", "touch_hold")]
    sweep = sum(len(run) for run in _runs(pads) if len(run) >= 3)
    # pads struck at the same moment, close enough together that a flat hand takes the lot
    moments: Dict[float, List[Note]] = {}
    for pad in pads:
        moments.setdefault(round(pad.time, 3), []).append(pad)
    cluster = sum(len(group) for group in moments.values() if len(group) >= 3)
    # the fan slide, which leaves one star and arrives as three
    wifi = sum(1 for n in slides if "w" in n.shape)
    # the star struck, notes played over the top of it, and only then the slide setting off: the
    # arrangement the editors name after ウミユリ海底譚
    when = [n.time for n in struck]
    delayed = sum(1 for s in slides if s.wait > 1e-3
                  and any(s.time + 1e-3 < t < s.time + s.wait - 1e-3 for t in when))
    return {
        "trills": trill / total,
        "jacks": jack / total,
        "streams": stream / total,
        "gallops": gallop / total,
        "chainedSlides": chained / total,
        "touchSweeps": sweep / total,
        "circles": _circles(struck) / total,
        "delayedSlides": delayed / total,
        "stationaryTrills": stationary / total,
        "axisTrills": axis / total,
        "scatterTrills": scatter / total,
        "touchClusters": cluster / total,
        "wifiSlides": wifi / total,
        "trillsOverSlides": _over_slides(runs, slides) / total,
        "crossedLoops": _crossed(slides) / total,
        "mixedSpeedSlides": _mixed_speed(slides) / total,
    }
