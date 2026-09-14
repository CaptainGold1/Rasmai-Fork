from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import logging

from rasmai.storage.db import (
    best_recorded_scores, load_judgements, record_area_progress, record_chart_scores, record_rating_point,
    update_account_snapshot,
)
from rasmai.util import _json_safe

logger = logging.getLogger(__name__)


CHART_FIELDS = ("name", "chart_type", "difficulty_type", "accuracy", "rating", "level",
                "constant", "fc_status", "fs_status", "is_new", "dx_score")


def chart_key(song: Any) -> Tuple[str, str, str]:
    return (
        str(getattr(song, "name", "")).casefold(),
        (str(getattr(song, "chart_type", "")).lower() or "std"),
        str(getattr(song, "difficulty_type", "")).lower(),
    )


def compact_snapshot(analyzer: Any) -> Dict[str, Any]:
    """Everything /compare and /export need, small enough to keep per account.

    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: Any
    :rtype: Dict[str, Any]
    """
    player = analyzer.player
    best50 = analyzer.best50
    charts: List[List[Any]] = []
    for song in analyzer.songs:
        if str(getattr(song, "difficulty_type", "")).lower() == "utage":
            continue
        charts.append([
            song.name, (song.chart_type or "std").lower(), (song.difficulty_type or "").lower(),
            round(float(song.accuracy or 0), 4), int(song.rating or 0), song.level,
            round(float(song.difficulty or 0), 1), song.fc_status or "", song.fs_status or "",
            bool(song.is_new), int(song.dx_score or 0),
        ])
    return {
        "name": player.name,
        "rating": int(player.rating or 0),
        "best50": best50.total if best50 else 0,
        "newTotal": best50.new_pool.total if best50 else 0,
        "oldTotal": best50.old_pool.total if best50 else 0,
        "totalPlayCount": int(player.total_play_count or 0),
        "recordedAt": datetime.now().isoformat(timespec="seconds"),
        "fields": list(CHART_FIELDS),
        "charts": charts,
        "areas": _json_safe(getattr(analyzer, "events_data", None) or {"areaEvents": [], "eventAreaEvents": []}),
        "areasReadAt": (analyzer.events_read_at.isoformat(timespec="seconds")
                        if isinstance(getattr(analyzer, "events_read_at", None), datetime) else None),
        "recentPlays": _json_safe(getattr(analyzer, "recent_songs", None) or []),
        # the recent-plays list as last read: the site's play ids on it are what a judgement page is fetched by,
        # so an analysis rebuilt from the stored copy after a restart can still open one
        "recent": _json_safe([r for r in (analyzer.recent_songs or []) if r.get("idx")]),
    }


def snapshot_charts(snapshot: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rows of a stored snapshot as dicts.

    :param snapshot: The stored copy of the player's scores.
    :type snapshot: Optional[Dict[str, Any]]
    :rtype: List[Dict[str, Any]]
    """
    if not snapshot:
        return []
    fields = snapshot.get("fields") or list(CHART_FIELDS)
    return [dict(zip(fields, row)) for row in snapshot.get("charts") or []]


def play_rows(analyzer: Any, recent: List[Dict[str, Any]]) -> List[Tuple[Any, ...]]:
    """Recent plays as chart_scores rows.

    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: Any
    :param recent: The recent-plays list from maimai DX NET.
    :type recent: List[Dict[str, Any]]
    :rtype: List[Tuple[Any, ...]]
    """
    rows: List[Tuple[Any, ...]] = []
    for record in recent or []:
        name = analyzer._normalize_official_song_name(str(record.get("songName", ""))).casefold()
        key = "|".join((name, str(record.get("musicType") or "std").lower(), str(record.get("difficulty") or "").lower()))
        achievement = float(record.get("achievement") or 0) / 10000.0
        if not (0 < achievement <= 101.0):
            continue
        played_at = record.get("playedAt", "")
        played_at = played_at.isoformat(timespec="seconds") if isinstance(played_at, datetime) else str(played_at)
        if not played_at:
            continue
        rows.append((key, played_at, round(achievement, 4), int(record.get("dxScore") or 0),
                     str(record.get("fc") or ""), str(record.get("fs") or ""), "play",
                     int(record.get("maxDxScore") or 0), int(record.get("track") or 0), record.get("judgement")))
    return rows


def record_plays(user_id: str, analyzer: Any, recent: List[Dict[str, Any]]) -> int:
    """Store the plays of one recent-plays read; repeats are ignored.

    :param user_id: The Discord user id.
    :type user_id: str
    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: Any
    :param recent: The recent-plays list from maimai DX NET.
    :type recent: List[Dict[str, Any]]
    :rtype: int
    """
    added = record_chart_scores(user_id, play_rows(analyzer, recent))
    store_recent(user_id, recent)
    return added


def judgement_key(analyzer: Any, record: Dict[str, Any]) -> Tuple[str, str]:
    """The chart key and time a recent-plays record is stored under, the way play_rows keys it.

    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: Any
    :param record: One entry of the recent-plays list.
    :type record: Dict[str, Any]
    :rtype: Tuple[str, str]
    """
    name = analyzer._normalize_official_song_name(str(record.get("songName", ""))).casefold()
    key = "|".join((name, str(record.get("musicType") or "std").lower(), str(record.get("difficulty") or "").lower()))
    played_at = record.get("playedAt", "")
    return key, played_at.isoformat(timespec="seconds") if isinstance(played_at, datetime) else str(played_at)


def collect_judgements(user_id: str, analyzer: Any, recent: List[Dict[str, Any]], region: str = "intl", limit: int = 50) -> int:
    """Read and store the judgement page of every recent play not stored yet, newest first, up to `limit`; never raises.

    The recent list holds fifty plays, so the first read after linking fetches every page once and later reads only the new ones.

    :param user_id: The Discord user id.
    :type user_id: str
    :param analyzer: The scraper and the analysis it holds, signed in.
    :type analyzer: Any
    :param recent: The recent-plays list from maimai DX NET.
    :type recent: List[Dict[str, Any]]
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: str
    :param limit: Most pages to read this time.
    :type limit: int
    :returns: How many pages were stored.
    :rtype: int
    """
    from rasmai.storage.db import judged_ids, save_judgement
    try:
        done = judged_ids(user_id)
    except Exception:
        logger.exception("Could not read stored judgements")
        return 0
    stored = 0
    for record in recent or []:
        idx = str(record.get("idx") or "")
        if not idx or idx in done:
            continue
        if stored >= limit:
            break
        try:
            detail = analyzer.fetch_playlog_detail(idx, region)
            key, played_at = judgement_key(analyzer, record)
            save_judgement(user_id, idx, key, played_at, detail)
            stored += 1
        except Exception as error:       # the site or the session gave out; what is stored so far stands
            logger.info("judgement pages stopped after %d: %s", stored, error)
            break
    return stored


def store_recent(user_id: str, recent: List[Dict[str, Any]]) -> None:
    """Keep the recent-plays list just read with the stored snapshot, so an analysis rebuilt after a restart still holds the play ids.

    :param user_id: The Discord user id.
    :type user_id: str
    :param recent: The recent-plays list from maimai DX NET.
    :type recent: List[Dict[str, Any]]
    """
    from rasmai.storage.db import get_connected_account, update_account_snapshot
    snapshot = (get_connected_account(user_id) or {}).get("latestSnapshot")
    if not snapshot:
        return
    snapshot["recent"] = _json_safe([r for r in recent if r.get("idx")])
    update_account_snapshot(user_id, None, snapshot)


def record_scores(user_id: str, analyzer: Any) -> int:
    """Remember every score this read revealed: each recent play, and each best that moved.

    The first read seeds a point per chart; later reads add only what changed, so the
    per-chart history stays small and every point is a real score the player made.

    :param user_id: The Discord user id.
    :type user_id: str
    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: Any
    :rtype: int
    """
    rows = play_rows(analyzer, analyzer.recent_songs or [])
    known = best_recorded_scores(user_id)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for song in analyzer.songs:
        if str(getattr(song, "difficulty_type", "")).lower() == "utage":
            continue
        accuracy = round(float(song.accuracy or 0), 4)
        if accuracy <= 0:
            continue
        key = "|".join(chart_key(song))
        if key not in known or accuracy > known[key] + 0.00005:
            rows.append((key, now, accuracy, int(song.dx_score or 0), song.fc_status or "", song.fs_status or "", "best"))
    return record_chart_scores(user_id, rows)


def analyzer_from_snapshot(user_id: str, account: Dict[str, Any]) -> Optional[Any]:
    """An analyzer over the stored snapshot, for when maimai cannot be read right now.

    :param user_id: The Discord user id.
    :type user_id: str
    :param account: The linked account, as stored.
    :type account: Dict[str, Any]
    :rtype: Optional[Any]
    """
    from rasmai.scraping.scraper import MaimaiRatingAnalyzer
    from rasmai.storage.db import load_play_counts, load_recorded_plays
    from rasmai.storage.models import PlayerInfo, SongInfo
    snapshot = account.get("latestSnapshot") or {}
    rows = snapshot_charts(snapshot)
    if not rows:
        return None
    profile = account.get("officialProfile") or {}
    analyzer = MaimaiRatingAnalyzer()
    analyzer.region = account.get("region", "intl")
    analyzer.player = PlayerInfo(
        name=str(profile.get("name") or snapshot.get("name") or ""), rating=int(profile.get("rating") or snapshot.get("rating") or 0),
        dan=str(profile.get("dan") or ""), title=str(profile.get("title") or ""),
        total_play_count=int(profile.get("totalPlayCount") or snapshot.get("totalPlayCount") or 0),
        # the avatar was read when the account was linked; without it every poster built from the stored copy has a blank corner
        avatar_base64=str(profile.get("avatar_base64") or ""), icon_url=str(profile.get("icon_url") or ""),
    )
    analyzer.songs = [
        SongInfo(
            name=r["name"], chart_type=r["chart_type"], difficulty_type=r["difficulty_type"],
            accuracy=float(r["accuracy"] or 0), rating=int(r["rating"] or 0), level=str(r["level"]),
            difficulty=float(r["constant"] or 0), fc_status=r["fc_status"], fs_status=r["fs_status"],
            is_new=bool(r["is_new"]), dx_score=int(r["dx_score"] or 0),
        )
        for r in rows
    ]
    analyzer.play_counts = load_play_counts(user_id)
    analyzer.recorded_plays = load_recorded_plays(user_id)
    analyzer.judgements = load_judgements(user_id)
    analyzer.recent_songs = list(snapshot.get("recentPlays") or snapshot.get("recent") or [])
    analyzer.events_data = snapshot.get("areas") or {"areaEvents": [], "eventAreaEvents": []}
    try:
        analyzer.events_read_at = datetime.fromisoformat(str(snapshot.get("areasReadAt") or "")) if snapshot.get("areasReadAt") else None
    except ValueError:
        analyzer.events_read_at = None
    return analyzer


def persist_progress(user_id: str, analyzer: Any) -> None:
    """Store the rating point, the compact snapshot and the scores seen; never lets a storage error reach the command.

    :param user_id: The Discord user id.
    :type user_id: str
    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: Any
    """
    try:
        record_scores(user_id, analyzer)
    except Exception:
        logger.exception("Could not record chart scores")
    try:
        record_area_progress(user_id, getattr(analyzer, "events_data", None), int(analyzer.player.total_play_count or 0))
    except Exception:
        logger.exception("Could not record area progress")
    try:
        player = analyzer.player
        best50 = analyzer.best50
        record_rating_point(
            user_id, int(player.rating or 0), best50.total if best50 else 0,
            best50.new_pool.total if best50 else 0, best50.old_pool.total if best50 else 0,
            len(analyzer.songs), int(player.total_play_count or 0),
        )
        profile = {
            "name": player.name, "rating": int(player.rating or 0), "dan": player.dan,
            "title": player.title, "totalPlayCount": int(player.total_play_count or 0),
            # a fresh read brings the avatar with it; an analysis built from the stored copy carries the stored one back
            "avatar_base64": player.avatar_base64 or "", "icon_url": player.icon_url or "",
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
        }
        update_account_snapshot(user_id, profile, compact_snapshot(analyzer))
    except Exception:
        logger.exception("Could not persist progress")
