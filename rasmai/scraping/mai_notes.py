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

# maiノーツ (mai-notes.com) is a fan-run maimai chart viewer. It publishes one static manifest
# describing every chart: the note count split by type, and the pattern tags its editors have
# put on a chart ("乱打", "スライド難"). The file carries an ETag, so a check costs one
# conditional request and no bytes when nothing changed.
SITE = "https://mai-notes.com"
MANIFEST_URL = f"{SITE}/data/manifest.json"
SOURCE = "mainotes_charts"
TTL = timedelta(days=1)

# Bumped whenever `distil` keeps a different set of fields. The stored copy is only re-read when
# the site says the manifest changed, so without this a copy distilled by older code would be kept
# for good and never gain the new fields: the site has not changed, only what is wanted from it.
FORMAT = 2
TIMEOUT = 30

_lock = threading.Lock()

DIFFICULTIES = {"BASIC": "basic", "ADVANCED": "advanced", "EXPERT": "expert",
                "MASTER": "master", "Re:MASTER": "remaster"}

# The tags are written the way the maimai community writes them. A short English gloss goes
# beside the Japanese so a reader who does not know the term still learns something; the
# "◯◯配置" tags name a specific song's signature pattern and keep that as their gloss.
PATTERN_ENGLISH = {
    "やべー譜面": "notorious", "練習におすすめ": "good to practice on", "maimai定番ソング": "a maimai standard",
    "局所難": "one hard section", "全体難": "hard throughout", "スコア難": "hard to score",
    "混フレ": "mixed rhythms between hands", "物量": "note volume", "ホールド難": "hold-heavy",
    "スライド難": "hard slides", "ソフラン": "tempo changes", "巻き込み注意": "easy to clip a neighbour",
    "乱打": "streams", "縦連": "jacks", "速いトリル": "fast trills", "微縦連": "short jacks",
    "トリル": "trills", "軸押しトリル": "axis trills", "イーチ難": "hard simultaneous hits",
    "速い回転": "fast rotations", "遅い回転": "slow rotations", "加減速回転": "rotations that change speed",
    "イーチ回転": "rotations hit together", "折り返し": "turnarounds", "速い流し": "fast sweeps",
    "遅い流し": "slow sweeps", "リズム難": "hard rhythms", "ハネリズム": "swing rhythm",
    "タッチ複合": "mixed with touch notes",
    "タップで発射": "slides fired by a tap", "持ち替え": "hand swaps", "一筆書き": "single-stroke slides",
    "連結スライド": "chained slides", "交差": "crossing slides", "魔法陣": "magic-circle slides",
    "連続同始点(8分未満)": "same start point, under 8th", "連続同始点(8分以上)": "same start point, 8th or slower",
    "連続（交互）": "alternating slides", "往復スライド": "slides that double back", "早消し": "slides that vanish early",
    "速度違い": "slides at different speeds", "停止": "stopped slides",
    "ウミユリ配置": "a slide you let go of at the start",
    "タッチ乱打": "touch streams", "タッチ流し": "touch sweeps", "タッチ回転": "touch rotations",
    "タッチ巻き込み": "touch notes easy to clip", "拘束タッチホールD": "touch holds that pin a hand",
    "拘束タッチホールド": "touch holds that pin a hand",
}

# note-type shares that count as notable: the upper quartile of every chart at level 12 and above.
# Only the top side is named. A chart that is light on a note type asks nothing of the player for
# it, so "slide-light" was never a skill of its own, only the other half of "slide-heavy" said twice.
SHARE_BANDS: Tuple[Tuple[str, str, float, str], ...] = (
    ("b", "break", 0.064, "break-heavy"),
    ("s", "slide", 0.145, "slide-heavy"),
    ("u", "touch", 0.070, "touch-heavy"),
    ("h", "hold",  0.094, "hold-heavy"),
)


def pattern_label(tag: str) -> str:
    """A tag as it is shown: the Japanese name the community uses, with an English gloss where one helps.

    A "◯◯配置" tag names the signature pattern of the song it is called after, so it is glossed as one
    rather than translated.

    :param tag: The pattern tag, as mai-notes writes it.
    :type tag: str
    :rtype: str
    """
    english = PATTERN_ENGLISH.get(tag, "")
    if not english and tag.endswith("配置"):
        english = f"the pattern from {tag[:-2]}"
    return f"{tag} ({english})" if english else tag


def distil(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The manifest reduced to what the model uses, keyed "title|type|difficulty".

    The note split, the pattern tags and the id of the chart file are kept; the rest of the
    manifest (top scores, release dates, editor bookkeeping) is dropped so the stored copy
    stays small.

    :param payload: The data to store or send.
    :type payload: Dict[str, Any]
    :rtype: Dict[str, Dict[str, Any]]
    """
    tags = {tag["id"]: str(tag.get("name") or "") for tag in payload.get("tags") or []}
    songs = payload.get("songs") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for chart in payload.get("charts") or []:
        song = songs.get(chart.get("song_id"))
        notes = chart.get("notes")
        if not song or not notes:
            continue
        difficulty = DIFFICULTIES.get(str(chart.get("difficulty") or ""), "")
        if not difficulty:
            continue
        chart_type = "dx" if str(song.get("type")) == "deluxe" else "std"
        key = f"{str(song.get('title') or '').casefold()}|{chart_type}|{difficulty}"
        row: Dict[str, Any] = {
            "n": int(notes), "t": int(chart.get("taps") or 0), "h": int(chart.get("hold") or 0),
            "s": int(chart.get("slide") or 0), "u": int(chart.get("touch") or 0), "b": int(chart.get("breaks") or 0),
        }
        names = [tags[t] for t in (chart.get("tags") or []) if t in tags and tags[t]]
        if names:
            row["g"] = names
        if chart.get("has_chart_data") and chart.get("id"):
            row["c"] = str(chart["id"])      # the chart itself can be read, note by note, from this id
            try:
                row["l"] = float(chart.get("internal_level") or 0)
            except (TypeError, ValueError):
                row["l"] = 0.0
        out[key] = row
    return out


def fetch(etag: str = "") -> Tuple[str, Optional[Dict[str, Dict[str, Any]]], str]:
    """One conditional request for the manifest: (status, distilled charts or None, new etag).

    Status is "changed", "unchanged" when the site answers 304, or "failed".

    :param etag: The tag the site gave the copy already held.
    :type etag: str
    :rtype: Tuple[str, Optional[Dict[str, Dict[str, Any]]], str]
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        response = requests.get(MANIFEST_URL, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as error:
        logger.info("mai-notes fetch failed: %s", error)
        return "failed", None, etag
    if response.status_code == 304:
        return "unchanged", None, etag
    if response.status_code != 200:
        logger.info("mai-notes answered %s", response.status_code)
        return "failed", None, etag
    try:
        payload = response.json()
    except ValueError:
        logger.info("mai-notes answered something that is not JSON")
        return "failed", None, etag
    return "changed", distil(payload), response.headers.get("ETag", "")


def refresh_charts(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """The chart table, re-read from mai-notes only when the stored copy is a day old; never raises.

    The stored copy is the working one: nothing here is fetched to answer a command, so the site
    sees at most one conditional request a day whatever the bot is asked to do, and a 304 carries
    no body. A failed read leaves the timestamp alone so the next start tries again, rather than
    counting as a check and waiting another day.

    :param force: Whether to act even when the stored copy is current.
    :type force: bool
    :rtype: Dict[str, Dict[str, Any]]
    """
    state = source_state_get(SOURCE) or {}
    stored = _load(state)
    if stored and not force:
        try:
            if datetime.now() - datetime.fromisoformat(state["checked_at"]) < TTL:
                return stored
        except (ValueError, KeyError):
            pass
    with _lock:
        state = source_state_get(SOURCE) or {}
        stored = _load(state)
        # another thread may have refreshed while this one waited for the lock
        try:
            if stored and not force and datetime.now() - datetime.fromisoformat(state["checked_at"]) < TTL:
                return stored
        except (ValueError, KeyError):
            pass
        # a copy in the old shape is worth nothing, and asking conditionally would have the site
        # answer 304 and leave it in place, so the tag is dropped along with it
        tag = str(state.get("etag") or "") if stored else ""
        status, charts, etag = fetch(tag)
        if status == "changed" and charts:
            source_state_set(SOURCE, etag=etag,
                             payload=json.dumps({"v": FORMAT, "rows": charts}, ensure_ascii=False, separators=(",", ":")))
            _forget()
            logger.info("mai-notes: %d charts, %d with pattern tags", len(charts), sum(1 for c in charts.values() if c.get("g")))
            return charts
        if status == "unchanged":
            source_state_set(SOURCE)          # the stored copy still stands; only the check time moves
        return stored


def _load(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The stored chart table, or empty when it was distilled by code that kept different fields."""
    payload = str(state.get("payload") or "")
    if not payload:
        return {}
    try:
        held = json.loads(payload)
    except ValueError:
        return {}
    if not isinstance(held, dict) or held.get("v") != FORMAT:
        return {}
    rows = held.get("rows")
    return rows if isinstance(rows, dict) else {}


class ChartFacts:
    """The mai-notes charts, looked up the way the bot keys a chart, with a loose fallback on the title."""

    def __init__(self, charts: Dict[str, Dict[str, Any]]):
        self.exact = charts
        self.loose: Dict[str, Dict[str, Any]] = {}
        for key, row in charts.items():
            title, _, rest = key.partition("|")
            folded = loose_title(title)
            if folded:
                self.loose.setdefault(f"{folded}|{rest}", row)

    def __len__(self) -> int:
        return len(self.exact)

    def get(self, key: Tuple[str, str, str]) -> Optional[Dict[str, Any]]:
        title, chart_type, difficulty = key
        row = self.exact.get(f"{str(title).casefold()}|{chart_type}|{difficulty}")
        if row is not None:
            return row
        folded = loose_title(str(title))
        row = self.loose.get(f"{folded}|{chart_type}|{difficulty}") if folded else None
        if row is not None:
            return row
        # the editors have tagged a third of the Master charts and almost nothing easier; dxrating counts
        # the notes on all of them, so the note mix is known where nobody has written a pattern tag
        try:
            from rasmai.scraping import dxdata
            return dxdata.note_split(str(title), chart_type, difficulty)
        except Exception:
            return None


_memo: Tuple[float, Optional[ChartFacts]] = (0.0, None)


def _forget() -> None:
    """Drop the in-memory copy so the next reader picks up a fresh crawl."""
    global _memo
    _memo = (0.0, None)


def cached_facts() -> ChartFacts:
    """The stored chart table; never fetches. Re-read from the database at most every five minutes.

    :rtype: ChartFacts
    """
    global _memo
    checked, facts = _memo
    if facts is not None and time.monotonic() - checked < 300:
        return facts
    facts = ChartFacts(_load(source_state_get(SOURCE) or {}))
    _memo = (time.monotonic(), facts)
    return facts


def note_traits(row: Dict[str, Any]) -> List[Tuple[str, str]]:
    """What a chart's note mix says about it: only the top quarter of each note type is called out.

    :param row: One row of the table.
    :type row: Dict[str, Any]
    :rtype: List[Tuple[str, str]]
    """
    total = int(row.get("n") or 0)
    if total <= 0:
        return []
    return [(dimension, label) for field, dimension, high, label in SHARE_BANDS
            if int(row.get(field) or 0) / total >= high]


def pattern_traits(row: Dict[str, Any]) -> List[Tuple[str, str]]:
    return [("pattern", pattern_label(tag)) for tag in (row.get("g") or [])]


# the genre names as the international version prints them
GENRES = {
    "POPS＆アニメ": "POPS & ANIME",
    "niconico＆ボーカロイド": "niconico & VOCALOID",
    "東方Project": "TOUHOU Project",
    "ゲーム＆バラエティ": "GAME & VARIETY",
    "オンゲキ＆CHUNITHM": "ONGEKI & CHUNITHM",
    "宴会場": "UTAGE",
}


def english_label(label: str) -> str:
    """The English side of a trait label, for a reader who does not read the Japanese.

    Pattern labels are stored as ``"乱打 (streams)"`` so the community's own word stays the
    identity; this returns just the gloss. Labels that are already English pass through.

    :param label: The trait label as it is stored.
    :type label: str
    :returns: The English wording, or the label itself when it has no gloss.
    :rtype: str
    """
    if label in GENRES:
        return GENRES[label]
    if label.endswith(")") and " (" in label:
        japanese, _, english = label.rpartition(" (")
        # only a pattern label carries a gloss; "slow songs (up to 120 BPM)" is already English
        if not japanese.isascii():
            return english[:-1].strip() or japanese
    return label
