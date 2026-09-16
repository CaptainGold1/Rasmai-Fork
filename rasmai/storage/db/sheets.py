from datetime import datetime
from typing import Dict, Iterator, Optional, Tuple

from rasmai.storage.db.connection import get_database_connection


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
                (chart_key, chart_id, sheet, datetime.now().isoformat(timespec="seconds")),
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
    return str(row["sheet"]) if row else None


def sheets_all() -> Iterator[Tuple[str, str]]:
    """Every stored chart as ``(key, simai)``, one at a time so the whole lot is never held at once.

    :rtype: Iterator[Tuple[str, str]]
    """
    connection = get_database_connection()
    try:
        for row in connection.execute("SELECT chart_key, sheet FROM simai_sheets ORDER BY chart_key"):
            yield str(row["chart_key"]), str(row["sheet"])
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
