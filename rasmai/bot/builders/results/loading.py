from datetime import datetime
from typing import Dict, Optional
import asyncio
import discord
import logging

from rasmai.engine import analysis
from rasmai.bot.state import reads
from rasmai.bot.state.cache import CachedAnalysis, cache_get
from rasmai.bot.ui.progress import Progress
from rasmai.config import RECHECK_AFTER
from rasmai.storage.db import touch_account, save_play_counts

from rasmai.bot.builders.results.stored import (  # noqa: F401
    downtime_note,
    _snapshot_time,
    _analysis_from_store,
    _stale_analysis,
    Changed,
    _fresh_areas,
    _attach_areas,
    _light_check,
    _still_current,
    _stored_analysis,
    human_age,
    note_read_age,
)
from rasmai.bot.builders.results.fresh import (  # noqa: F401
    latest_play_times,
    run_full_analysis,
    _fresh_analysis,
)

logger = logging.getLogger(__name__)


async def ensure_target_play_counts(interaction: discord.Interaction, cached: CachedAnalysis, challenge: str) -> None:
    """Read play counts for the charts this challenge level targets.

    The analysis pass only fetched counts for the level it ran with; another level
    picks different charts, so its first showing fills in the gaps and then the
    views for that level are rebuilt with the counts in place.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction
    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :param challenge: How bold the targets are: ``"easy"``, ``"balanced"``, ``"hard"`` or ``"extreme"``.
    :type challenge: str
    """
    a = cached.analyzer
    if getattr(a, "_official_session", None) is None:
        return
    challenge = challenge if challenge in analysis.CHALLENGES else "balanced"
    recs, _summary = cached.analysis_for(challenge)
    plan = cached.plan_for(None, False, challenge)
    wanted = a.play_count_targets(recommendations=recs, plan=plan)
    if not wanted:
        return
    label = analysis.challenge_for(challenge).label.lower()
    progress = Progress(interaction, title=f"Reading play counts for {label} targets").only("plays")
    await progress.flush(force=True)
    try:
        fetched = await asyncio.to_thread(a.fetch_official_play_counts, wanted, cached.region, progress.from_thread())
    except Exception:
        logger.exception("Play count top-up for a challenge level failed; continuing without it")
        fetched = {}
    finally:
        progress.close()
    if not fetched:
        return
    save_play_counts(cached.user_id, fetched)
    a.play_counts.update(fetched)
    profile = getattr(a, "play_profile", None)
    if profile is not None:
        profile.play_counts.update(fetched)   # the profile carries its own copy, and the posters read that one
    # counts feed the ranking, so everything built for this level is stale
    if challenge == getattr(a, "challenge", "balanced"):
        cached.recommendations, cached.value_charts = await asyncio.to_thread(a.generate_recommendations)
    cached.forget(challenge)


_inflight: Dict[str, "asyncio.Future[Optional[CachedAnalysis]]"] = {}


async def load_analysis(interaction: discord.Interaction, force: bool = False) -> Optional[CachedAnalysis]:
    """The user's analysis, from memory, from the stored read, or from maimai DX NET, in that order.

    Memory holds finished analyses for a few minutes so switching views never re-reads.
    After that the stored read is reused for as long as a light check of maimai DX NET
    (profile and recent plays, a few seconds) says nothing has changed; a full read of
    every score page happens only when it has, when the stored read is a week old, or
    when `force` asks for it. A second command from the same person while their scores
    are being read waits for that read instead of starting another. Replies on its own
    when no account is linked and returns None.

    :param interaction: The Discord interaction the command arrived on.
    :type interaction: discord.Interaction
    :param force: Whether to act even when the stored copy is current.
    :type force: bool
    :rtype: Optional[CachedAnalysis]
    """
    user_id = str(interaction.user.id)
    # every command counts as using the app, not just a read: the developer page reports on it
    asyncio.get_running_loop().run_in_executor(None, touch_account, user_id)
    if not force:
        cached = cache_get(user_id)
        if cached is not None:
            if datetime.now() - cached.checked < RECHECK_AFTER or await _still_current(user_id, cached):
                return cached
    running = _inflight.get(user_id)
    if running is not None:
        # another command of theirs is already reading: wait on that one rather than start a second
        await interaction.edit_original_response(
            content="Your scores are already being read for another command; this one follows it.",
            embed=None, attachments=[], view=None,
        )
        return await asyncio.shield(running)
    elsewhere = reads.claim(user_id, reads.DISCORD)
    if elsewhere is not None:
        # a read started somewhere this command cannot wait on, so say so rather than read twice
        await interaction.edit_original_response(
            content=f"Your scores are being read right now, started from **{elsewhere}**. "
                    "Give it a moment and run this again; reading twice at once would only slow both down.",
            embed=None, attachments=[], view=None,
        )
        return None
    task = asyncio.ensure_future(_fresh_analysis(interaction, user_id, force))
    _inflight[user_id] = task
    try:
        return await task
    finally:
        _inflight.pop(user_id, None)
        reads.release(user_id)
