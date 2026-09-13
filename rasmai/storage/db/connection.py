from typing import Dict, Optional, Any
import json
import sqlite3
import threading
import logging

from rasmai.config import DATABASE_PATH
from rasmai.util import _json_safe

logger = logging.getLogger(__name__)


_database_ready = False


_database_lock = threading.Lock()


def get_database_connection() -> sqlite3.Connection:
    """Open the local account database, creating it on first use.

    :rtype: sqlite3.Connection
    """
    global _database_ready
    with _database_lock:
        if not _database_ready:
            DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(DATABASE_PATH) as setup:
                setup.execute("PRAGMA journal_mode=WAL")
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS connected_accounts (
                        user_id          TEXT PRIMARY KEY,
                        region           TEXT NOT NULL,
                        token            TEXT NOT NULL,
                        official_profile TEXT,
                        latest_snapshot  TEXT,
                        created_at       TEXT NOT NULL,
                        updated_at       TEXT NOT NULL
                    )
                    """
                )
                try:
                    setup.execute("ALTER TABLE connected_accounts ADD COLUMN session_expired TEXT NOT NULL DEFAULT ''")
                except sqlite3.OperationalError:
                    pass      # already there
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS login_codes (
                        code_hash  TEXT PRIMARY KEY,
                        user_id    TEXT NOT NULL,
                        region     TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        used_at    TEXT
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_settings (
                        user_id    TEXT PRIMARY KEY,
                        settings   TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rating_history (
                        user_id     TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        rating      INTEGER NOT NULL,
                        best50      INTEGER NOT NULL,
                        new_total   INTEGER NOT NULL,
                        old_total   INTEGER NOT NULL,
                        charts      INTEGER NOT NULL,
                        plays       INTEGER NOT NULL,
                        PRIMARY KEY (user_id, recorded_at)
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS area_progress (
                        user_id     TEXT NOT NULL,
                        kind        TEXT NOT NULL,
                        name        TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        distance    INTEGER NOT NULL,
                        next_reward INTEGER,
                        state       TEXT NOT NULL,
                        plays       INTEGER NOT NULL DEFAULT 0,
                        period_start TEXT,
                        period_end   TEXT,
                        PRIMARY KEY (user_id, kind, name, recorded_at)
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chart_play_counts (
                        user_id    TEXT NOT NULL,
                        chart_key  TEXT NOT NULL,
                        plays      INTEGER NOT NULL,
                        fetched_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, chart_key)
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS news_state (   -- crawl state per source (etag, payload, last check); the name predates the sources module
                        source        TEXT PRIMARY KEY,
                        etag          TEXT NOT NULL DEFAULT '',
                        last_modified TEXT NOT NULL DEFAULT '',
                        payload       TEXT NOT NULL DEFAULT '',
                        checked_at    TEXT NOT NULL
                    )
                    """
                )
                try:
                    setup.execute("ALTER TABLE login_codes ADD COLUMN verified_at TEXT")
                except sqlite3.OperationalError:
                    pass          # already there
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS guild_settings (
                        guild_id   TEXT PRIMARY KEY,
                        settings   TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notify_state (
                        user_id     TEXT PRIMARY KEY,
                        rating      INTEGER NOT NULL DEFAULT 0,
                        notified_at TEXT NOT NULL
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS quiet_reads (
                        user_id     TEXT PRIMARY KEY,
                        read_at     TEXT NOT NULL,
                        plays_added INTEGER NOT NULL DEFAULT 0,
                        error       TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chart_videos (
                        song       TEXT PRIMARY KEY,
                        page       TEXT NOT NULL DEFAULT '',
                        videos     TEXT NOT NULL DEFAULT '{}',
                        fetched_at TEXT NOT NULL
                    )
                    """
                )
                try:
                    setup.execute("ALTER TABLE chart_videos ADD COLUMN unlock TEXT")    # NULL until the page was read for it
                except sqlite3.OperationalError:
                    pass          # already there
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chart_scores (
                        user_id     TEXT NOT NULL,
                        chart_key   TEXT NOT NULL,
                        played_at   TEXT NOT NULL,
                        achievement REAL NOT NULL,
                        dx_score    INTEGER NOT NULL DEFAULT 0,
                        fc          TEXT NOT NULL DEFAULT '',
                        fs          TEXT NOT NULL DEFAULT '',
                        source      TEXT NOT NULL DEFAULT 'play',
                        PRIMARY KEY (user_id, chart_key, played_at)
                    )
                    """
                )
                for column in ("max_dx INTEGER NOT NULL DEFAULT 0", "track INTEGER NOT NULL DEFAULT 0",
                               "judgement TEXT NOT NULL DEFAULT ''"):
                    try:
                        setup.execute(f"ALTER TABLE chart_scores ADD COLUMN {column}")
                    except sqlite3.OperationalError:
                        pass      # already there
                setup.execute(
                    """
                    CREATE TABLE IF NOT EXISTS play_judgements (   -- one play's judgement page: counts per note type, timing split
                        user_id     TEXT NOT NULL,
                        idx         TEXT NOT NULL,
                        chart_key   TEXT NOT NULL,
                        played_at   TEXT NOT NULL,
                        achievement REAL NOT NULL,
                        fast        INTEGER NOT NULL DEFAULT 0,
                        late        INTEGER NOT NULL DEFAULT 0,
                        notes       TEXT NOT NULL,
                        PRIMARY KEY (user_id, idx)
                    )
                    """
                )
            _database_ready = True

    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _dump_json_column(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    try:
        return json.dumps(_json_safe(value), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        logger.warning(f"Failed to serialise account column: {error}")
        return None


def _load_json_column(value: Any) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
