from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any
import json

from rasmai.config import PLAY_COUNT_TTL
from rasmai.storage.db.connection import get_database_connection
from rasmai.util import _json_safe


def load_play_counts(
    user_id: str, latest_plays: Optional[Dict[Tuple[str, str, str], datetime]] = None
) -> Dict[Tuple[str, str, str], int]:
    """Per-chart play counts scraped earlier for this user, if still fresh.

    A count is stale once the chart has been played again (`latest_plays` maps
    chart key -> time of the newest play), and a chart whose count could not be
    read is retried after an hour rather than waiting out the full TTL.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Dict[Tuple[str, str, str], int]
    """
    connection = get_database_connection()
    try:
        rows = connection.execute(
            "SELECT chart_key, plays, fetched_at FROM chart_play_counts WHERE user_id = ?", (user_id,)
        ).fetchall()
    finally:
        connection.close()
    now = datetime.now()
    cutoff = now - PLAY_COUNT_TTL
    unknown_cutoff = now - timedelta(hours=1)
    counts: Dict[Tuple[str, str, str], int] = {}
    for row in rows:
        try:
            fetched_at = datetime.fromisoformat(row["fetched_at"])
        except ValueError:
            continue
        plays = int(row["plays"])
        if fetched_at < (unknown_cutoff if plays < 0 else cutoff):
            continue
        parts = str(row["chart_key"]).split("|")
        if len(parts) != 3:
            continue
        key = (parts[0], parts[1], parts[2])
        played = latest_plays.get(key) if latest_plays else None
        if played is not None and played > fetched_at.astimezone():
            continue
        counts[key] = plays
    return counts


def save_play_counts(user_id: str, counts: Dict[Tuple[str, str, str], int]) -> None:
    if not counts:
        return
    now = datetime.now().isoformat()
    connection = get_database_connection()
    try:
        with connection:
            connection.executemany(
                """
                INSERT INTO chart_play_counts (user_id, chart_key, plays, fetched_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, chart_key) DO UPDATE SET
                    plays = excluded.plays, fetched_at = excluded.fetched_at
                """,
                [(user_id, "|".join(key), int(plays), now) for key, plays in counts.items()],
            )
    finally:
        connection.close()


def record_chart_scores(user_id: str, rows: List[Tuple[Any, ...]]) -> int:
    """Append score rows, retaining imported judgement data when available.

    Rows are kept for as long as the account is linked: they are the player's own score
    history, and everything that draws a graph or checks the model reads from here.

    :param user_id: The Discord user id.
    :type user_id: str
    :param rows: The rows to render.
    :type rows: List[Tuple[Any, ...]]
    :rtype: int
    """
    if not rows:
        return 0
    connection = get_database_connection()
    try:
        with connection:
            cursor = connection.executemany(
                                "INSERT INTO chart_scores (user_id, chart_key, played_at, achievement, dx_score, fc, fs, source, max_dx, track, judgement) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                                "ON CONFLICT(user_id, chart_key, played_at) DO UPDATE SET judgement = "
                                "CASE WHEN excluded.judgement <> '' THEN excluded.judgement ELSE chart_scores.judgement END",
                [(user_id, row[0], row[1], float(row[2]), int(row[3]), row[4] or "", row[5] or "", row[6],
                                    int(row[7]) if len(row) > 7 else 0, int(row[8]) if len(row) > 8 else 0,
                                    json.dumps(_json_safe(row[9]), ensure_ascii=False) if len(row) > 9 and row[9] else "")
                 for row in rows],
            )
            return cursor.rowcount if cursor.rowcount is not None else 0
    finally:
        connection.close()


def best_recorded_scores(user_id: str) -> Dict[str, float]:
    """The highest achievement stored for each of this user's charts.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Dict[str, float]
    """
    connection = get_database_connection()
    try:
        rows = connection.execute(
            "SELECT chart_key, MAX(achievement) AS best FROM chart_scores WHERE user_id = ? GROUP BY chart_key", (user_id,)
        ).fetchall()
    finally:
        connection.close()
    return {str(row["chart_key"]): float(row["best"]) for row in rows}


def load_chart_scores(user_id: str, chart_keys: List[str]) -> List[Dict[str, Any]]:
    """Every stored score for these chart keys, oldest first.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: List[Dict[str, Any]]
    """
    if not chart_keys:
        return []
    connection = get_database_connection()
    try:
        marks = ",".join("?" for _ in chart_keys)
        rows = connection.execute(
            f"SELECT played_at, achievement, dx_score, fc, fs, source, judgement FROM chart_scores "
            f"WHERE user_id = ? AND chart_key IN ({marks}) ORDER BY played_at",
            (user_id, *chart_keys),
        ).fetchall()
    finally:
        connection.close()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["judgement"] = json.loads(item["judgement"]) if item.get("judgement") else None
        except (TypeError, ValueError):
            item["judgement"] = None
        out.append(item)
    return out


def load_recorded_plays(user_id: str) -> List[Dict[str, Any]]:
    """Every stored play with the best the player held on that chart before it, for the model's self-check.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: List[Dict[str, Any]]
    """
    connection = get_database_connection()
    try:
        rows = connection.execute(
            "SELECT chart_key, played_at, achievement, source FROM chart_scores WHERE user_id = ? ORDER BY chart_key, played_at",
            (user_id,),
        ).fetchall()
    finally:
        connection.close()
    out: List[Dict[str, Any]] = []
    best_so_far: Dict[str, float] = {}
    for row in rows:
        key = str(row["chart_key"])
        achievement = float(row["achievement"])
        if row["source"] == "play":
            out.append({"key": key, "played_at": row["played_at"], "achievement": achievement,
                        "best_before": best_so_far.get(key, 0.0)})
        best_so_far[key] = max(best_so_far.get(key, 0.0), achievement)
    return out


def delete_chart_scores(user_id: str) -> None:
    connection = get_database_connection()
    try:
        with connection:
            connection.execute("DELETE FROM chart_scores WHERE user_id = ?", (user_id,))
    finally:
        connection.close()
