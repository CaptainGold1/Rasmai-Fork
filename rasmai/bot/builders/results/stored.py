from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
import asyncio
import discord
import logging

from rasmai.bot.state.cache import CachedAnalysis, cache_put
from rasmai.bot.core import watch
from rasmai.bot.tasks.chart_db import resolve_unknown_later
from rasmai.bot.tasks.presence import maintenance_at
from rasmai.bot.ui.formatting import stamp
from rasmai.bot.state.snapshots import analyzer_from_snapshot, collect_judgements, record_plays
from rasmai.scraping.scraper import SessionRejected, MaimaiRatingAnalyzer
from rasmai.config import DEBUG_MODE, MAIMAI_BASE_URLS, SNAPSHOT_MAX_AGE
from rasmai.security import public_reason
from rasmai.storage.db import get_connected_account, mark_session_expired, record_area_progress

logger = logging.getLogger(__name__)


def downtime_note() -> str:
    """Why maimai DX NET cannot be read right now, or "" when it can.

    The presence watch already knows the maintenance schedule and whether the site answers;
    a read attempted during either only fails slowly and used to blame the player's session.

    :rtype: str
    """
    window = maintenance_at()
    if window.active:
        return f"maimai DX NET is in maintenance, back {stamp(window.moment, 'R')}."
    if not getattr(watch, "reachable", True):
        return "maimai DX NET is not answering right now."
    return ""


def _snapshot_time(account: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str((account.get("latestSnapshot") or {}).get("recordedAt", "")))
    except ValueError:
        return None


async def _analysis_from_store(user_id: str, account: Dict[str, Any]) -> Optional[CachedAnalysis]:
    """An analysis over the stored read, remembered in memory with the time the scores were read.

    :param user_id: The Discord user id.
    :type user_id: str
    :param account: The linked account, as stored.
    :type account: Dict[str, Any]
    :rtype: Optional[CachedAnalysis]
    """
    analyzer = await asyncio.to_thread(analyzer_from_snapshot, user_id, account)
    if analyzer is None:
        return None
    recommendations, value_charts = await asyncio.to_thread(analyzer.generate_recommendations)
    cached = CachedAnalysis(user_id=user_id, region=analyzer.region, analyzer=analyzer,
                            recommendations=recommendations, value_charts=value_charts)
    cached.extras["read_at"] = _snapshot_time(account)
    cache_put(cached)
    # a stored read answers at once; when it holds songs the database lacks, the fetch runs behind it
    # and this analysis is rebuilt in place, so the next command already has the constants
    resolve_unknown_later(cached, asyncio.get_running_loop())
    return cached


async def _stale_analysis(interaction: discord.Interaction, user_id: str, account: Dict[str, Any],
                          error: Exception, relink: bool = True) -> Optional[CachedAnalysis]:
    """The last stored read, when maimai cannot be read right now, with a note saying so.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction
    :param user_id: The Discord user id.
    :type user_id: str
    :param account: The linked account, as stored.
    :type account: Dict[str, Any]
    :param error: What went wrong.
    :type error: Exception
    :rtype: Optional[CachedAnalysis]
    """
    if isinstance(error, SessionRejected):
        # both command paths land here, so this is where the site learns the sign-in has to be redone
        await asyncio.to_thread(mark_session_expired, user_id)
    cached = await _analysis_from_store(user_id, account)
    if cached is None:
        return None
    recorded = _snapshot_time(account)
    when = stamp(recorded, "R") if recorded else "earlier"
    advice = "Run `/login` to link again and refresh." if relink else "Try `/refresh` later."
    try:
        await interaction.followup.send(f"{public_reason(error)}\n-# Showing your last read from {when} instead. {advice}", ephemeral=True)
    except discord.HTTPException:
        pass
    return cached


class Changed(Exception):
    """The light check found the stored scores out of date; the message says how."""


# the map data of the latest light check per user, to attach to the analysis the check confirmed
_fresh_areas: Dict[str, Tuple[Dict[str, Any], datetime]] = {}


def _attach_areas(user_id: str, cached: CachedAnalysis) -> None:
    fresh = _fresh_areas.pop(user_id, None)
    if fresh is not None:
        cached.analyzer.events_data, cached.analyzer.events_read_at = fresh


async def _light_check(user_id: str, account: Dict[str, Any], token: str, region: str) -> Tuple[Any, List[Dict[str, Any]]]:
    """Sign in and read the profile and recent plays; raise Changed when the stored scores are out of date.

    New plays are recorded as they would be by the daily read. Any of them, a changed play
    count or a changed rating means a full read is due. Errors from maimai propagate.

    :param user_id: The Discord user id.
    :type user_id: str
    :param account: The linked account, as stored.
    :type account: Dict[str, Any]
    :param token: The saved maimai session.
    :type token: str
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: str
    :rtype: Tuple[Any, List[Dict[str, Any]]]
    """
    probe = await asyncio.to_thread(lambda: MaimaiRatingAnalyzer(debug=DEBUG_MODE))
    player, plays = await asyncio.to_thread(probe.fetch_official_check, token, region)
    added = await asyncio.to_thread(record_plays, user_id, probe, plays)
    # the judgement pages of new plays are read behind the command, not in front of it
    asyncio.get_running_loop().run_in_executor(None, collect_judgements, user_id, probe, plays, region)
    if probe.events_read_at is not None:
        # every reading of the map, paired with the play count, sharpens the plays-to-next-reward estimate
        await asyncio.to_thread(record_area_progress, user_id, probe.events_data, int(player.total_play_count or 0))
        _fresh_areas[user_id] = (probe.events_data, probe.events_read_at)
    profile = account.get("officialProfile") or {}
    snapshot = account.get("latestSnapshot") or {}
    stored_plays = int(profile.get("totalPlayCount") or 0)
    stored_rating = int(profile.get("rating") or snapshot.get("rating") or 0)
    if added > 0:
        raise Changed(f"{added} new play(s)")
    if player.total_play_count and stored_plays and int(player.total_play_count) != stored_plays:
        raise Changed(f"play count {stored_plays} -> {player.total_play_count}")
    if player.rating and stored_rating and int(player.rating) != stored_rating:
        raise Changed(f"rating {stored_rating} -> {player.rating}")
    return player, plays


async def _still_current(user_id: str, cached: CachedAnalysis) -> bool:
    """Whether an analysis in memory still matches maimai DX NET; False means a full read is due.

    Runs for a command (never for the buttons under a result) when the last check is a few
    minutes old, so a session played between two commands is noticed without anyone asking.
    A check that cannot reach maimai keeps the memory copy rather than failing the command.

    :param user_id: The Discord user id.
    :type user_id: str
    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :rtype: bool
    """
    if downtime_note():
        cached.checked = datetime.now()
        return True
    account = await asyncio.to_thread(get_connected_account, user_id)
    token = str(account.get("token", "")) if account else ""
    if not token:
        return True
    region = str(account.get("region", "intl")).strip().lower()
    try:
        player, plays = await _light_check(user_id, account, token, region if region in MAIMAI_BASE_URLS else "intl")
    except Changed as why:
        logger.info("memory copy for %s is out of date: %s", user_id, why)
        return False
    except Exception as error:
        logger.info("light check for %s failed, keeping the memory copy: %s", user_id, public_reason(error))
        cached.checked = datetime.now()
        return True
    cached.checked = datetime.now()
    cached.analyzer.player = player
    cached.analyzer.recent_songs = plays
    _attach_areas(user_id, cached)
    return True


async def _stored_analysis(interaction: discord.Interaction, user_id: str, account: Dict[str, Any],
                           token: str, region: str) -> Optional[CachedAnalysis]:
    """The stored read, when a light check of maimai DX NET says nothing changed since it; None when a full read is due.

    The check signs in and reads the profile and the recent-plays page. New plays are
    recorded as they would be by the daily read, and any of them, a changed play count or
    a changed rating means the stored scores are out of date. When maimai cannot be
    read at all, the stored copy is shown with a note rather than failing.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction
    :param user_id: The Discord user id.
    :type user_id: str
    :param account: The linked account, as stored.
    :type account: Dict[str, Any]
    :param token: The saved maimai session.
    :type token: str
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: str
    :rtype: Optional[CachedAnalysis]
    """
    snapshot = account.get("latestSnapshot") or {}
    recorded = _snapshot_time(account)
    if not snapshot.get("charts") or recorded is None or datetime.now() - recorded > SNAPSHOT_MAX_AGE:
        return None
    try:
        player, plays = await _light_check(user_id, account, token, region)
    except Changed as why:
        logger.info("stored read for %s is out of date: %s", user_id, why)
        return None
    except SessionRejected as error:
        return await _stale_analysis(interaction, user_id, account, error)
    except Exception as error:
        logger.info("light check for %s failed: %s", user_id, public_reason(error))
        return await _stale_analysis(interaction, user_id, account, error, relink=False)
    cached = await _analysis_from_store(user_id, account)
    if cached is None:
        return None
    # the check brought the live profile (avatar included), the recent plays and the map; the stored read has none of them live
    cached.analyzer.player = player
    cached.analyzer.recent_songs = plays
    _attach_areas(user_id, cached)
    return cached


def human_age(moment: Optional[datetime]) -> str:
    if moment is None:
        return "earlier"
    minutes = max(0, int((datetime.now() - moment).total_seconds() // 60))
    if minutes < 2:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h ago"
    return f"{hours // 24} days ago"


def note_read_age(embed: Optional[discord.Embed], cached: Optional[CachedAnalysis]) -> None:
    """Say in the footer when the scores behind a reply were read, when they were not read just now.

    :param embed: The embed being built.
    :type embed: Optional[discord.Embed]
    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    """
    if embed is None or cached is None:
        return
    read_at = cached.extras.get("read_at")
    if not isinstance(read_at, datetime):
        return
    current = getattr(getattr(embed, "footer", None), "text", None) or ""
    embed.set_footer(text=(f"{current} · " if current else "") + f"scores as read {human_age(read_at)} · /refresh reads them again")
