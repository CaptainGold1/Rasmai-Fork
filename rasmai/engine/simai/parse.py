from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
import re

# simai is the notation maimai charts are written in. A chart is a run of beat slots separated by
# commas; (120) sets the tempo, {8} sets how much of a bar a comma advances, and everything else is
# a note. The ring buttons are 1 to 8 clockwise from the top right, touch areas are A to E.
TOUCH_AREAS = "ABCDE"

# longest first, so "pp" is read before "p"
SHAPES: Tuple[str, ...] = ("pp", "qq", "-", "^", "<", ">", "v", "V", "p", "q", "s", "z", "w")

SHAPE_CHARS = "-^<>vVpqszw"

# a firework on a touch note, a star's appearance, and a head that is not struck: none of them
# change what the hand has to do, so they are read and dropped
DECORATIONS = "f$?!"

# a slash joins notes into one moment; a backtick does the same for notes written a hair apart
JOINERS = "/`"


@dataclass
class Note:
    """One thing the player has to do, placed in time."""

    time: float                  # seconds from the first beat
    kind: str                    # tap | hold | slide | touch | touch_hold
    position: str                # "1".."8" around the ring, or "A3" / "C" for a touch area
    duration: float = 0.0        # seconds a hold is held down, or a slide takes to travel
    shape: str = ""              # the path a slide follows, one letter per corner it turns
    end: str = ""                # where a slide finishes
    brk: bool = False            # a break note, worth more and punished harder
    ex: bool = False
    each: int = 1                # how many notes are struck at this moment, this one included


@dataclass
class Chart:
    """A parsed chart: every note in time order, and how long they run for."""

    notes: List[Note] = field(default_factory=list)
    bpm: float = 0.0
    seconds: float = 0.0
    tempo_changes: int = 0

    def counts(self) -> Dict[str, int]:
        """The note split the way maimai counts it, so it can be checked against a source that knows.

        A break is counted as a break whatever it is played on, and a touch hold counts as a hold.

        :rtype: Dict[str, int]
        """
        out = {"tap": 0, "hold": 0, "slide": 0, "touch": 0, "break": 0}
        for note in self.notes:
            if note.brk:
                out["break"] += 1
            elif note.kind == "touch_hold":
                out["hold"] += 1
            elif note.kind in out:
                out[note.kind] += 1
        return out


def _duration(spec: str, bpm: float) -> float:
    """How long a hold is held or a slide travels, in seconds.

    simai writes this four ways: ``[x:y]`` as a fraction of a whole note at the song's tempo,
    ``[bpm#x:y]`` at a tempo of its own, ``[#total]`` in seconds, and ``[wait##travel]`` where the
    star sits still before it sets off. Only the travelling part asks anything of the hand, so that
    is what comes back.

    :param spec: The bracketed length, with or without its brackets.
    :type spec: str
    :param bpm: The tempo in force where the note sits.
    :type bpm: float
    :rtype: float
    """
    spec = spec.strip("[]")
    try:
        if "##" in spec:
            spec = spec.partition("##")[2]
            return _duration(spec, bpm) if ":" in spec else float(spec)
        if spec.startswith("#"):
            return float(spec[1:])
        if "#" in spec:
            head, _, rest = spec.partition("#")
            bpm = float(head) or bpm
            spec = rest
        if ":" not in spec:
            return float(spec)
        divisor, _, count = spec.partition(":")
        return (float(count) * 4.0 / float(divisor)) * (60.0 / bpm) if bpm else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse(text: str) -> Chart:
    """Every note in a simai chart, with the second it falls on.

    :param text: The chart as maiノーツ serves it.
    :type text: str
    :rtype: Chart
    """
    text = re.sub(r"\|\|.*", "", text)
    text = re.sub(r"\s+", "", text)
    if text.endswith("E"):
        text = text[:-1]              # a chart is ended with a lone E, which is not a touch note
    chart = Chart()
    bpm, divisor, clock = 0.0, 4.0, 0.0
    index: int = 0
    slot: List[Note] = []

    def flush() -> None:
        nonlocal slot
        # only struck notes count towards an each. A slide and the star that fires it land in the
        # same slot but are one gesture, not two things hit at once.
        struck = max(1, sum(1 for note in slot if note.kind != "slide"))
        for note in slot:
            note.each = struck
        chart.notes.extend(slot)
        slot = []

    while index < len(text):
        char = text[index]
        if char == "(":
            close = text.find(")", index)
            if close < 0:
                break
            try:
                bpm = float(text[index + 1:close])
            except ValueError:
                pass
            chart.tempo_changes += 1
            chart.bpm = chart.bpm or bpm
            index = close + 1
        elif char == "{":
            close = text.find("}", index)
            if close < 0:
                break
            spec = text[index + 1:close]
            try:
                divisor = float(spec[1:] if spec.startswith("#") else spec) or divisor
            except ValueError:
                pass
            index = close + 1
        elif char == ",":
            flush()
            clock += (4.0 / divisor) * (60.0 / bpm) if bpm and divisor else 0.0
            index += 1
        elif char in JOINERS:
            index += 1                # both join a note to the moment before it
        else:
            notes, moved = _note(text, index, clock, bpm)
            slot.extend(notes)
            index = moved if moved > index else index + 1
    flush()
    chart.seconds = clock
    return chart


def _note(text: str, index: int, clock: float, bpm: float) -> Tuple[List[Note], int]:
    """One note and everything hanging off it, from `index`; the notes it makes and where it ended."""
    char = text[index]
    if char in TOUCH_AREAS:
        position = char
        index += 1
        if index < len(text) and text[index].isdigit():
            position += text[index]
            index += 1
        kind = "touch"
    elif char.isdigit():
        position = char
        index += 1
        kind = "tap"
    else:
        return [], index + 1
    brk = ex = False
    held = 0.0
    slides: List[Note] = []
    while index < len(text):
        char = text[index]
        if char == "b":
            brk = True
            index += 1
        elif char == "x":
            ex = True
            index += 1
        elif char in DECORATIONS:
            index += 1
        elif char == "h":
            kind = "touch_hold" if kind == "touch" else "hold"
            index += 1
        elif char == "[":
            close = text.find("]", index)
            if close < 0:
                break
            held = _duration(text[index:close + 1], bpm)
            index = close + 1
        elif char == "*":
            index += 1                # another slide leaving the same star
        elif char in SHAPE_CHARS:
            note, index = _slide(text, index, clock, bpm, position)
            slides.append(note)
        else:
            break
    if kind == "hold" and held == 0.0 and slides:
        kind = "tap"                  # the h belonged to the slide, not to the star
    return [Note(clock, kind, position, held, "", "", brk, ex)] + slides, index


def _slide(text: str, index: int, clock: float, bpm: float, position: str) -> Tuple[Note, int]:
    """A slide, however many corners it turns.

    A slide written with several shapes in a row, such as ``5^2p8[8:5]``, is one star travelling a
    longer path and judged once at the end, so it is one note rather than one per corner.
    """
    corners: List[Tuple[str, str]] = []
    while index < len(text) and text[index] in SHAPE_CHARS:
        shape = next(sh for sh in SHAPES if text.startswith(sh, index))
        index += len(shape)
        end = ""
        while index < len(text) and text[index].isdigit():
            end += text[index]
            index += 1
        corners.append((shape, end))
    travel = 0.0
    brk = ex = False
    for _ in range(2):                # the break mark sits on either side of the length
        while index < len(text) and text[index] in "bx":
            brk = brk or text[index] == "b"
            ex = ex or text[index] == "x"
            index += 1
        if index < len(text) and text[index] == "[":
            close = text.find("]", index)
            if close < 0:
                break
            travel = _duration(text[index:close + 1], bpm)
            index = close + 1
    return Note(clock, "slide", position, travel, "".join(sh for sh, _ in corners),
                corners[-1][1] if corners else "", brk, ex), index


def note_split(chart: Chart) -> Dict[str, Any]:
    """The parsed counts in the shape the rest of the bot keys a note mix by."""
    counts = chart.counts()
    return {"n": len(chart.notes), "t": counts["tap"], "h": counts["hold"],
            "s": counts["slide"], "u": counts["touch"], "b": counts["break"]}
