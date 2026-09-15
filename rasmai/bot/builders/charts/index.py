from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import io
import threading
import discord
from discord import app_commands

from rasmai.engine import analysis
from rasmai.engine.analysis import DIFFICULTY_ORDER, ChartIndex, ChartRef, loose_title
from rasmai.romaji import loanword, skeleton
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.state.snapshots import chart_key
from rasmai.scraping.otoge import CachedOtogeDB
from rasmai.scraping import dxdata, wiki
from rasmai.config import WIKI_VIDEOS


TYPE_ORDER = {"std": 0, "dx": 1}


LEVEL_PATTERN = ("1", "2", "3", "4", "5", "6", "7", "7+", "8", "8+", "9", "9+", "10", "10+", "11", "11+",
                 "12", "12+", "13", "13+", "14", "14+", "15")


_shared_index: Optional[ChartIndex] = None
_build_lock = threading.Lock()      # one build at a time; a reader that arrives meanwhile waits for it rather than starting another


_records: Dict[str, Dict[str, Any]] = {}      # database title -> raw otoge-db record


# otoge-db version codes, first three digits
VERSION_NAMES = {
    "100": "maimai", "110": "maimai PLUS", "120": "GreeN", "130": "GreeN PLUS", "140": "ORANGE", "150": "ORANGE PLUS",
    "160": "PiNK", "170": "PiNK PLUS", "180": "MURASAKi", "185": "MURASAKi PLUS", "190": "MiLK", "195": "MiLK PLUS",
    "199": "FiNALE", "200": "maimai DX", "205": "DX PLUS", "210": "Splash", "215": "Splash PLUS", "220": "UNiVERSE",
    "225": "UNiVERSE PLUS", "230": "FESTiVAL", "235": "FESTiVAL PLUS", "240": "BUDDiES", "245": "BUDDiES PLUS",
    "250": "PRiSM", "255": "PRiSM PLUS", "260": "CiRCLE", "265": "CiRCLE PLUS", "270": "MAGiCAL",
}


_DESIGNER_KEYS = {"basic": "bas", "advanced": "adv", "expert": "exp", "master": "mas", "remaster": "remas"}


_titles: List[str] = []


def refresh_shared_index() -> None:
    """Rebuild the shared index from the database as it now is, whole before anyone can read it."""
    with _build_lock:
        _build()


def _build() -> None:
    # every table is built to the side and swapped in as one object, so a command answered on another
    # thread meanwhile reads a complete index, the old one or the new one, never a half-filled table
    global _shared_index, _titles, _records
    db = CachedOtogeDB()
    index = analysis.build_chart_index(db.songs_data)
    _titles = sorted({c.title for c in index.values()}, key=str.casefold)
    _build_search(db.songs_data, index)
    records: Dict[str, Dict[str, Any]] = {}
    for record in db.songs_data.values():
        records.setdefault(str(record.get("title", "")), record)
    _records = records
    _shared_index = index


def shared_index() -> ChartIndex:
    """Chart database for lookups that do not need the user's scores.

    :rtype: ChartIndex
    """
    if _shared_index is None:
        with _build_lock:
            if _shared_index is None:
                _build()
    return _shared_index      # type: ignore[return-value]


def song_record(title: str) -> Dict[str, Any]:
    """The raw database record for a title: reading, BPM, version code, designers, wiki link.

    :param title: The song title.
    :type title: str
    :rtype: Dict[str, Any]
    """
    shared_index()
    return _records.get(title, {})


def version_name(record: Dict[str, Any]) -> str:
    code = str(record.get("version", "") or "").strip()
    return VERSION_NAMES.get(code[:3], f"v{code[:2]}" if len(code) >= 2 else "")


def chart_designer(record: Dict[str, Any], ref: ChartRef) -> str:
    if ref.designer:
        return ref.designer      # built into the index, from otoge-db for standard charts and dxrating for DX
    stem = _DESIGNER_KEYS.get(ref.difficulty, "")
    key = f"{'dx_' if ref.chart_type == 'dx' else ''}lev_{stem}_designer"
    value = str(record.get(key, "") or "").strip()
    return value if value and value != "-" else ""


def all_titles() -> List[str]:
    shared_index()
    return _titles


# title -> search keys: the title itself, its reading, the wiki's English name, and romaji skeletons of all of them
_search: Dict[str, Tuple[str, ...]] = {}


_search_bones: Dict[str, Tuple[str, ...]] = {}     # loanword skeletons, so "telepathy" finds テレパシ


_aliases: Dict[str, str] = {}                      # database title -> the wiki's name for it, when it differs (モニタリング -> Monitoring)


_songs_data_ref: Dict[str, Dict[str, Any]] = {}


# title -> the people credited on it: the artist, and every charter across its difficulties. Kept
# apart from the title keys so a song never loses its place to something merely charted by a name
# that reads like the query.
_credits: Dict[str, Tuple[str, ...]] = {}


def _credit_keys(*names: str) -> set:
    """The forms a credited name can be typed as: the name itself, and its romaji skeleton.

    :rtype: set
    """
    keys = set()
    for name in names:
        name = str(name or "").strip()
        if not name or name == "-":
            continue
        keys.update({name.casefold(), loose_title(name), skeleton(name)})
    # a short skeleton ("100" out of 譜面-100号) would match half the database, so only keys with
    # enough in them to mean one person are kept
    return {key for key in keys if len(key) >= 4}


def _build_search(songs_data: Dict[str, Dict[str, Any]], index: Optional[ChartIndex] = None) -> None:
    global _search, _search_bones, _aliases, _songs_data_ref, _credits
    _songs_data_ref = songs_data
    readings: Dict[str, str] = {}
    for record in songs_data.values():
        title = str(record.get("title", "")).strip()
        if title:
            readings.setdefault(title, str(record.get("alt_title", "") or ""))
    # the wiki names Japanese songs in English or romaji; those names become search keys
    # as soon as the wiki's song list has been crawled once
    alias_index = wiki.AliasIndex(wiki.cached_titles()) if WIKI_VIDEOS else None
    table: Dict[str, Tuple[str, ...]] = {}
    bones_table: Dict[str, Tuple[str, ...]] = {}
    aliases: Dict[str, str] = {}
    for title in _titles:
        reading = readings.get(title, "")
        # a title with kanji only romanizes its kana, so its skeleton would be shared by
        # every song with the same kana: rely on the reading for those
        kanji = any("一" <= ch <= "鿿" for ch in title)
        keys = {loose_title(title)} if kanji else {loose_title(title), skeleton(title)}
        bones = set() if kanji else {loanword(title)}
        if reading:
            keys.add(loose_title(reading))
            keys.add(skeleton(reading))
            bones.add(loanword(reading))
        alias = alias_index.find(title, reading) if alias_index else None
        if alias and loose_title(alias) != loose_title(title):
            aliases[title] = alias
            keys.update({loose_title(alias), skeleton(alias)})
            bones.add(loanword(alias))
        # the community's short names from dxrating: "lk" for Latent Kingdom
        for short in dxdata.aliases_for(title):
            keys.update({loose_title(short), skeleton(short)})
        table[title] = tuple(k for k in keys if k)
        bones_table[title] = tuple(b for b in bones if len(b) >= 4)
    _search = table
    _search_bones = bones_table
    _aliases = aliases
    credits: Dict[str, set] = {}
    for chart in (index.values() if index is not None else ()):
        credits.setdefault(chart.title, set()).update(_credit_keys(chart.artist, chart.designer))
    _credits = {title: tuple(sorted(keys)) for title, keys in credits.items() if keys}


def song_alias(title: str) -> str:
    """The wiki's English or romaji name for a song, when it has one that differs from the title.

    :param title: The song title.
    :type title: str
    :rtype: str
    """
    return _aliases.get(title, "")


def _refresh_aliases() -> None:
    """Rebuild the search table once the wiki's song list arrives after the index was built."""
    if not _aliases and WIKI_VIDEOS and _songs_data_ref and wiki.cached_titles():
        # the index goes back in too: it carries the artists and charters, and rebuilding without
        # it would drop every credit the moment the wiki's names arrived
        _build_search(_songs_data_ref, _shared_index)


def search_titles(query: str, limit: int = 25) -> List[str]:
    """Titles matching typed text: the title, its kana reading, the wiki's English name, or romaji of any of them.

    :param query: What the player typed.
    :type query: str
    :param limit: Most entries to return.
    :type limit: int
    :rtype: List[str]
    """
    shared_index()
    _refresh_aliases()
    wanted = (query or "").strip()
    if not wanted:
        return _titles[:limit]
    folded = wanted.casefold()
    loose = loose_title(wanted)
    bones = skeleton(wanted)
    exact: List[str] = []
    starts: List[str] = []
    contains: List[str] = []
    for title, keys in _search.items():
        if title.casefold() == folded:
            exact.insert(0, title)          # the title itself always wins
        elif (loose and loose in keys) or (bones and bones in keys):
            exact.append(title)
        elif any(k.startswith(loose) for k in keys if loose) or any(k.startswith(bones) for k in keys if len(bones) >= 3):
            starts.append(title)
        elif folded in title.casefold() or any(loose in k for k in keys if len(loose) >= 3) or any(bones in k for k in keys if len(bones) >= 4):
            contains.append(title)
    # whoever wrote or charted it. Somebody typing a charter's name in full means that charter, so
    # those land above songs that merely contain the query somewhere in their title; a partial match
    # is a guess and goes last, where it cannot cost a song its place.
    named: List[str] = []
    credited: List[str] = []
    if len(folded) >= 2:
        placed = set(exact) | set(starts) | set(contains)
        for title, keys in _credits.items():
            if title in placed:
                continue
            if folded in keys or (loose and loose in keys):
                named.append(title)
            elif any(folded in key for key in keys):
                credited.append(title)
    ranked = (exact + sorted(starts, key=len) + sorted(named, key=str.casefold)
              + sorted(contains, key=len) + sorted(credited, key=str.casefold))
    if len(ranked) < 5:
        # "tetris" for テトリス (tetorisu), "telepathy" for テレパシ: compare the English and the katakana on one skeleton
        bare = loanword(wanted)
        if len(bare) >= 4:
            seen = set(ranked)
            exact_bones = [title for title, keys in _search_bones.items() if title not in seen and bare in keys]
            near_bones = [title for title, keys in _search_bones.items()
                          if title not in seen and title not in exact_bones and any(k.startswith(bare) for k in keys)]
            ranked.extend(sorted(exact_bones, key=len) + sorted(near_bones, key=len))
    return ranked[:limit]


def _choice_name(title: str) -> str:
    alias = song_alias(title)
    return f"{title} ({alias})"[:100] if alias else title[:100]


async def song_autocomplete(_interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    return [app_commands.Choice(name=_choice_name(t), value=t[:100]) for t in search_titles(current)]


def resolve_title(query: str, index: ChartIndex) -> Optional[str]:
    """The database title a free-text query most likely means.

    :param query: What the player typed.
    :type query: str
    :param index: The chart database to look charts up in.
    :type index: ChartIndex
    :rtype: Optional[str]
    """
    wanted = (query or "").strip()
    if not wanted:
        return None
    available = {c.title for c in index.values()}
    for title in search_titles(wanted, limit=10):
        if title in available:
            return title
    return None


def charts_for(title: str, index: ChartIndex) -> List[ChartRef]:
    refs = [c for c in index.values() if c.title == title and c.difficulty in DIFFICULTY_ORDER]
    refs.sort(key=lambda c: (TYPE_ORDER.get(c.chart_type, 9), DIFFICULTY_ORDER.index(c.difficulty)))
    return refs


def songs_by_key(cached: CachedAnalysis) -> Dict[Tuple[str, str, str], Any]:
    return {chart_key(s): s for s in cached.analyzer.songs}


def loose_key(title: str, chart_type: str, difficulty: str) -> Tuple[str, str, str]:
    """Title-insensitive key: the site strips symbols like ♡ and folds width, the database does not.

    :param title: The song title.
    :type title: str
    :param chart_type: ``"std"`` or ``"dx"``.
    :type chart_type: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: str
    :rtype: Tuple[str, str, str]
    """
    return (loose_title(title), (chart_type or "std").lower(), (difficulty or "").lower())


def songs_by_loose_key(cached: CachedAnalysis) -> Dict[Tuple[str, str, str], Any]:
    return {loose_key(s.name, s.chart_type, s.difficulty_type): s for s in cached.analyzer.songs}


def song_for_chart(loose_map: Dict[Tuple[str, str, str], Any], ref: ChartRef) -> Any:
    return loose_map.get(loose_key(ref.title, ref.chart_type, ref.difficulty))


def jacket_file(cached: Optional[CachedAnalysis], cover: str, filename: str = "jacket.webp") -> Optional[discord.File]:
    """The local jacket for a chart, as an attachment for embed thumbnails.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param cover: The jacket file name.
    :type cover: str
    :param filename: The name to attach the file under.
    :type filename: str
    :rtype: Optional[discord.File]
    """
    if not cover:
        return None
    stem = Path(cover.split("/")[-1].split("?")[0]).stem
    roots = [Path(cached.analyzer.jacket_path)] if cached else []
    roots.append(Path("otoge_cache/jackets"))
    for root in roots:
        for candidate in (root / f"{stem}.webp", root / f"{stem}.png", root / f"{stem}.jpg"):
            if candidate.exists():
                try:
                    return discord.File(io.BytesIO(candidate.read_bytes()), filename=filename)
                except OSError:
                    continue
    return None
