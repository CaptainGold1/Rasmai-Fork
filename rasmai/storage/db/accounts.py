from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Any
import re
import secrets

from rasmai.security import LOGIN_CODE_TTL, _hash_code, decrypt_token, encrypt_token
from rasmai.storage.db.connection import _dump_json_column, _load_json_column, get_database_connection


def issue_login_code(user_id: str, region: str) -> str:
    """Random, single-use, short-lived code bound to one Discord user.

    :param user_id: The Discord user id.
    :type user_id: str
    :param region: intl, jp or cn.
    :type region: str
    :rtype: str
    """
    code = secrets.token_urlsafe(24)
    now = datetime.now()
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                "DELETE FROM login_codes WHERE created_at < ?", ((now - timedelta(days=1)).isoformat(),)
            )
            connection.execute(
                "INSERT INTO login_codes (code_hash, user_id, region, created_at) VALUES (?, ?, ?, ?)",
                (_hash_code(code), user_id, region, now.isoformat()),
            )
    finally:
        connection.close()
    return code


def _lookup_login_code(code: str, consume: bool) -> Optional[Tuple[str, str]]:
    if not code or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", code):
        return None
    connection = get_database_connection()
    try:
        row = connection.execute(
            "SELECT user_id, region, created_at, used_at FROM login_codes WHERE code_hash = ?", (_hash_code(code),)
        ).fetchone()
        if row is None or row["used_at"]:
            return None
        try:
            if datetime.now() - datetime.fromisoformat(row["created_at"]) > LOGIN_CODE_TTL:
                return None
        except ValueError:
            return None
        if consume:
            with connection:
                updated = connection.execute(
                    "UPDATE login_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL",
                    (datetime.now().isoformat(), _hash_code(code)),
                ).rowcount
            if not updated:
                return None
        return str(row["user_id"]), str(row["region"]), str(row["created_at"])
    finally:
        connection.close()


def login_code_issued_at(code: str) -> Optional[datetime]:
    """When a login code was issued, whether or not it has been used since.

    :param code: The login code.
    :type code: str
    :rtype: Optional[datetime]
    """
    if not code or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", code):
        return None
    connection = get_database_connection()
    try:
        row = connection.execute("SELECT created_at FROM login_codes WHERE code_hash = ?", (_hash_code(code),)).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    try:
        return datetime.fromisoformat(row["created_at"])
    except ValueError:
        return None


def peek_login_code(code: str) -> Optional[Tuple[str, str, str]]:
    return _lookup_login_code(code, consume=False)


def mark_login_code_verified(code: str) -> bool:
    """Record that the person holding this code passed the human check.

    :param code: The login code.
    :type code: str
    :rtype: bool
    """
    if not code or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", code):
        return False
    connection = get_database_connection()
    try:
        with connection:
            return bool(connection.execute(
                "UPDATE login_codes SET verified_at = ? WHERE code_hash = ? AND used_at IS NULL",
                (datetime.now().isoformat(), _hash_code(code)),
            ).rowcount)
    finally:
        connection.close()


def login_code_verified(code: str) -> bool:
    if not code or not re.fullmatch(r"[A-Za-z0-9_-]{20,64}", code):
        return False
    connection = get_database_connection()
    try:
        row = connection.execute("SELECT verified_at FROM login_codes WHERE code_hash = ?", (_hash_code(code),)).fetchone()
    finally:
        connection.close()
    return bool(row and row["verified_at"])


def consume_login_code(code: str) -> Optional[Tuple[str, str, str]]:
    return _lookup_login_code(code, consume=True)


def login_code_expiry(created: Optional[datetime] = None) -> datetime:
    return (created or datetime.now()) + LOGIN_CODE_TTL


# the minute each account was last noted as active, so a run of commands writes once
_SEEN: Dict[str, str] = {}


def upsert_connected_account(user_id: str, region: str, token: str, official_profile: Optional[Dict[str, Any]] = None, snapshot: Optional[Dict[str, Any]] = None) -> None:
    now = datetime.now().isoformat()
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO connected_accounts
                    (user_id, region, token, official_profile, latest_snapshot, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    region           = excluded.region,
                    token            = excluded.token,
                    official_profile = COALESCE(excluded.official_profile, connected_accounts.official_profile),
                    latest_snapshot  = COALESCE(excluded.latest_snapshot, connected_accounts.latest_snapshot),
                    updated_at       = excluded.updated_at,
                    session_expired  = ''
                """,
                (
                    user_id,
                    region,
                    encrypt_token(token),
                    _dump_json_column(official_profile),
                    _dump_json_column(snapshot),
                    now,
                    now,
                ),
            )
    finally:
        connection.close()


def get_connected_account(user_id: str) -> Optional[Dict[str, Any]]:
    connection = get_database_connection()
    try:
        row = connection.execute(
            "SELECT * FROM connected_accounts WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return {
        "userId": row["user_id"],
        "region": row["region"],
        "token": decrypt_token(str(row["token"] or "")),
        "officialProfile": _load_json_column(row["official_profile"]),
        "latestSnapshot": _load_json_column(row["latest_snapshot"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "sessionExpired": row["session_expired"] or "",
        "shareSlug": row["share_slug"] or "",
        "seenAt": row["seen_at"] or "",
    }


def touch_account(user_id: str) -> None:
    """Note that the person used the bot or the site just now, to the minute.

    Written at most once a minute per account so a burst of commands is one write, not dozens.

    :param user_id: The Discord user id.
    :type user_id: str
    """
    stamp = datetime.now().replace(second=0, microsecond=0).isoformat()
    if _SEEN.get(user_id) == stamp:
        return
    _SEEN[user_id] = stamp
    connection = get_database_connection()
    try:
        with connection:
            connection.execute("UPDATE connected_accounts SET seen_at = ? WHERE user_id = ?", (stamp, user_id))
    finally:
        connection.close()


def set_share_slug(user_id: str, slug: Optional[str]) -> Optional[str]:
    """Give the account a public profile address, or take it away with ``None``.

    A new slug replaces the old one, so a link that has been passed around stops working the
    moment the person asks for a fresh one.

    :param user_id: The Discord user id.
    :type user_id: str
    :param slug: The new slug, or ``None`` to remove the public profile.
    :type slug: Optional[str]
    :returns: The slug now in force, or ``None``.
    :rtype: Optional[str]
    """
    connection = get_database_connection()
    try:
        with connection:
            connection.execute("UPDATE connected_accounts SET share_slug = ? WHERE user_id = ?", (slug, user_id))
    finally:
        connection.close()
    return slug


def account_by_share_slug(slug: str) -> Optional[Dict[str, Any]]:
    """The account a public profile link points at, or ``None`` when nothing matches.

    :param slug: The slug from the address.
    :type slug: str
    :rtype: Optional[Dict[str, Any]]
    """
    if not slug or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", slug):
        return None
    connection = get_database_connection()
    try:
        row = connection.execute("SELECT user_id FROM connected_accounts WHERE share_slug = ?", (slug,)).fetchone()
    finally:
        connection.close()
    return get_connected_account(str(row["user_id"])) if row else None


def mark_session_expired(user_id: str, when: str = "") -> None:
    """Record that maimai DX NET refused the saved sign-in, so the site can say so before the next read.

    The next successful ``/login`` clears it, because the upsert writes the column back to empty.

    :param user_id: The Discord user id.
    :type user_id: str
    :param when: When it was refused, ISO 8601; now by default.
    :type when: str
    """
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                "UPDATE connected_accounts SET session_expired = ? WHERE user_id = ? AND session_expired = ''",
                (when or datetime.now().isoformat(timespec="seconds"), user_id),
            )
    finally:
        connection.close()


def delete_connected_account(user_id: str) -> bool:
    connection = get_database_connection()
    try:
        with connection:
            cursor = connection.execute(
                "DELETE FROM connected_accounts WHERE user_id = ?", (user_id,)
            )
            connection.execute("DELETE FROM chart_play_counts WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM area_progress WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM chart_scores WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM quiet_reads WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM login_codes WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM rating_history WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM play_judgements WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM notify_state WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0
    finally:
        connection.close()


def update_account_snapshot(user_id: str, official_profile: Optional[Dict[str, Any]], snapshot: Optional[Dict[str, Any]]) -> None:
    """Refresh the stored profile and compact score snapshot after an analysis.

    :param user_id: The Discord user id.
    :type user_id: str
    :param snapshot: The stored copy of the player's scores.
    :type snapshot: Optional[Dict[str, Any]]
    """
    connection = get_database_connection()
    try:
        with connection:
            connection.execute(
                """
                UPDATE connected_accounts
                SET official_profile = COALESCE(?, official_profile),
                    latest_snapshot  = COALESCE(?, latest_snapshot),
                    updated_at       = ?,
                    -- a read that landed proves the session works, whatever an earlier one thought
                    session_expired  = ''
                WHERE user_id = ?
                """,
                (_dump_json_column(official_profile), _dump_json_column(snapshot), datetime.now().isoformat(), user_id),
            )
    finally:
        connection.close()
