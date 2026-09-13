from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
import json

from rasmai.security import decrypt_token
from rasmai.storage.db.connection import _load_json_column, get_database_connection


def record_rating_point(user_id: str, rating: int, best50: int, new_total: int, old_total: int,
                        charts: int, plays: int) -> bool:
    """Append a point to the rating history unless nothing moved since the last one within a day.

    :param user_id: The Discord user id.
    :type user_id: str
    :param rating: The player's rating.
    :type rating: int
    :param best50: The player's two rating pools.
    :type best50: int
    :param charts: The charts to work through.
    :type charts: int
    :param plays: How many times the chart has been played.
    :type plays: int
    :rtype: bool
    """
    connection = get_database_connection()
    try:
        last = connection.execute(
            "SELECT * FROM rating_history WHERE user_id = ? ORDER BY recorded_at DESC LIMIT 1", (user_id,)
        ).fetchone()
        now = datetime.now()
        if last:
            same = (int(last["rating"]) == rating and int(last["best50"]) == best50 and int(last["plays"]) == plays)
            try:
                recent = now - datetime.fromisoformat(last["recorded_at"]) < timedelta(days=1)
            except ValueError:
                recent = False
            if same and recent:
                return False
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO rating_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, now.isoformat(timespec="seconds"), rating, best50, new_total, old_total, charts, plays),
            )
        return True
    finally:
        connection.close()


def import_rating_points(user_id: str, points: List[Tuple[Any, ...]]) -> int:
    """Add (recorded_at, rating, best50, new_total, old_total, charts, plays) points as dated; ones already held are skipped.

    :param user_id: The Discord user id.
    :type user_id: str
    :param points: The points to add.
    :type points: List[Tuple[Any, ...]]
    :returns: How many were new.
    :rtype: int
    """
    connection = get_database_connection()
    try:
        with connection:
            cursor = connection.executemany("INSERT OR IGNORE INTO rating_history VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                            [(user_id, *point) for point in points])
            return cursor.rowcount
    finally:
        connection.close()


def load_play_history(user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every stored play, newest first, each with the best held on that chart before it.

    Plays arrive from the recent-plays page on every read (a command, a dashboard refresh
    or the daily quiet read) and stay until the account is unlinked, so this outlives the
    fifty plays maimai DX NET itself shows.

    :param user_id: The Discord user id.
    :type user_id: str
    :param limit: Most entries to return.
    :type limit: Optional[int]
    :rtype: List[Dict[str, Any]]
    """
    connection = get_database_connection()
    try:
        rows = connection.execute(
            "SELECT chart_key, played_at, achievement, dx_score, fc, fs, source, max_dx, track, judgement "
            "FROM chart_scores WHERE user_id = ? ORDER BY played_at",
            (user_id,),
        ).fetchall()
    finally:
        connection.close()
    best_so_far: Dict[str, float] = {}
    plays: List[Dict[str, Any]] = []
    for row in rows:
        key = str(row["chart_key"])
        achievement = float(row["achievement"])
        if row["source"] == "play":
            try:
                judgement = json.loads(row["judgement"]) if row["judgement"] else None
            except (TypeError, ValueError):
                judgement = None
            plays.append({
                "key": key, "played_at": str(row["played_at"]), "achievement": achievement,
                "dx_score": int(row["dx_score"] or 0), "max_dx": int(row["max_dx"] or 0), "track": int(row["track"] or 0),
                "fc": str(row["fc"] or ""), "fs": str(row["fs"] or ""), "best_before": best_so_far.get(key, 0.0),
                "judgement": judgement,
            })
        best_so_far[key] = max(best_so_far.get(key, 0.0), achievement)
    plays.reverse()
    return plays[:limit] if limit else plays


def count_play_history(user_id: str) -> int:
    connection = get_database_connection()
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM chart_scores WHERE user_id = ? AND source = 'play'", (user_id,)
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        connection.close()


def quiet_reads_due(every: timedelta) -> List[Dict[str, Any]]:
    """Accounts with the history setting on whose last quiet read is older than `every` (or never ran).

    :param every: How often to run.
    :type every: timedelta
    :rtype: List[Dict[str, Any]]
    """
    cutoff = (datetime.now() - every).isoformat(timespec="seconds")
    connection = get_database_connection()
    try:
        rows = connection.execute(
            """
            SELECT a.user_id, a.region, a.token, s.settings, q.read_at
            FROM connected_accounts a
            JOIN user_settings s ON s.user_id = a.user_id
            LEFT JOIN quiet_reads q ON q.user_id = a.user_id
            WHERE q.read_at IS NULL OR q.read_at < ?
            ORDER BY q.read_at
            """,
            (cutoff,),
        ).fetchall()
    finally:
        connection.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        settings = _load_json_column(row["settings"]) or {}
        if settings.get("history"):
            out.append({"userId": row["user_id"], "region": row["region"], "token": decrypt_token(str(row["token"] or ""))})
    return out


def quiet_read_done(user_id: str, plays_added: int, error: str = "") -> None:
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO quiet_reads (user_id, read_at, plays_added, error) VALUES (?, ?, ?, ?)",
                (user_id, datetime.now().isoformat(timespec="seconds"), int(plays_added), error[:200]),
            )
    finally:
        connection.close()


def quiet_read_status(user_id: str) -> Optional[Dict[str, Any]]:
    connection = get_database_connection()
    try:
        row = connection.execute("SELECT read_at, plays_added, error FROM quiet_reads WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        connection.close()
    return dict(row) if row else None


def load_rating_history(user_id: str) -> List[Dict[str, Any]]:
    connection = get_database_connection()
    try:
        rows = connection.execute(
            "SELECT * FROM rating_history WHERE user_id = ? ORDER BY recorded_at", (user_id,)
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def since_last_look(user_id: str, rating: int, plays: int) -> Optional[Dict[str, Any]]:
    """What moved since the previous read that differed from this one: rating change, plays made, new bests.

    The latest rating point usually is this read; the point before the first one that
    matches the current rating and play count is "last time". None when there is no
    earlier point to compare with.

    :param user_id: The Discord user id.
    :type user_id: str
    :param rating: The player's rating now.
    :type rating: int
    :param plays: The player's total play count now.
    :type plays: int
    :rtype: Optional[Dict[str, Any]]
    """
    history = load_rating_history(user_id)
    previous = None
    for point in reversed(history):
        if int(point.get("rating") or 0) != int(rating) or int(point.get("plays") or 0) != int(plays):
            previous = point
            break
    if previous is None:
        return None
    since = str(previous.get("recorded_at") or "")
    if not since:
        return None
    connection = get_database_connection()
    try:
        row = connection.execute(
            "SELECT COUNT(*) AS n FROM chart_scores WHERE user_id = ? AND source = 'play' AND played_at > ?", (user_id, since)
        ).fetchone()
    finally:
        connection.close()
    new_bests = sum(1 for play in load_play_history(user_id) if play["played_at"] > since and play["achievement"] > play["best_before"] + 0.00005)
    return {
        "since": since,
        "ratingDelta": int(rating) - int(previous.get("rating") or 0),
        "plays": int(row["n"]) if row else 0,
        "newBests": new_bests,
    }
