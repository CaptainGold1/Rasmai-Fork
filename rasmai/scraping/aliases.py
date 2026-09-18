from datetime import datetime, timedelta
from typing import Any, Dict, List
import json
import logging
import threading
import time

import requests

from rasmai.config import USER_AGENT
from rasmai.engine.analysis.charts import loose_title
from rasmai.storage.db import source_state_get, source_state_set

logger = logging.getLogger(__name__)

# maimai.party's search aliases: the names people actually type for a song when they do not type its
# title. dxrating gives us the community's short forms, and this covers the rest - the romanisations
# and translations of a Japanese title, "+boy" and "plus male" for "+♂", "Crazy Nation 2" for
# "#狂った民族2". Measured against what we already hold, 1,171 of its spellings were ones no other
# source gave us.
#
# The file says of itself: "Search aliases only; not chart mappings or game availability guarantees."
# That is exactly what it is used for here - finding a song someone is looking for, never deciding
# what a chart is or where it can be played.
URL = "https://raw.githubusercontent.com/arussin/maimai-chart-browser/main/src/maimai_intelligence/assets/song-aliases.json"
SOURCE = "party_aliases"
TIMEOUT = 60

# the file changes when its author publishes a revision, which is rarely; a week between looks costs
# one conditional request and usually a 304
TTL = timedelta(days=7)

_lock = threading.Lock()
_memo: tuple = (0.0, None)


def _key(title: str) -> str:
    """The title as this table is keyed by it.

    Usually the folded title the rest of the bot matches on. That strips everything that is not a
    letter or a kana, which leaves nothing at all for a song called "+♂" - and that is exactly the
    song whose aliases are worth having, since nobody can type its title. Those fall back to the
    title itself, lowercased.
    """
    folded = loose_title(str(title))
    return folded or str(title).strip().casefold()


def _load(state: Dict[str, Any]) -> Dict[str, List[str]]:
    """The stored table, keyed by folded title."""
    try:
        held = json.loads(str(state.get("payload") or ""))
    except ValueError:
        return {}
    return held if isinstance(held, dict) else {}


def distil(payload: Any) -> Dict[str, List[str]]:
    """The file reduced to what is used: the spellings to search by, under the folded title.

    :param payload: The file as it was served.
    :type payload: Any
    :rtype: Dict[str, List[str]]
    """
    rows = (payload or {}).get("entries") if isinstance(payload, dict) else None
    out: Dict[str, List[str]] = {}
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        title, aliases = row[0], row[2]          # row[1] is the artist, which is not searched here
        folded = _key(title)
        if not folded or not isinstance(aliases, list):
            continue
        kept = [str(a) for a in aliases if str(a).strip()]
        if kept:
            out.setdefault(folded, []).extend(kept)
    return out


def refresh(force: bool = False) -> Dict[str, List[str]]:
    """Re-read the alias file when the stored copy is a week old; never raises.

    :param force: Fetch even when the copy held is current.
    :type force: bool
    :rtype: Dict[str, List[str]]
    """
    state = source_state_get(SOURCE) or {}
    held = _load(state)
    if held and not force:
        try:
            if datetime.now() - datetime.fromisoformat(state["checked_at"]) < TTL:
                return held
        except (ValueError, KeyError):
            pass
    with _lock:
        headers = {"User-Agent": USER_AGENT}
        if held and state.get("etag"):
            headers["If-None-Match"] = str(state["etag"])
        try:
            response = requests.get(URL, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as error:
            logger.info("aliases: %s did not answer, keeping the copy held: %s", URL, error)
            return held
        if response.status_code == 304:
            source_state_set(SOURCE, etag=str(state.get("etag") or ""))
            return held
        if response.status_code != 200:
            logger.info("aliases: %s answered %d, keeping the copy held", URL, response.status_code)
            return held
        try:
            table = distil(response.json())
        except ValueError:
            logger.info("aliases: the file did not read as JSON, keeping the copy held")
            return held
        if not table:
            return held
        source_state_set(SOURCE, etag=response.headers.get("ETag", ""),
                         payload=json.dumps(table, ensure_ascii=False, separators=(",", ":")))
        global _memo
        _memo = (0.0, None)
        logger.info("aliases: %d songs have another name to search by", len(table))
        return table


def cached() -> Dict[str, List[str]]:
    """The stored table; never fetches. Re-read from the database at most every five minutes.

    :rtype: Dict[str, List[str]]
    """
    global _memo
    checked, table = _memo
    if table is not None and time.monotonic() - checked < 300:
        return table
    table = _load(source_state_get(SOURCE) or {})
    _memo = (time.monotonic(), table)
    return table


def aliases_for(title: str) -> List[str]:
    """Every other name this song is searched by, or nothing when it has none.

    :param title: The song title.
    :type title: str
    :rtype: List[str]
    """
    folded = _key(title)
    return list(cached().get(folded, [])) if folded else []
