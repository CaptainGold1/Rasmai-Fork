from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
import asyncio
import discord
import logging

from rasmai.bot.state.cache import CachedAnalysis, cache_put
from rasmai.bot.core import fetch_snapshot_limited
from rasmai.bot.tasks.chart_db import resolve_unknown
from rasmai.bot.ui.formatting import stamp, NOT_CONNECTED_MESSAGE
from rasmai.bot.ui.progress import Progress
from rasmai.bot.state.snapshots import collect_judgements, persist_progress
from rasmai.scraping.scraper import SessionRejected, MaimaiRatingAnalyzer
from rasmai.config import DEBUG_EXPORT_JSON, DEBUG_MODE, MAIMAI_BASE_URLS
from rasmai.storage.db import (
    get_connected_account, load_judgements, load_play_counts, load_recorded_plays, save_play_counts,
)
from rasmai.storage.models import Recommendation
from rasmai.util import export_debug_payload
from rasmai.bot.builders.results.stored import _analysis_from_store, _snapshot_time, _stale_analysis, _stored_analysis, downtime_note

logger = logging.getLogger(__name__)


def latest_play_times(analyzer: "MaimaiRatingAnalyzer") -> Dict[Tuple[str, str, str], datetime]:
    """When each chart in the recent-plays list was last played, keyed like play counts.

    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: 'MaimaiRatingAnalyzer'
    :rtype: Dict[Tuple[str, str, str], datetime]
    """
    latest: Dict[Tuple[str, str, str], datetime] = {}
    for record in analyzer.recent_songs or []:
        try:
            played = datetime.fromisoformat(str(record.get("playedAt", "")))
        except ValueError:
            continue
        if played.tzinfo is None:
            played = played.astimezone()
        key = (
            analyzer._normalize_official_song_name(str(record.get("songName", ""))).casefold(),
            str(record.get("musicType") or "std").lower(),
            str(record.get("difficulty") or "").lower(),
        )
        if key not in latest or played > latest[key]:
            latest[key] = played
    return latest


async def run_full_analysis(
    analyzer: "MaimaiRatingAnalyzer",
    snapshot: Dict[str, Any],
    user_id: str,
    region: str,
    progress: Optional[Progress] = None,
) -> Tuple[List[Recommendation], Dict]:
    """Analyse, fetch play counts for the charts that matter, analyse again.

    :param analyzer: The scraper and the analysis it holds.
    :type analyzer: 'MaimaiRatingAnalyzer'
    :param snapshot: The stored copy of the player's scores.
    :type snapshot: Dict[str, Any]
    :param user_id: The Discord user id.
    :type user_id: str
    :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
    :type region: str
    :rtype: Tuple[List[Recommendation], Dict]
    """
    tell = progress.from_thread() if progress else (lambda *args, **kwargs: None)
    analyzer.player = snapshot["player"]
    analyzer.songs = snapshot["songs"]
    analyzer.recent_songs = snapshot.get("recentSongsData", [])
    analyzer.events_data = snapshot.get("eventsData") or {"areaEvents": [], "eventAreaEvents": []}
    analyzer.play_counts = load_play_counts(user_id, latest_play_times(analyzer))
    analyzer.recorded_plays = load_recorded_plays(user_id)
    analyzer.judgements = load_judgements(user_id)
    recommendations, value_charts = await asyncio.to_thread(analyzer.generate_recommendations)
    if await asyncio.to_thread(resolve_unknown, analyzer, tell):
        recommendations, value_charts = await asyncio.to_thread(analyzer.generate_recommendations)
    wanted = analyzer.play_count_targets()
    if wanted:
        try:
            fetched = await asyncio.to_thread(analyzer.fetch_official_play_counts, wanted, region, tell)
        except Exception:
            logger.exception("Play count pass failed; continuing without it")
            fetched = {}
        if fetched:
            save_play_counts(user_id, fetched)
            analyzer.play_counts.update(fetched)
            recommendations, value_charts = await asyncio.to_thread(analyzer.generate_recommendations)
            top_up = analyzer.play_count_targets(limit=20)
            if top_up:
                # the second pass continues the same counter instead of restarting it
                base = len(wanted)
                continued = (lambda key, done=0, total=0, detail="": tell(key, base + done, base + total, detail))
                try:
                    extra = await asyncio.to_thread(analyzer.fetch_official_play_counts, top_up, region, continued)
                except Exception:
                    logger.exception("Play count top-up failed; continuing")
                    extra = {}
                if extra:
                    save_play_counts(user_id, extra)
                    analyzer.play_counts.update(extra)
                    recommendations, value_charts = await asyncio.to_thread(analyzer.generate_recommendations)
    elif progress:
        progress.skip("plays", "Play counts already known")
    if progress:
        progress.finish("plays")
        progress.report("analysis", 1, 1)
    return recommendations, value_charts


async def _fresh_analysis(interaction: discord.Interaction, user_id: str, force: bool = False) -> Optional[CachedAnalysis]:
    account = await asyncio.to_thread(get_connected_account, user_id)
    token = str(account.get("token", "")) if account else ""
    region = str(account.get("region", "intl")).strip().lower() if account else "intl"
    if region not in MAIMAI_BASE_URLS:
        region = "intl"
    if not token:
        await interaction.edit_original_response(content=NOT_CONNECTED_MESSAGE, embed=None, attachments=[], view=None)
        return None
    down = downtime_note()
    if down:
        stored = await _analysis_from_store(user_id, account)
        if stored is not None:
            recorded = _snapshot_time(account)
            try:
                await interaction.followup.send(
                    f"{down}\n-# Showing your last read from {stamp(recorded, 'R') if recorded else 'earlier'} instead.", ephemeral=True)
            except discord.HTTPException:
                pass
            return stored
        await interaction.edit_original_response(content=f"{down} Try again once it is back; `/ping` shows the schedule.",
                                                 embed=None, attachments=[], view=None)
        return None
    if not force:
        stored = await _stored_analysis(interaction, user_id, account, token, region)
        if stored is not None:
            return stored

    # the constructor may refresh the chart database, which is minutes of git and image work
    analyzer = await asyncio.to_thread(lambda: MaimaiRatingAnalyzer(debug=DEBUG_MODE))
    progress = Progress(interaction)
    await progress.flush(force=True)
    try:
        try:
            snapshot = await fetch_snapshot_limited(analyzer, token, region, progress.from_thread())
        except SessionRejected as error:
            stale = await _stale_analysis(interaction, user_id, account, error)
            if stale is not None:
                return stale
            raise
        recommendations, value_charts = await run_full_analysis(analyzer, snapshot, user_id, region, progress)
        progress.report("render", 0, 1)
        await progress.flush(force=True)
    finally:
        progress.close()
    if DEBUG_EXPORT_JSON:
        export_debug_payload({
            "exportedAt": datetime.now().isoformat(),
            "source": "analyze:official",
            "region": region,
            "userId": user_id,
            "connectedTokenUsed": True,
            "player": analyzer.player,
            "allSongsData": snapshot["allSongsData"],
            "recentSongsData": snapshot["recentSongsData"],
            "albumData": snapshot["albumData"],
            "eventsData": snapshot["eventsData"],
            "songs": analyzer.songs,
            "recommendations": recommendations,
            "valueCharts": value_charts,
            "analysis": analyzer.analysis_summary,
        })
    cached = CachedAnalysis(user_id=user_id, region=region, analyzer=analyzer,
                            recommendations=recommendations, value_charts=value_charts)
    cache_put(cached)
    persist_progress(user_id, analyzer)
    # the judgement pages of the plays just read, fetched behind the reply so the results are not held for them
    asyncio.get_running_loop().run_in_executor(None, collect_judgements, user_id, analyzer, analyzer.recent_songs, region)
    return cached
