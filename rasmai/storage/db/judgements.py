from typing import Any, Dict, Optional, List, Tuple
import json

from rasmai.storage.db.connection import get_database_connection


def save_judgement(user_id: str, idx: str, chart_key: str, played_at: str, detail: Dict[str, Any]) -> None:
    """Keep one play's judgement page: the counts per note type, the timing split and the achievement.

    :param user_id: The Discord user id.
    :type user_id: str
    :param idx: The site's own id for the play.
    :type idx: str
    :param chart_key: The chart, as ``"title|type|difficulty"``.
    :type chart_key: str
    :param played_at: When the play happened, ISO 8601.
    :type played_at: str
    :param detail: The play's judgement page.
    :type detail: Dict[str, Any]
    """
    if not detail.get("notes"):
        return
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO play_judgements "
                "(user_id, idx, chart_key, played_at, achievement, fast, late, notes, combo, max_combo, sync, max_sync) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, idx, chart_key, played_at, float(detail.get("achievement") or 0), int(detail.get("fast") or 0),
                 int(detail.get("late") or 0), json.dumps(detail["notes"], separators=(",", ":")),
                 int(detail.get("combo") or 0), int(detail.get("max_combo") or 0),
                 int(detail.get("sync") or 0), int(detail.get("max_sync") or 0)),
            )
    finally:
        connection.close()


_COLUMNS = "idx, chart_key, played_at, achievement, fast, late, notes, combo, max_combo, sync, max_sync"


def _row(row: Any) -> Optional[Dict[str, Any]]:
    """One stored page as the dashboard and the poster read it, or None when its notes did not survive."""
    try:
        notes = json.loads(row["notes"])
    except ValueError:
        return None
    return {"idx": row["idx"], "chart_key": row["chart_key"], "played_at": row["played_at"],
            "achievement": float(row["achievement"]), "fast": int(row["fast"]), "late": int(row["late"]),
            "combo": int(row["combo"] or 0), "max_combo": int(row["max_combo"] or 0),
            "sync": int(row["sync"] or 0), "max_sync": int(row["max_sync"] or 0), "notes": notes}


def judgement_for(user_id: str, idx: str) -> Optional[Dict[str, Any]]:
    """The stored page for one play, or None when it was never read.

    A page read once is kept for good, so opening it again asks this rather than maimai DX NET.

    :param user_id: The Discord user id.
    :type user_id: str
    :param idx: The site's own id for the play.
    :type idx: str
    :rtype: Optional[Dict[str, Any]]
    """
    connection = get_database_connection()
    try:
        row = connection.execute(
            f"SELECT {_COLUMNS} FROM play_judgements WHERE user_id = ? AND idx = ?", (user_id, idx)).fetchone()
    finally:
        connection.close()
    return _row(row) if row else None


def judged_marks(user_id: str) -> Dict[Tuple[str, str], str]:
    """Every stored page keyed by the chart and moment it belongs to, so a play can be matched to its id.

    The recent-plays list only carries ids for the fifty plays maimai still shows; this is what lets
    a play that has since scrolled off still open the page that was kept for it.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Dict[Tuple[str, str], str]
    """
    connection = get_database_connection()
    try:
        rows = connection.execute(
            "SELECT idx, chart_key, played_at FROM play_judgements WHERE user_id = ?", (user_id,)).fetchall()
    finally:
        connection.close()
    return {(str(row["chart_key"]), str(row["played_at"])): str(row["idx"]) for row in rows}


def load_judgements(user_id: str) -> List[Dict[str, Any]]:
    """Every stored judgement page for a player, oldest first.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: List[Dict[str, Any]]
    """
    connection = get_database_connection()
    try:
        rows = connection.execute(
            f"SELECT {_COLUMNS} FROM play_judgements WHERE user_id = ? ORDER BY played_at", (user_id,)).fetchall()
    finally:
        connection.close()
    return [page for page in (_row(row) for row in rows) if page]


def judged_ids(user_id: str) -> set:
    """The play ids whose judgement page is already stored.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: set
    """
    connection = get_database_connection()
    try:
        return {row["idx"] for row in connection.execute("SELECT idx FROM play_judgements WHERE user_id = ?", (user_id,))}
    finally:
        connection.close()


def delete_judgements(user_id: str) -> None:
    connection = get_database_connection()
    try:
        with connection:
            connection.execute("DELETE FROM play_judgements WHERE user_id = ?", (user_id,))
    finally:
        connection.close()
