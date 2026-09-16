from datetime import datetime
from typing import Any, Dict, Iterator, Optional, Tuple
import zlib

from rasmai.storage.db.connection import get_database_connection

# simai is repetitive text and packs down to about a third of its size, which matters because the
# charts are the largest thing the database holds by some way. Level 6 is where the gain flattens:
# level 9 saves another 0.2% for noticeably more work.
SQUASH = 6


def _pack(sheet: str) -> bytes:
    return zlib.compress(sheet.encode("utf-8"), SQUASH)


def _unpack(stored: Any) -> str:
    """The notation back out, whether it was packed or written before packing was."""
    if isinstance(stored, (bytes, bytearray)):
        try:
            return zlib.decompress(stored).decode("utf-8")
        except zlib.error:
            return bytes(stored).decode("utf-8", "replace")
    return str(stored)


def sheet_put(chart_key: str, chart_id: str, sheet: str) -> None:
    """Keep one chart's simai, exactly as the site served it.

    The notation is the source everything measured about a chart comes from, and a chart never
    changes once it is published. Keeping it means a change to what is measured costs a re-read of
    the local copy rather than another crawl of somebody else's site.

    :param chart_key: The chart, as ``"title|type|difficulty"``.
    :type chart_key: str
    :param chart_id: maiノーツ's own id for the chart.
    :type chart_id: str
    :param sheet: The chart in simai.
    :type sheet: str
    """
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO simai_sheets (chart_key, chart_id, sheet, fetched_at) VALUES (?, ?, ?, ?)",
                (chart_key, chart_id, _pack(sheet), datetime.now().isoformat(timespec="seconds")),
            )
    finally:
        connection.close()


def sheet_get(chart_key: str) -> Optional[str]:
    """One chart's simai, or None when it has never been read.

    :param chart_key: The chart, as ``"title|type|difficulty"``.
    :type chart_key: str
    :rtype: Optional[str]
    """
    connection = get_database_connection()
    try:
        row = connection.execute("SELECT sheet FROM simai_sheets WHERE chart_key = ?", (chart_key,)).fetchone()
    finally:
        connection.close()
    return _unpack(row["sheet"]) if row else None


def sheets_all() -> Iterator[Tuple[str, str]]:
    """Every stored chart as ``(key, simai)``, one at a time so the whole lot is never held at once.

    :rtype: Iterator[Tuple[str, str]]
    """
    connection = get_database_connection()
    try:
        for row in connection.execute("SELECT chart_key, sheet FROM simai_sheets ORDER BY chart_key"):
            yield str(row["chart_key"]), _unpack(row["sheet"])
    finally:
        connection.close()


def squash_sheets() -> int:
    """Pack any chart still held as plain text; returns how many were packed.

    Charts read before packing existed are stored as they arrived. They are read back either way,
    so this is only about the room they take: about a third of what they took before.

    :rtype: int
    """
    connection = get_database_connection()
    try:
        rows = connection.execute("SELECT chart_key, sheet FROM simai_sheets "
                                  "WHERE typeof(sheet) = 'text'").fetchall()
        if not rows:
            return 0
        with connection:
            connection.executemany("UPDATE simai_sheets SET sheet = ? WHERE chart_key = ?",
                                   [(_pack(str(row["sheet"])), str(row["chart_key"])) for row in rows])
        # the pages the old copies sat on are free now but the file is still as large as it was,
        # so it is rewritten once to hand the room back to the disk
        connection.execute("VACUUM")
        return len(rows)
    finally:
        connection.close()


def sheets_held() -> Dict[str, int]:
    """How many charts are stored and what they take up, for the developer page.

    :rtype: Dict[str, int]
    """
    connection = get_database_connection()
    try:
        row = connection.execute("SELECT COUNT(*) AS charts, COALESCE(SUM(LENGTH(sheet)), 0) AS bytes "
                                 "FROM simai_sheets").fetchone()
    finally:
        connection.close()
    return {"charts": int(row["charts"]), "bytes": int(row["bytes"])}
