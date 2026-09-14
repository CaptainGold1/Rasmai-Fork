from datetime import datetime
from typing import Dict, Any
import logging
import threading

from rasmai.bot.state import reads
from rasmai.bot.state.cache import CachedAnalysis
from rasmai.bot.state.snapshots import collect_judgements, persist_progress
from rasmai.bot.tasks.chart_db import resolve_unknown
from rasmai.config import MAIMAI_BASE_URLS, MAX_CONCURRENT_SCRAPES
from rasmai.scraping.scraper import MaimaiRatingAnalyzer, SessionRejected
from rasmai.security import public_reason
from rasmai.storage.db import (
    load_judgements, load_play_counts, load_recorded_plays, mark_session_expired, save_play_counts,
)

logger = logging.getLogger(__name__)


class RefreshJobs:
    """One score read per user at a time, started from the dashboard and followed by polling."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max(2, MAX_CONCURRENT_SCRAPES // 4))

    def status(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(user_id)
            return dict(job) if job else {"running": False}

    def start(self, user_id: str, account: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(user_id)
            if job and job.get("running"):
                return dict(job)
            elsewhere = reads.claim(user_id, reads.WEBSITE)
            if elsewhere is not None:
                # a Discord command is already reading this account; a second read would only slow both
                return {"running": False, "stage": "failed", "done": 0, "total": 0, "detail": "",
                        "error": f"your scores are being read right now, started from {elsewhere}. "
                                 "Give it a moment and try again."}
            job = {"running": True, "stage": "queued", "done": 0, "total": 0, "detail": "", "error": "",
                   "startedAt": datetime.now().isoformat(timespec="seconds")}
            self._jobs[user_id] = job
        threading.Thread(target=self._run, args=(user_id, account, job), daemon=True, name=f"refresh-{user_id}").start()
        return dict(job)

    def _tell(self, job: Dict[str, Any]):
        def callback(key: str, done: int = 0, total: int = 0, detail: str = "") -> None:
            with self._lock:
                job.update({"stage": key, "done": done, "total": total, "detail": detail})
        return callback

    def _run(self, user_id: str, account: Dict[str, Any], job: Dict[str, Any]) -> None:
        tell = self._tell(job)
        try:
            self._read(user_id, account, job, tell)
        finally:
            # the slot goes back however this ended, or nothing could read this account again
            reads.release(user_id)

    def _read(self, user_id: str, account: Dict[str, Any], job: Dict[str, Any], tell: Any) -> None:
        try:
            with self._slots:
                region = account.get("region", "intl")
                if region not in MAIMAI_BASE_URLS:
                    region = "intl"
                analyzer = MaimaiRatingAnalyzer()
                snapshot = analyzer.fetch_official_maimai_snapshot(str(account["token"]), region, tell)
                analyzer.player = snapshot["player"]
                analyzer.songs = snapshot["songs"]
                analyzer.recent_songs = snapshot.get("recentSongsData", [])
                analyzer.play_counts = load_play_counts(user_id)
                analyzer.recorded_plays = load_recorded_plays(user_id)
                analyzer.judgements = load_judgements(user_id)
                tell("analysis", 0, 1)
                recommendations, value_charts = analyzer.generate_recommendations()
                if resolve_unknown(analyzer, tell):
                    recommendations, value_charts = analyzer.generate_recommendations()
                wanted = analyzer.play_count_targets()
                if wanted:
                    fetched = analyzer.fetch_official_play_counts(wanted, region, tell)
                    if fetched:
                        save_play_counts(user_id, fetched)
                        analyzer.play_counts.update(fetched)
                        recommendations, value_charts = analyzer.generate_recommendations()
                persist_progress(user_id, analyzer)
                from rasmai.bot.state.cache import cache_put
                cache_put(CachedAnalysis(user_id=user_id, region=region, analyzer=analyzer,
                                         recommendations=recommendations, value_charts=value_charts))
            with self._lock:
                job.update({"running": False, "stage": "done", "finishedAt": datetime.now().isoformat(timespec="seconds")})
            # the judgement pages of the plays just read, after the page has been told the read is done
            collect_judgements(user_id, analyzer, analyzer.recent_songs, region)
        except Exception as error:
            if isinstance(error, SessionRejected):
                mark_session_expired(user_id)
            logger.exception("Dashboard refresh failed")
            with self._lock:
                job.update({"running": False, "stage": "failed", "error": public_reason(error)})


refresh_jobs = RefreshJobs()
