from typing import Any, Dict, List, Optional

from rasmai.engine.analysis import DIFFICULTY_ORDER, ChartRef, level_range


def _facts() -> Dict[str, Dict[str, Any]]:
    try:
        from rasmai.scraping import mai_notes
        return mai_notes.cached_facts()
    except Exception:
        return {}


def _fold(text: str) -> str:
    """A search string with case, spaces, hyphens and brackets taken out, so "slide heavy" finds "slide-heavy"."""
    return "".join(ch for ch in str(text).casefold() if ch.isalnum())


def english_of(tag: str) -> str:
    """The English gloss of a mai-notes tag, or the tag itself when it has none."""
    from rasmai.scraping.mai_notes import PATTERN_ENGLISH
    english = PATTERN_ENGLISH.get(tag, "")
    if not english and tag.endswith("配置"):
        english = f"the pattern from {tag[:-2]}"
    return english or tag


def label_of(tag: str) -> str:
    from rasmai.scraping.mai_notes import pattern_label
    return pattern_label(tag)


def reading_for(cached: Any) -> bool:
    """Whether this player switched chart reading on; False for anyone not linked.

    :param cached: The player's analysis, held in memory.
    :type cached: Any
    :rtype: bool
    """
    return bool(getattr(getattr(cached, "analyzer", None), "reading", False))


def tags_for(chart: ChartRef, reading: bool = False) -> List[Dict[str, Any]]:
    """Every trait the chart carries, each with the key it is searched by.

    A community tag is searched by its Japanese name, so a link made before measured traits
    existed still resolves; a measured one is searched by its English wording, which is also
    what it is shown as.

    :param chart: The chart being read.
    :type chart: ChartRef
    :param reading: Whether traits measured from the chart's own notes join the list.
    :type reading: bool
    :rtype: List[Dict[str, Any]]
    """
    from rasmai.engine.insights import chart_tags
    out = []
    for tag in chart_tags(chart, reading):
        out.append({**tag, "key": tag["label"].split(" (")[0] if tag["community"] else tag["label"]})
    return out


_catalogue_memo: Dict[Any, List[Dict[str, Any]]] = {}


def catalogue(index: Any, reading: bool = False) -> List[Dict[str, Any]]:
    """Every trait in use, with how many playable charts carry it: the community's tags first, then the measured ones.

    :param index: The chart database to look constants and metadata up in.
    :type index: Any
    :rtype: List[Dict[str, Any]]
    """
    stamp = (getattr(index, "stamp", id(index)), len(index), len(_facts()), reading)
    hit = _catalogue_memo.get(stamp)
    if hit is not None:
        return hit
    counts: Dict[str, int] = {}
    meta: Dict[str, Dict[str, Any]] = {}
    for chart in index.values():
        if not index.playable(chart):
            continue
        for tag in tags_for(chart, reading):
            counts[tag["key"]] = counts.get(tag["key"], 0) + 1
            meta.setdefault(tag["key"], tag)
    out = [{"tag": key, "label": meta[key]["label"], "english": english_of(key) if meta[key]["community"] else meta[key]["label"],
            "charts": n, "community": meta[key]["community"], "dimension": meta[key]["dimension"],
            "read": bool(meta[key].get("read"))}
           for key, n in counts.items()]
    out.sort(key=lambda item: (not item["community"], -item["charts"], item["tag"]))
    _catalogue_memo.clear()          # one index at a time; a rebuilt database gets a fresh count
    _catalogue_memo[stamp] = out
    return out


def resolve(query: str, index: Any, reading: bool = False) -> Optional[str]:
    """The tag someone means by `query`: its Japanese name, its English gloss, or a part of either.

    :param query: What the player typed.
    :type query: str
    :param index: The chart database to look constants and metadata up in.
    :type index: Any
    :rtype: Optional[str]
    """
    wanted = _fold(query)
    if not wanted:
        return None
    items = catalogue(index, reading)
    for item in items:
        if wanted in (_fold(item["tag"]), _fold(item["english"]), _fold(item["label"])):
            return item["tag"]
    partial = [item["tag"] for item in items
               if wanted in _fold(item["tag"]) or wanted in _fold(item["english"]) or wanted in _fold(item["label"])]
    return partial[0] if partial else None


def suggest(query: str, index: Any, limit: int = 25, reading: bool = False) -> List[Dict[str, Any]]:
    """Tags matching typed text, for autocomplete; the whole catalogue when nothing is typed.

    :param query: What the player typed.
    :type query: str
    :param index: The chart database to look constants and metadata up in.
    :type index: Any
    :param limit: Most entries to return.
    :type limit: int
    :rtype: List[Dict[str, Any]]
    """
    wanted = _fold(query)
    items = catalogue(index, reading)
    if wanted:
        items = [item for item in items
                 if wanted in _fold(item["tag"]) or wanted in _fold(item["english"]) or wanted in _fold(item["label"])]
    return items[:limit]


def charts_with(index: Any, tag: str, level: Optional[str] = None, difficulty: Optional[str] = None,
                reading: bool = False) -> List[ChartRef]:
    """Playable charts carrying `tag`, hardest first, narrowed to a level or a difficulty when asked.

    :param index: The chart database to look constants and metadata up in.
    :type index: Any
    :param tag: The mai-notes tag, as `resolve` returns it.
    :type tag: str
    :param level: A displayed level such as ``"13+"``, or None for every level.
    :type level: Optional[str]
    :param difficulty: A difficulty tier, or None for every tier.
    :type difficulty: Optional[str]
    :rtype: List[ChartRef]
    """
    span = level_range(level) if level else None
    out: List[ChartRef] = []
    for chart in index.values():
        if chart.difficulty not in DIFFICULTY_ORDER or not index.playable(chart):
            continue
        if not any(item["key"] == tag for item in tags_for(chart, reading)):
            continue
        if span and not (span[0] - 1e-9 <= chart.constant <= span[1] + 1e-9):
            continue
        if difficulty and chart.difficulty != difficulty:
            continue
        out.append(chart)
    out.sort(key=lambda c: (-c.constant, c.title.casefold()))
    return out


def tags_of(chart: ChartRef) -> List[str]:
    row = _facts().get(chart.key)
    return list(row.get("g") or []) if row else []
