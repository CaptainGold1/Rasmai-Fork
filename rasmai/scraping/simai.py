from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import threading
import time

import requests

from rasmai.config import USER_AGENT
from rasmai.engine.simai import distil, parse
from rasmai.engine.simai.features import VERSION
from rasmai.storage.db import source_state_get, source_state_set

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


def _save(rows: Dict[str, Any]) -> None:
    source_state_set(SOURCE, payload=json.dumps({"v": VERSION, "rows": rows}, separators=(",", ":")))
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
    """A chart's measured features, or None when the reading cannot be trusted.

    maiノーツ publishes its own count of the taps, holds, slides, touches and breaks on a chart.
    That count is worked out from the same file by someone else's code, so it is an independent
    answer: when the parse here disagrees with it, the parse is wrong somewhere and the chart is
    dropped rather than have numbers nobody checked go into the model.

    :param text: The chart in simai.
    :type text: str
    :param expected: The chart's row from the manifest, carrying the note split.
    :type expected: Dict[str, Any]
    :rtype: Optional[Dict[str, float]]
    """
    chart = parse(text)
    if not chart.notes:
        return None
    counts = chart.counts()
    for mine, theirs in (("tap", "t"), ("hold", "h"), ("slide", "s"), ("touch", "u"), ("break", "b")):
        if counts[mine] != int(expected.get(theirs) or 0):
            return None
    if len(chart.notes) != int(expected.get("n") or 0):
        return None
    measured = distil(chart)
    measured["lv"] = float(expected.get("l") or 0)
    return measured


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
        waiting = _pending(known)
        if not waiting:
            return known
        read = refused = missed = 0
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
                measured = read_chart(text, row)
                if measured is None:
                    refused += 1
                    known[key] = {}           # read once, understood poorly: do not ask again
                else:
                    read += 1
                    known[key] = measured
            time.sleep(PAUSE)
        _save(known)
        logger.info("simai: read %d, could not trust %d, %d charts still to read",
                    read, refused, max(0, len(waiting) - read - refused))
        return known if (read or refused) else {}


_memo: Tuple[float, Optional[Dict[str, Any]], Optional[Dict[str, float]]] = (0.0, None, None)


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


def chart_traits(key: Tuple[str, str, str]) -> List[Tuple[str, str]]:
    """What the notes themselves say a chart asks for, or nothing when it has not been read.

    :param key: The chart, as ``(title, type, difficulty)``.
    :type key: Tuple[str, str, str]
    :rtype: List[Tuple[str, str]]
    """
    from rasmai.engine.simai import traits
    rows, levels = cached()
    if not levels:
        return []
    title, chart_type, difficulty = key
    row = rows.get(f"{str(title).casefold()}|{chart_type}|{difficulty}")
    return traits(row, levels) if row else []


def progress() -> Dict[str, int]:
    """How far the crawl has got, for the developer page."""
    rows = _stored()
    trusted = sum(1 for row in rows.values() if row)
    try:
        waiting = len(_pending(rows))
    except Exception:
        waiting = 0
    return {"read": trusted, "refused": len(rows) - trusted, "waiting": waiting,
            "checked_at": str((source_state_get(SOURCE) or {}).get("checked_at") or "")}


def due() -> bool:
    """Whether there is anything left to read at all."""
    try:
        return bool(_pending(_stored()))
    except Exception:
        return False
