import itertools
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from rasmai.engine.analysis.rating import parse_constant, version_major

DIFFICULTY_ORDER = ["basic", "advanced", "expert", "master", "remaster"]

# otoge-db level keys per (chart_type, difficulty_name)
_LEVEL_KEYS = {
    ("std", "basic"): ("lev_bas_i", "lev_bas", "lev_bas_notes"),
    ("std", "advanced"): ("lev_adv_i", "lev_adv", "lev_adv_notes"),
    ("std", "expert"): ("lev_exp_i", "lev_exp", "lev_exp_notes"),
    ("std", "master"): ("lev_mas_i", "lev_mas", "lev_mas_notes"),
    ("std", "remaster"): ("lev_remas_i", "lev_remas", "lev_remas_notes"),
    ("dx", "basic"): ("dx_lev_bas_i", "dx_lev_bas", "dx_lev_bas_notes"),
    ("dx", "advanced"): ("dx_lev_adv_i", "dx_lev_adv", "dx_lev_adv_notes"),
    ("dx", "expert"): ("dx_lev_exp_i", "dx_lev_exp", "dx_lev_exp_notes"),
    ("dx", "master"): ("dx_lev_mas_i", "dx_lev_mas", "dx_lev_mas_notes"),
    ("dx", "remaster"): ("dx_lev_remas_i", "dx_lev_remas", "dx_lev_remas_notes"),
}

@dataclass
class ChartRef:
    title: str
    chart_type: str          # "std" | "dx"
    difficulty: str          # "basic" ... "remaster"
    constant: float
    level: str
    notes: int
    genre: str
    artist: str
    cover: str
    version: int             # version major, e.g. 26
    intl: bool = True        # playable on the international version
    deleted: bool = False    # removed from the game
    bpm: float = 0.0
    designer: str = ""       # otoge-db credits standard charts only; dxrating fills the DX ones in
    intl_known: bool = False  # whether a source that lists regions per chart, rather than per song, said so
    released: str = ""       # the day the chart arrived, ISO 8601
    locked: bool = False     # the song has to be unlocked before it can be picked at all

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.title.casefold(), self.chart_type, self.difficulty)

def loose_title(title: str) -> str:
    """Key used to match a scraped title against the database.

    :param title: The song title.
    :type title: str
    :returns: The folded title, empty when it holds nothing but symbols.
    :rtype: str
    """
    folded = unicodedata.normalize("NFKC", str(title or "")).casefold()
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿가-힯]+", "", folded)

_stamps = itertools.count(1)


class ChartIndex:
    """Chart lookup keyed by (title, chart type, difficulty), with a loose fallback.

    Every chart is indexed so a scraped score always finds its constant; `playable`
    says whether a chart may be *suggested* to this player (still in the game, and
    released in their region)."""

    def __init__(self, region: Optional[str] = None) -> None:
        # several songs can share a title (two "Link"s), so a key holds every chart that answers to it
        self._exact: Dict[Tuple[str, str, str], List[ChartRef]] = {}
        self._loose: Dict[Tuple[str, str, str], ChartRef] = {}
        self._flat: Optional[List[ChartRef]] = None      # every chart once, built on first use
        self.region = region
        self.stamp = next(_stamps)      # tells one index from the next, where an address would be reused
        self.current_version = 0       # the version the player is on, once their scores reveal it

    def playable(self, chart: ChartRef) -> bool:
        if chart.deleted:
            return False
        # otoge-db tracks the Japanese game, which gets a version months before everyone else, so its
        # region flag lags for charts of the version the player is on and is distrusted there. dxrating
        # lists regions per chart rather than per song and is taken at its word, which is what keeps a
        # Japan-only chart of the current version out of the picks.
        if self.region == "intl" and not chart.intl and (chart.intl_known or not self.current_version or chart.version != self.current_version):
            return False
        return True

    def add(self, chart: ChartRef) -> None:
        # the database holds a song again under its reading ("タナカ" for "田中"), and again in a later
        # source file with the artist reworded or a constant revised, so the same chart arrives more
        # than once. The jacket says whether it is the same song: two songs that merely share a title
        # ("Link", "trust") carry different ones and are both kept. A repeat replaces what is stored,
        # because the files are read oldest first and the last word is the current one.
        self._flat = None
        same = self._exact.setdefault(chart.key, [])
        for position, other in enumerate(same):
            if other.cover == chart.cover if chart.cover else (other.artist == chart.artist and other.constant == chart.constant):
                same[position] = chart
                return
        same.append(chart)
        loose = loose_title(chart.title)
        # a title made only of symbols ("∀", "+♂", the untitled "　") folds to nothing; nothing must not match everything
        if loose:
            self._loose.setdefault((loose, chart.chart_type, chart.difficulty), chart)

    def get(self, key: Tuple[str, str, str], level: Optional[str] = None) -> Optional[ChartRef]:
        """The chart for a key; when several songs share the title, the one whose level agrees with `level` (the site's).

        :param key: The chart, as ``(title, chart type, difficulty)``.
        :type key: Tuple[str, str, str]
        :param level: A displayed level such as ``"13"`` or ``"13+"``.
        :type level: Optional[str]
        :returns: The chart, or ``None`` when nothing matches.
        :rtype: Optional[ChartRef]
        """
        key = (str(key[0]).casefold(), key[1], key[2])     # the entries are folded; a caller need not remember to
        charts = self._exact.get(key)
        if charts:
            if len(charts) > 1 and level:
                wanted = str(level).strip()
                for chart in charts:
                    if str(chart.level).strip() == wanted:
                        return chart
            return charts[0]
        title, chart_type, difficulty = key
        loose = loose_title(title)
        return self._loose.get((loose, chart_type, difficulty)) if loose else None

    def __contains__(self, key: Tuple[str, str, str]) -> bool:
        return self.get(key) is not None

    def _charts(self) -> List[ChartRef]:
        if self._flat is None:
            self._flat = [chart for charts in self._exact.values() for chart in charts]
        return self._flat

    def __len__(self) -> int:
        return len(self._charts())

    def items(self):
        return ((chart.key, chart) for chart in self._charts())

    def values(self):
        return list(self._charts())

def build_chart_index(songs_data: Dict[str, Dict[str, Any]], region: Optional[str] = None) -> ChartIndex:
    """Flatten the otoge-db song table into one entry per chart.

    Region and removal flags are kept on each chart rather than used to drop it,
    so a score the player already has always matches; `ChartIndex.playable`
    keeps unavailable charts out of suggestions.

    :param songs_data: The otoge-db song table, keyed by title.
    :type songs_data: Dict[str, Dict[str, Any]]
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: Optional[str]
    :returns: The index, holding every chart the database lists.
    :rtype: ChartIndex
    """
    index = ChartIndex(region)
    try:
        from rasmai.scraping import dxdata
        known = dxdata.cached().get("sheets") or {}
    except Exception:                    # the index has to build with or without the second source
        known = {}
    for record in songs_data.values():
        raw_title = str(record.get("title", ""))
        title = raw_title.strip() or ("　" if raw_title else "")     # the untitled song's title is one ideographic space
        if not title:
            continue
        deleted = bool(record.get("deleted"))
        intl = str(record.get("intl", "1")) != "0"
        genre = str(record.get("genre", ""))
        artist = str(record.get("artist", ""))
        cover = str(record.get("cover", ""))
        version = version_major(record.get("version"))
        folded = loose_title(title)
        bpm_match = re.search(r"\d+(?:\.\d+)?", str(record.get("bpm", "") or ""))
        bpm = float(bpm_match.group(0)) if bpm_match else 0.0
        for (chart_type, difficulty), (const_key, level_key, notes_key) in _LEVEL_KEYS.items():
            constant = parse_constant(record.get(const_key))
            level = str(record.get(level_key, "") or "")
            if constant <= 0:
                constant = parse_constant(level)
            if constant <= 0:
                continue
            try:
                notes = int(str(record.get(notes_key, "") or 0) or 0)
            except ValueError:
                notes = 0
            designer = str(record.get(const_key.replace("_i", "_designer"), "") or "").strip()
            facts = known.get(f"{folded}|{chart_type}|{difficulty}") or {}
            if designer in ("", "-"):
                designer = str(facts.get("d", ""))
            if not notes and facts.get("n"):
                notes = sum(int(count) for count in facts["n"])
            chart = ChartRef(
                title=title,
                chart_type=chart_type,
                difficulty=difficulty,
                constant=constant,
                level=level,
                notes=notes,
                genre=genre,
                artist=artist,
                cover=cover,
                version=version,
                intl=(facts.get("i", 1) != 0) if facts else intl,
                intl_known=bool(facts),
                deleted=deleted,
                bpm=bpm,
                designer=designer if designer != "-" else "",
                released=str(facts.get("r", "")),
                locked=bool(facts.get("k")),
            )
            index.add(chart)
    return index

def level_floor(level: Optional[str]) -> float:
    """The lowest constant a displayed level covers.

    :param level: A displayed level such as ``"13"`` or ``"13+"``.
    :type level: Optional[str]
    :returns: The lowest constant the level covers, or 0.0 when it is not a level.
    :rtype: float
    """
    span = level_range(level)
    return span[0] if span else 0.0

def constant_span(text: Optional[str]) -> Optional[Tuple[float, float]]:
    """The constants a typed filter covers: a level (``13+``), one constant (``13.2``) or a range (``13.0-13.4``).

    :param text: What the player typed.
    :type text: Optional[str]
    :returns: ``(lowest, highest)`` constant, or ``None`` when the text is none of those.
    :rtype: Optional[Tuple[float, float]]
    """
    raw = str(text or "").strip().replace("～", "-").replace("〜", "-").replace("–", "-").replace("to", "-")
    if not raw:
        return None
    span = level_range(raw)
    if span:
        return span
    match = re.fullmatch(r"(\d{1,2}(?:\.\d)?)\s*-\s*(\d{1,2}(?:\.\d)?)", raw)
    if match:
        low, high = sorted((float(match.group(1)), float(match.group(2))))
        return (low - 1e-6, high + 1e-6)
    match = re.fullmatch(r"\d{1,2}\.\d", raw)
    if match:
        constant = float(raw)
        return (constant - 0.05, constant + 0.05)
    return None


def describe_span(text: Optional[str]) -> str:
    """How a filter reads back to the player: ``level 13+``, ``constant 13.2`` or ``constants 13.0 to 13.4``.

    :param text: What the player typed.
    :type text: Optional[str]
    :rtype: str
    """
    raw = str(text or "").strip()
    if not raw or constant_span(raw) is None:
        return ""
    if level_range(raw):
        return f"level {raw}"
    if re.fullmatch(r"\d{1,2}\.\d", raw):
        return f"constant {raw}"
    low, high = constant_span(raw)
    return f"constants {low + 1e-6:.1f} to {high - 1e-6:.1f}"


def level_range(level: Optional[str]) -> Optional[Tuple[float, float]]:
    """The constants a displayed level spans: 13 is 13.0 to 13.5, 13+ is 13.6 to 13.9; None for anything that is not a level.

    Every chart in the database agrees on this split, so a 13.6 belongs to 13+ and never to 13. The
    game only splits a level in two from 7 upward, so a level 6 covers 6.0 to 6.9 on its own.

    :param level: A displayed level such as ``"13"`` or ``"13+"``.
    :type level: Optional[str]
    :returns: ``(lowest, highest)`` constant, or ``None`` when it is not a level.
    :rtype: Optional[Tuple[float, float]]
    """
    match = re.fullmatch(r"(\d{1,2})(\+?)", str(level or "").strip())
    if not match:
        return None
    base, plus = int(match.group(1)), bool(match.group(2))
    if not 1 <= base <= 15:
        return None
    if base < 7:
        return None if plus else (float(base), base + 0.9)
    return (base + 0.6, base + 0.9) if plus else (float(base), base + 0.5)
