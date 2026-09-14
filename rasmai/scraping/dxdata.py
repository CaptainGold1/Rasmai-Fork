from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import threading
import time

import requests

from rasmai.config import USER_AGENT
from rasmai.engine.analysis import loose_title
from rasmai.storage.db import source_state_get, source_state_set

logger = logging.getLogger(__name__)

URL = "https://raw.githubusercontent.com/gekichumai/dxrating/main/packages/dxdata/dxdata.json"      # dxrating, MIT; THIRD_PARTY_NOTICES.md
SOURCE = "dxrating_dxdata"
TTL = timedelta(days=1)
TIMEOUT = 60

# the international version opens each release a season after Japan; a play is dated against
# the version that was actually on the cabinet
# ponytail: one fixed lag; a per-version intl date table if a season's gap ever matters
INTL_LAG = timedelta(days=90)

_lock = threading.Lock()


def distil(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The file reduced to what is used: aliases by folded title, constants per version by chart key, the version dates.

    The aliases are the community's short names ("lk" for Latent Kingdom). The constants are kept per
    version because they get revised, and a play from last year scored against last year's number.
    Each chart also keeps what otoge-db is thin on: who wrote it, whether the international version
    has it, its note split and the day it arrived. The keys are one letter because the table is
    every chart in the game and it is stored as one row.

    :param payload: The data to store or send.
    :type payload: Dict[str, Any]
    :rtype: Dict[str, Any]
    """
    aliases: Dict[str, List[str]] = {}
    constants: Dict[str, Dict[str, float]] = {}
    sheets: Dict[str, Dict[str, Any]] = {}
    for song in payload.get("songs") or []:
        title = str(song.get("title") or "")
        folded = loose_title(title)
        if not folded:
            continue
        names = [str(a) for a in (song.get("searchAcronyms") or []) if a]
        if names:
            aliases.setdefault(folded, []).extend(n for n in names if n not in aliases.get(folded, []))
        for sheet in song.get("sheets") or []:
            chart_type = str(sheet.get("type") or "")
            if chart_type not in ("std", "dx"):
                continue
            key = f"{folded}|{chart_type}|{sheet.get('difficulty')}"
            history = sheet.get("multiverInternalLevelValue") or {}
            if len(set(history.values())) > 1:
                constants[key] = {str(v): float(c) for v, c in history.items() if c}      # only a chart whose constant moved
            facts: Dict[str, Any] = {}
            designer = str(sheet.get("noteDesigner") or "").strip()
            if designer and designer != "-":
                facts["d"] = designer
            if not (sheet.get("regions") or {}).get("intl", True):
                facts["i"] = 0      # available everywhere is the common case, so only absence is written down
            counts = sheet.get("noteCounts") or {}
            if counts.get("total"):
                facts["n"] = [int(counts.get(field) or 0) for field in ("tap", "hold", "slide", "touch", "break")]
            released = str(sheet.get("releaseDate") or "")
            if released:
                facts["r"] = released
            if facts:
                sheets[key] = facts
    versions = [(str(v.get("version") or ""), str(v.get("releaseDate") or ""))
                for v in payload.get("versions") or [] if v.get("releaseDate")]
    return {"aliases": aliases, "constants": constants, "versions": versions, "sheets": sheets}


def fetch(etag: str = "") -> Tuple[str, Optional[Dict[str, Any]], str]:
    """One conditional request for the file: (status, distilled data or None, new etag).

    :param etag: The tag the site gave the copy already held.
    :type etag: str
    :rtype: Tuple[str, Optional[Dict[str, Any]], str]
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        response = requests.get(URL, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as error:
        logger.info("dxrating fetch failed: %s", error)
        return "failed", None, etag
    if response.status_code == 304:
        return "unchanged", None, etag
    if response.status_code != 200:
        logger.info("dxrating answered %s", response.status_code)
        return "failed", None, etag
    try:
        return "changed", distil(response.json()), response.headers.get("ETag", "")
    except (ValueError, TypeError, AttributeError):
        logger.info("dxrating answered something that is not the expected JSON")
        return "failed", None, etag


def refresh(force: bool = False) -> bool:
    """Re-read the file when the stored copy is a day old; True when new data was stored. Never raises.

    :param force: Whether to act even when the stored copy is current.
    :type force: bool
    :rtype: bool
    """
    with _lock:
        state = source_state_get(SOURCE) or {}
        if _load(state) and not force:
            try:
                if datetime.now() - datetime.fromisoformat(state["checked_at"]) < TTL:
                    return False
            except (ValueError, KeyError):
                pass
        status, data, etag = fetch(str(state.get("etag") or ""))
        if status == "changed" and data and data["aliases"]:
            source_state_set(SOURCE, etag=etag, payload=json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            _forget()
            logger.info("dxrating: aliases for %d songs, %d charts with a revised constant", len(data["aliases"]), len(data["constants"]))
            return True
        if status == "unchanged":
            source_state_set(SOURCE)
        return False


def _load(state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(str(state.get("payload") or "")) or {}
    except ValueError:
        return {}


_memo: Tuple[float, Optional[Dict[str, Any]]] = (0.0, None)


def _forget() -> None:
    global _memo
    _memo = (0.0, None)


def cached() -> Dict[str, Any]:
    """The stored copy; never fetches. Re-read from the database at most every five minutes.

    :rtype: Dict[str, Any]
    """
    global _memo
    checked, data = _memo
    if data is not None and time.monotonic() - checked < 300:
        return data
    data = _load(source_state_get(SOURCE) or {})
    _memo = (time.monotonic(), data)
    return data


NOTE_FIELDS = ("t", "h", "s", "u", "b")      # tap, hold, slide, touch, break, the way mai-notes names them


def chart_facts(title: str, chart_type: str, difficulty: str) -> Dict[str, Any]:
    """What dxrating holds for one chart: ``d`` designer, ``i`` region, ``n`` note split, ``r`` release day.

    :param title: The song title.
    :type title: str
    :param chart_type: ``"std"`` or ``"dx"``.
    :type chart_type: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: str
    :rtype: Dict[str, Any]
    """
    folded = loose_title(title)
    return (cached().get("sheets") or {}).get(f"{folded}|{chart_type}|{difficulty}", {}) if folded else {}


def note_split(title: str, chart_type: str, difficulty: str) -> Optional[Dict[str, int]]:
    """A chart's notes by type, keyed the way mai-notes keys them, or None when dxrating has no count.

    :param title: The song title.
    :type title: str
    :param chart_type: ``"std"`` or ``"dx"``.
    :type chart_type: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: str
    :rtype: Optional[Dict[str, int]]
    """
    counts = chart_facts(title, chart_type, difficulty).get("n")
    if not counts or len(counts) != len(NOTE_FIELDS):
        return None
    row = {field: int(value) for field, value in zip(NOTE_FIELDS, counts)}
    row["n"] = sum(row.values())
    return row


def aliases_for(title: str) -> List[str]:
    """The community's short names for a song, by its title.

    :param title: The song title.
    :type title: str
    :rtype: List[str]
    """
    folded = loose_title(title)
    return list((cached().get("aliases") or {}).get(folded, [])) if folded else []


def constant_at(title: str, chart_type: str, difficulty: str, when: datetime, region: str = "intl") -> Optional[float]:
    """The constant a chart had when a play happened, or None when it has never been revised.

    :param title: The song title.
    :type title: str
    :param chart_type: ``"std"`` or ``"dx"``.
    :type chart_type: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: str
    :param when: When the play happened.
    :type when: datetime
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: str
    :rtype: Optional[float]
    """
    data = cached()
    history = (data.get("constants") or {}).get(f"{loose_title(title)}|{chart_type}|{difficulty}")
    if not history:
        return None
    day = (when.replace(tzinfo=None) - (INTL_LAG if region != "jp" else timedelta())).date().isoformat()
    current = None
    for version, released in data.get("versions") or []:
        if released > day:
            break
        if version in history:
            current = history[version]
    return current
