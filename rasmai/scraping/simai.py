from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import threading
import time

import requests

from rasmai.config import USER_AGENT
from rasmai.engine.simai import distil, parse
from rasmai.engine.simai.features import VERSION
from rasmai.storage.db import sheet_put, sheets_all, source_state_get, source_state_set

logger = logging.getLogger(__name__)

# maiノーツ serves every chart it holds in simai, the notation maimai charts are written in. The
# manifest already says which charts have one, so this only ever asks for a chart it knows is
# there and has not read before. A chart does not change once it has been published, so the crawl
# runs down over time instead of repeating: about 2,900 charts, then a handful per game version.
SITE = "https://mai-notes.com"
CHART_URL = f"{SITE}/data/charts/{{chart}}.txt"
SOURCE = "simai_features"
TIMEOUT = 20

# read this many a run, a second apart, so the site is never asked for more than a page's worth
BATCH = 120
PAUSE = 1.0

# keep what has been read this often. A batch takes two minutes, and holding it all in memory until
# the end means a restart loses the lot and the page shows nothing at all in the meantime.
SAVE_EVERY = 25

# give up the run after this many unanswered requests in a row, so a site that is down is left alone
MISSES = 5

_lock = threading.Lock()


def _stored() -> Dict[str, Any]:
    state = source_state_get(SOURCE) or {}
    payload = str(state.get("payload") or "")
    if not payload:
        return {}
    try:
        held = json.loads(payload)
    except ValueError:
        return {}
    if not isinstance(held, dict) or held.get("v") != VERSION:
        # measured by code that meant something else by these numbers: read them all again
        return {}
    rows = held.get("rows")
    return rows if isinstance(rows, dict) else {}


def _held() -> Dict[str, Any]:
    """The whole stored blob, rows and pace together."""
    state = source_state_get(SOURCE) or {}
    try:
        held = json.loads(str(state.get("payload") or ""))
    except ValueError:
        return {}
    return held if isinstance(held, dict) else {}


def pace() -> float:
    """Charts read a second, as last measured; 0 when nothing has been timed yet."""
    try:
        return float(_held().get("rate") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _save(rows: Dict[str, Any], rate: Optional[float] = None) -> None:
    """Keep the readings, and the pace they were read at so time left can be worked out."""
    blob: Dict[str, Any] = {"v": VERSION, "rows": rows}
    kept = rate if rate else pace()
    if kept:
        blob["rate"] = round(kept, 3)
    source_state_set(SOURCE, payload=json.dumps(blob, separators=(",", ":")))
    _forget()


def fetch_chart(chart_id: str) -> Optional[str]:
    """One chart's simai, or None when the site will not give it.

    :param chart_id: maiノーツ's own id for the chart.
    :type chart_id: str
    :rtype: Optional[str]
    """
    try:
        response = requests.get(CHART_URL.format(chart=chart_id),
                                headers={"User-Agent": USER_AGENT, "Accept": "text/plain"}, timeout=TIMEOUT)
    except requests.RequestException as error:
        logger.info("simai fetch failed: %s", error)
        return None
    if response.status_code != 200:
        return None
    text = response.text
    # the site answers its own index page for an id it does not hold, rather than a 404
    return None if text.lstrip().startswith("<") else text


def read_chart(text: str, expected: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """A chart's measured features, or None when the notation could not be read.

    maiノーツ publishes its own note counts, taken from a wiki rather than from the file it serves,
    so the two disagree on a chart now and then and the disagreement is not always ours: one chart
    is counted there at 954 notes where the file plainly holds 1,549. A count is therefore recorded
    as a measure of agreement rather than used to throw the reading away.

    What is refused is a chart the reader itself could not follow: notation it did not recognise, or
    a file it found nothing in. That is the case where the numbers really would be made up.

    :param text: The chart in simai.
    :type text: str
    :param expected: The chart's row from the manifest, carrying the note split.
    :type expected: Dict[str, Any]
    :rtype: Optional[Dict[str, float]]
    """
    chart = _best(text, int(expected.get("n") or 0))
    if chart is None or not chart.notes or chart.skipped:
        return None
    measured = distil(chart)
    measured["lv"] = float(expected.get("l") or 0)
    published = int(expected.get("n") or 0)
    if published:
        # how far this reading sits from the published count, kept so the gap can be watched
        measured["off"] = round((len(chart.notes) - published) / published, 4)
    return measured


def _best(text: str, published: int):
    """The chart in a served file, picking between them when it holds more than one.

    Which difficulty a section belongs to cannot be read off the notation, so where there is a
    choice the published count settles it: the section nearest that is the one that was asked for.
    """
    from rasmai.engine.simai.parse import sections
    parts = sections(text)
    if len(parts) == 1:
        return parse(parts[0])
    read = [parse(part) for part in parts]
    read = [chart for chart in read if chart.notes] or read
    if not published:
        return max(read, key=lambda chart: len(chart.notes))
    return min(read, key=lambda chart: abs(len(chart.notes) - published))


def disputed(rows: Dict[str, Any], limit: float = 0.02) -> int:
    """How many readings sit further than `limit` from the count maiノーツ publishes."""
    return sum(1 for row in rows.values() if row and abs(float(row.get("off") or 0)) > limit)


def _pending(known: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Charts the manifest says have a file that has not been read yet: (key, chart id, row)."""
    from rasmai.scraping import mai_notes
    out = []
    for key, row in mai_notes.cached_facts().exact.items():
        chart_id = str(row.get("c") or "")
        if chart_id and key not in known:
            out.append((key, chart_id, row))
    return out


def refresh(budget: int = BATCH) -> Dict[str, Any]:
    """Read a few more charts and keep what parsed cleanly; never raises.

    :param budget: Most charts to ask the site for this run.
    :type budget: int
    :rtype: Dict[str, Any]
    """
    with _lock:
        known = _stored()
        # the repository first: it holds most of the game in one clone, and what it does not hold
        # is what the site is asked for
        try:
            from rasmai.scraping import simai_bulk
            if simai_bulk.load(known):
                _save(known)
        except Exception:
            logger.exception("simai: reading the chart repository failed, carrying on with the site")
        waiting = _pending(known)
        if not waiting:
            return known
        read = refused = missed = 0
        started = time.monotonic()
        logger.info("simai: reading %d of the %d charts still to read", min(budget, len(waiting)), len(waiting))
        for key, chart_id, row in waiting[:budget]:
            text = fetch_chart(chart_id)
            if text is None:
                # the site is not answering. A chart that was never fetched is left pending on
                # purpose, so stop rather than walk the whole list against a site that is down.
                missed += 1
                if missed >= MISSES:
                    logger.info("simai: %s stopped answering, leaving the rest for next time", SITE)
                    break
            else:
                missed = 0
                sheet_put(key, chart_id, text)
                measured = read_chart(text, row)
                if measured is None:
                    refused += 1
                    known[key] = {}           # read once, understood poorly: do not ask again
                else:
                    read += 1
                    known[key] = measured
                if (read + refused) % SAVE_EVERY == 0:
                    _save(known, (read + refused) / max(1e-6, time.monotonic() - started))
            time.sleep(PAUSE)
        _save(known, (read + refused) / max(1e-6, time.monotonic() - started) if (read + refused) else None)
        logger.info("simai: read %d, could not trust %d, %d charts still to read",
                    read, refused, max(0, len(waiting) - read - refused))
        return known if (read or refused) else {}


def remeasure() -> int:
    """Measure every stored chart again, from the notation already held, without asking the site.

    Called when the measures change meaning: the stored readings are thrown away by their version
    stamp, but the charts they were taken from are still here, so the crawl does not start over.

    :returns: How many charts were measured again.
    :rtype: int
    """
    from rasmai.scraping import mai_notes
    facts = mai_notes.cached_facts().exact
    with _lock:
        known = _stored()
        measured = 0
        for key, sheet in sheets_all():
            if key in known:
                continue
            row = facts.get(key)
            if row is None:
                continue
            reading = read_chart(sheet, row)
            known[key] = reading if reading is not None else {}
            measured += 1
        if measured:
            _save(known)
            logger.info("simai: measured %d charts again from the copies already held", measured)
        return measured


_memo: Tuple[float, Optional[Dict[str, Any]], Optional[Dict[str, float]]] = (0.0, None, None)
_loose: Tuple[Optional[int], Dict[str, Any]] = (None, {})


def _forget() -> None:
    global _memo
    _memo = (0.0, None, None)


def cached() -> Tuple[Dict[str, Any], Dict[str, float]]:
    """The measured charts and the level each measure has to clear; never fetches.

    :rtype: Tuple[Dict[str, Any], Dict[str, float]]
    """
    global _memo
    checked, rows, levels = _memo
    if rows is not None and levels is not None and time.monotonic() - checked < 300:
        return rows, levels
    from rasmai.engine.simai import thresholds
    rows = _stored()
    levels = thresholds(row for row in rows.values() if row)
    _memo = (time.monotonic(), rows, levels)
    return rows, levels


def _loosely(rows: Dict[str, Any]) -> Dict[str, Any]:
    """The readings keyed by a title stripped of spacing and width, built once per set of rows."""
    global _loose
    stamp, index = _loose
    if stamp == id(rows) and index:
        return index
    from rasmai.engine.analysis.charts import loose_title
    index = {}
    for key, row in rows.items():
        title, _, rest = key.partition("|")
        folded = loose_title(title)
        if folded:
            index.setdefault(f"{folded}|{rest}", row)
    _loose = (id(rows), index)
    return index


def chart_traits(key: Tuple[str, str, str]) -> List[Tuple[str, str]]:
    """What the notes themselves say a chart asks for, or nothing when it has not been read.

    The exact title first, then the same match the chart table already falls back on. maimai writes
    a title with different spacing and width from the sites that catalogue it, and matching those
    exactly reached 62% of what a player has played where the looser match reaches 95%.

    :param key: The chart, as ``(title, type, difficulty)``.
    :type key: Tuple[str, str, str]
    :rtype: List[Tuple[str, str]]
    """
    from rasmai.engine.analysis.charts import loose_title
    from rasmai.engine.simai import traits
    rows, levels = cached()
    if not levels:
        return []
    title, chart_type, difficulty = key
    row = rows.get(f"{str(title).casefold()}|{chart_type}|{difficulty}")
    if row is None:
        folded = loose_title(str(title))
        row = _loosely(rows).get(f"{folded}|{chart_type}|{difficulty}") if folded else None
    return traits(row, levels) if row else []


def progress() -> Dict[str, int]:
    """How far the crawl has got, for the developer page."""
    rows = _stored()
    trusted = sum(1 for row in rows.values() if row)
    try:
        waiting = len(_pending(rows))
    except Exception:
        waiting = 0
    from rasmai.storage.db import sheets_held
    try:
        held = sheets_held()
    except Exception:
        held = {"charts": 0, "bytes": 0}
    rate = pace()
    return {"read": trusted, "refused": len(rows) - trusted, "waiting": waiting,
            "disputed": disputed(rows),
            "sheets": held["charts"], "sheetBytes": held["bytes"],
            "rate": round(rate, 3), "eta": int(waiting / rate) if rate and waiting else 0,
            "checked_at": str((source_state_get(SOURCE) or {}).get("checked_at") or "")}


def due() -> bool:
    """Whether there is anything left to read at all."""
    try:
        return bool(_pending(_stored()))
    except Exception:
        return False
