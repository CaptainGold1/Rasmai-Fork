from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import logging
import os
import sqlite3
import threading
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


def accounts_payload() -> List[Dict[str, Any]]:
    """Every linked account, most recently active first, for the list the developer page shows.

    :rtype: List[Dict[str, Any]]
    """
    connection = get_database_connection()
    try:
        rows = _rows(connection, """
            SELECT a.user_id, a.region, a.created_at, a.updated_at, a.seen_at, a.session_expired,
                   a.share_slug IS NOT NULL AND a.share_slug <> '' AS shared,
                   json_extract(a.official_profile, '$.name')   AS player,
                   json_extract(a.official_profile, '$.rating') AS rating,
                   (SELECT COUNT(*) FROM chart_scores s WHERE s.user_id = a.user_id) AS plays,
                   (SELECT COUNT(*) FROM play_judgements j WHERE j.user_id = a.user_id) AS judged
            FROM connected_accounts a
            ORDER BY COALESCE(a.seen_at, a.updated_at) DESC
        """)
    finally:
        connection.close()
    out = [{"userId": r["user_id"], "region": r["region"], "player": r["player"] or "", "rating": int(r["rating"] or 0),
            "linkedAt": r["created_at"], "readAt": r["updated_at"], "seenAt": r["seen_at"] or "",
            "expired": bool(r["session_expired"]), "shared": bool(r["shared"]),
            "plays": int(r["plays"] or 0), "judged": int(r["judged"] or 0)} for r in rows]
    return _named(out, people([r["userId"] for r in out]))


def account_detail(user_id: str) -> Optional[Dict[str, Any]]:
    """Everything the developer page shows about one account, without its session token.

    The stored maimai session is never returned: it is the credential itself, and nothing on a
    page needs it. Everything else is what the bot already holds about the person.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Optional[Dict[str, Any]]
    """
    from rasmai.bot.state.prefs import get_prefs
    from rasmai.storage.db import get_connected_account, quiet_read_status
    account = get_connected_account(user_id)
    if account is None:
        return None
    profile = account.get("officialProfile") or {}
    snapshot = account.get("latestSnapshot") or {}
    connection = get_database_connection()
    try:
        counts = {
            "plays": _one(connection, "SELECT COUNT(*) FROM chart_scores WHERE user_id = ?", user_id) or 0,
            "judgements": _one(connection, "SELECT COUNT(*) FROM play_judgements WHERE user_id = ?", user_id) or 0,
            "ratingPoints": _one(connection, "SELECT COUNT(*) FROM rating_history WHERE user_id = ?", user_id) or 0,
            "playCounts": _one(connection, "SELECT COUNT(*) FROM chart_play_counts WHERE user_id = ?", user_id) or 0,
            "areaReadings": _one(connection, "SELECT COUNT(*) FROM area_progress WHERE user_id = ?", user_id) or 0,
            "firstPlay": _one(connection, "SELECT MIN(played_at) FROM chart_scores WHERE user_id = ?", user_id),
            "lastPlay": _one(connection, "SELECT MAX(played_at) FROM chart_scores WHERE user_id = ?", user_id),
        }
        history = _rows(connection, "SELECT recorded_at, rating FROM rating_history WHERE user_id = ? "
                                    "ORDER BY recorded_at DESC LIMIT 60", user_id)
        daily = _rows(connection, "SELECT substr(played_at, 1, 10) AS day, COUNT(*) AS plays FROM chart_scores "
                                  "WHERE user_id = ? GROUP BY day ORDER BY day DESC LIMIT 30", user_id)
    finally:
        connection.close()
    quiet = quiet_read_status(user_id) or {}
    known = people([user_id]).get(user_id, {})
    return {
        "userId": user_id, **known,
        "region": account.get("region", "intl"),
        "player": str(profile.get("name") or ""), "title": str(profile.get("title") or ""),
        "dan": str(profile.get("dan") or ""), "rating": int(profile.get("rating") or 0),
        "totalPlayCount": int(profile.get("totalPlayCount") or 0),
        "charts": len(snapshot.get("charts") or []),
        "linkedAt": account.get("createdAt"), "readAt": account.get("updatedAt"), "seenAt": account.get("seenAt") or "",
        "expired": account.get("sessionExpired") or "",
        "shared": bool(account.get("shareSlug")),
        "settings": get_prefs(user_id),
        "counts": counts,
        "quietRead": {"readAt": quiet.get("read_at") or quiet.get("readAt") or "",
                      "added": quiet.get("plays_added") or quiet.get("added") or 0,
                      "error": quiet.get("error") or ""},
        "history": [{"recordedAt": r["recorded_at"], "rating": int(r["rating"] or 0)} for r in reversed(history)],
        "activity": [{"day": r["day"], "plays": int(r["plays"] or 0)} for r in reversed(daily)],
    }


def guilds_payload() -> List[Dict[str, Any]]:
    """Every Discord server the bot is in, biggest first.

    Read entirely from what the gateway already told us, so it costs no API calls: the member
    counts arrive with the server itself. `configured` marks the ones that have set something
    with /server-settings, which is the closest thing to a sign a server actually uses the bot.

    :rtype: List[Dict[str, Any]]
    """
    try:
        from rasmai.bot.core import bot
        guilds = list(bot.guilds)
    except Exception:
        return []
    connection = get_database_connection()
    try:
        configured = {str(row["guild_id"]) for row in _rows(connection, "SELECT guild_id FROM guild_settings")}
    finally:
        connection.close()
    out = []
    for guild in guilds:
        me = guild.me
        out.append({
            "id": str(guild.id),
            "name": guild.name,
            "icon": str(guild.icon.url) if guild.icon else "",
            "members": int(guild.member_count or 0),
            "ownerId": str(guild.owner_id or ""),
            "joinedAt": me.joined_at.isoformat(timespec="seconds") if me is not None and me.joined_at else "",
            "shard": int(guild.shard_id or 0),
            "configured": str(guild.id) in configured,
        })
    out.sort(key=lambda g: g["members"], reverse=True)
    # the owners are worth a name, and they are few enough that one lookup each is fine
    known = people([g["ownerId"] for g in out if g["ownerId"]])
    return [{**g, "owner": known.get(g["ownerId"], {}).get("name", "")} for g in out]


# Both chart databases refresh on their own: otoge-db when its copy is a week old, the simai
# repository when the commit it was read from has moved. Neither has a way to say "now", and the
# only way to force one was to restart the bot. These run the same code the scheduled refresh runs,
# on a thread, one at a time, so the page can start one and poll for how it went.
SOURCES = ("simai", "otoge")
_updates: Dict[str, Dict[str, Any]] = {}
_update_lock = threading.Lock()


def _run_update(source: str) -> None:
    """Fetch one chart database again, whatever its age, and record how it went."""
    started = time.time()
    try:
        if source == "simai":
            from rasmai.scraping import simai, simai_bulk
            held = simai_bulk.update(force=True)
            simai.refresh()
            said = f"{held:,} charts held, database filled from them"
        else:
            from rasmai.bot.builders.charts.index import refresh_shared_index
            from rasmai.scraping.otoge import CachedOtogeDB
            fetched = CachedOtogeDB().refresh_now()
            if fetched:
                refresh_shared_index()
            said = "fetched and the chart index rebuilt" if fetched else "nothing came back, the copy held stands"
        done = {"running": False, "ok": True, "said": said}
    except Exception as error:                       # a failed update must not take the page with it
        logger.exception("%s update failed", source)
        done = {"running": False, "ok": False, "said": str(error)[:200]}
    with _update_lock:
        _updates[source] = {**done, "at": datetime.now().isoformat(timespec="seconds"),
                            "seconds": round(time.time() - started, 1)}


def start_update(source: str) -> Dict[str, Any]:
    """Start a refresh of one chart database, or say no when that one is already running.

    :param source: Which database: "simai" or "otoge".
    :type source: str
    :rtype: Dict[str, Any]
    """
    if source not in SOURCES:
        return {"ok": False, "error": "unknown_source"}
    with _update_lock:
        if (_updates.get(source) or {}).get("running"):
            return {"ok": False, "error": "already_running", **_updates[source]}
        _updates[source] = {"running": True, "ok": True, "said": "running",
                            "at": datetime.now().isoformat(timespec="seconds")}
    threading.Thread(target=_run_update, args=(source,), name=f"rasmai-update-{source}", daemon=True).start()
    return {"ok": True, "running": True, "source": source}


def update_state() -> Dict[str, Any]:
    """How each chart database was last refreshed by hand, and whether one is running now."""
    with _update_lock:
        return {source: dict(_updates.get(source) or {"running": False}) for source in SOURCES}


def _simai_progress() -> Dict[str, Any]:
    """How far the chart crawl has got; empty when it has not started or cannot be read."""
    try:
        from rasmai.scraping import simai
        return simai.progress()
    except Exception:
        return {}


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
        "simai": _simai_progress(),
        "updates": update_state(),
        "busiest": _named([{"userId": r["user_id"], "plays": int(r["plays"])} for r in busiest], known),
        "activity": activity,
        "growth": growth,
        "store": store,
        "live": live,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
    }
