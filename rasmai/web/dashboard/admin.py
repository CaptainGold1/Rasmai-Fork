from datetime import datetime, timedelta
from typing import Any, Dict, List
import logging
import os
import sqlite3
import time

from rasmai.config import ADMIN_USER_ID, DATABASE_PATH, MAX_CONCURRENT_RENDERS, MAX_CONCURRENT_SCRAPES
from rasmai.storage.db.connection import get_database_connection

logger = logging.getLogger(__name__)

STARTED = time.time()

# names and avatars resolved from Discord, kept for the life of the process: the page polls every
# few seconds and a display name almost never changes, so one lookup per account is plenty
_PEOPLE: Dict[str, Dict[str, str]] = {}


def _shape(user: Any) -> Dict[str, str]:
    return {"name": getattr(user, "global_name", None) or user.name, "handle": user.name,
            "avatar": str(user.display_avatar.url) if getattr(user, "display_avatar", None) else ""}


def people(ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Discord names and avatars for a handful of ids, from the bot's cache or by asking Discord.

    The bot keeps no member cache, so most ids need a fetch. That is a network call on the web
    server's thread, hence the short timeout and the process-lifetime cache; a failure just leaves
    the id showing as itself.

    :param ids: The Discord user ids to name.
    :type ids: List[str]
    :rtype: Dict[str, Dict[str, str]]
    """
    import asyncio
    wanted = [str(i) for i in dict.fromkeys(ids) if str(i) not in _PEOPLE]
    if wanted:
        try:
            from rasmai.bot.core import bot
            loop = getattr(bot, "loop", None)
            for user_id in wanted:
                found = bot.get_user(int(user_id))
                if found is None and loop is not None and loop.is_running():
                    found = asyncio.run_coroutine_threadsafe(bot.fetch_user(int(user_id)), loop).result(timeout=4)
                if found is not None:
                    _PEOPLE[user_id] = _shape(found)
        except Exception:
            logger.info("could not name every account on the developer page", exc_info=False)
    return {i: _PEOPLE[i] for i in {str(x) for x in ids} if i in _PEOPLE}


def _named(rows: List[Dict[str, Any]], known: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    return [{**row, **(known.get(str(row.get("userId", "")), {}))} for row in rows]


def is_admin(user_id: str) -> bool:
    """Whether this Discord account is the one the developer page answers to.

    :param user_id: The Discord user id, as the web server authenticated it.
    :type user_id: str
    :rtype: bool
    """
    return bool(ADMIN_USER_ID) and str(user_id) == ADMIN_USER_ID


def _rows(connection: sqlite3.Connection, sql: str, *args) -> List[sqlite3.Row]:
    try:
        return connection.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _one(connection: sqlite3.Connection, sql: str, *args) -> Any:
    rows = _rows(connection, sql, *args)
    return rows[0][0] if rows else None


def _table_sizes(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Bytes per table, from dbstat when the build has it, otherwise row counts alone.

    :rtype: List[Dict[str, Any]]
    """
    out = []
    for row in _rows(connection, "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name ORDER BY bytes DESC"):
        out.append({"name": row["name"], "bytes": int(row["bytes"] or 0)})
    if out:
        return out
    for row in _rows(connection, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
        out.append({"name": row["name"], "bytes": None,
                    "rows": _one(connection, f"SELECT COUNT(*) FROM \"{row['name']}\"") or 0})
    return out


def admin_payload() -> Dict[str, Any]:
    """Everything the developer page shows: who is linked, what is stored, and what the process is doing.

    Read-only and built on the spot, so nothing has to be recorded all the time to make it work.

    :rtype: Dict[str, Any]
    """
    connection = get_database_connection()
    try:
        accounts = _rows(connection, "SELECT region, COUNT(*) AS n, SUM(session_expired <> '') AS dead "
                                     "FROM connected_accounts GROUP BY region ORDER BY n DESC")
        stale = _rows(connection, "SELECT user_id, region, session_expired FROM connected_accounts "
                                  "WHERE session_expired <> '' ORDER BY session_expired")
        reads = _rows(connection, "SELECT user_id, read_at, error FROM quiet_reads WHERE error <> '' ORDER BY read_at DESC LIMIT 10")
        sources = _rows(connection, "SELECT source, checked_at, LENGTH(payload) AS bytes, etag <> '' AS tagged "
                                    "FROM news_state ORDER BY source")
        busiest = _rows(connection, "SELECT user_id, COUNT(*) AS plays FROM chart_scores GROUP BY user_id ORDER BY plays DESC LIMIT 5")
        since = (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d")
        daily = _rows(connection, "SELECT substr(played_at, 1, 10) AS day, COUNT(*) AS plays, COUNT(DISTINCT user_id) AS people "
                                  "FROM chart_scores WHERE played_at >= ? GROUP BY day ORDER BY day", since)
        linked_on = _rows(connection, "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM connected_accounts GROUP BY day ORDER BY day")
        page_size = _one(connection, "PRAGMA page_size") or 0
        store = {
            "bytes": int((_one(connection, "PRAGMA page_count") or 0) * page_size),
            "freeBytes": int((_one(connection, "PRAGMA freelist_count") or 0) * page_size),
            "walBytes": int(os.path.getsize(f"{DATABASE_PATH}-wal")) if os.path.exists(f"{DATABASE_PATH}-wal") else 0,
            "tables": _table_sizes(connection),
            "plays": _one(connection, "SELECT COUNT(*) FROM chart_scores") or 0,
            "judgements": _one(connection, "SELECT COUNT(*) FROM play_judgements") or 0,
            "ratingPoints": _one(connection, "SELECT COUNT(*) FROM rating_history") or 0,
            "playCounts": _one(connection, "SELECT COUNT(*) FROM chart_play_counts") or 0,
            "oldestPlay": _one(connection, "SELECT MIN(played_at) FROM chart_scores"),
        }
    finally:
        connection.close()

    # the running process: what is in memory and how much of each limit is in use right now
    live: Dict[str, Any] = {"uptimeSeconds": int(time.time() - STARTED)}
    try:
        from rasmai.bot.core import RENDER_SEMAPHORE, SCRAPE_SEMAPHORE, bot
        live.update({
            "guilds": len(bot.guilds), "shards": bot.shard_count or 1,
            "ready": bot.is_ready(), "latencyMs": round((bot.latency or 0) * 1000),
            "scrapesFree": SCRAPE_SEMAPHORE._value, "scrapesMax": MAX_CONCURRENT_SCRAPES,
            "rendersFree": RENDER_SEMAPHORE._value, "rendersMax": MAX_CONCURRENT_RENDERS,
        })
    except Exception:
        pass
    try:
        from rasmai.bot.state.cache import ANALYSIS_TTL, _analysis_cache
        now = datetime.now()
        live["analysesCached"] = len(_analysis_cache)
        live["analysisTtlMinutes"] = int(ANALYSIS_TTL / timedelta(minutes=1))
        live["cacheAges"] = sorted(int((now - c.created).total_seconds()) for c in _analysis_cache.values())[:10]
    except Exception:
        pass
    try:
        from rasmai.web.dashboard.refresh import refresh_jobs
        live["refreshesRunning"] = sum(1 for job in refresh_jobs._jobs.values() if job.get("running"))
    except Exception:
        pass
    try:
        from rasmai.bot.builders.charts.index import shared_index
        index = shared_index()
        live["chartsIndexed"] = len(index)
    except Exception:
        pass

    seen = {row["day"]: row for row in daily}
    activity = []
    for back in range(29, -1, -1):
        day = (datetime.now() - timedelta(days=back)).strftime("%Y-%m-%d")
        row = seen.get(day)
        activity.append({"day": day, "plays": int(row["plays"]) if row else 0,
                         "people": int(row["people"]) if row else 0})
    running = 0
    growth = []
    for row in linked_on:
        running += int(row["n"])
        growth.append({"day": row["day"], "accounts": running})

    known = people([r["user_id"] for r in busiest] + [r["user_id"] for r in stale] + [r["user_id"] for r in reads])
    return {
        "accounts": [{"region": r["region"], "count": int(r["n"]), "expired": int(r["dead"] or 0)} for r in accounts],
        "expired": _named([{"userId": r["user_id"], "region": r["region"], "since": r["session_expired"]} for r in stale], known),
        "failingReads": _named([{"userId": r["user_id"], "lastRead": r["read_at"], "error": r["error"]} for r in reads], known),
        "sources": [{"source": r["source"], "checkedAt": r["checked_at"], "bytes": int(r["bytes"] or 0),
                     "etag": bool(r["tagged"])} for r in sources],
        "busiest": _named([{"userId": r["user_id"], "plays": int(r["plays"])} for r in busiest], known),
        "activity": activity,
        "growth": growth,
        "store": store,
        "live": live,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
    }
