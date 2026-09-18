from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

from rasmai.bot.state.cache import CachedAnalysis
from rasmai.engine.losses import note_losses
from rasmai.bot.state.snapshots import compact_snapshot
from rasmai.engine import analysis
from rasmai.engine.analysis import rank_for
from rasmai.storage.db import judged_marks, judgement_for, load_play_history, load_rating_history
from rasmai.util import _json_safe
from rasmai.web.dashboard.analysis import _chart_key


def play_payload(cached: CachedAnalysis, idx: str) -> Optional[Dict[str, Any]]:
    """One play's judgement page with what each note type cost; None when nothing is stored and the site no longer lists it.

    A page read once is kept for good, so this answers from storage without touching maimai DX NET.

    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :param idx: The site's own id for the play.
    :type idx: str
    :rtype: Optional[Dict[str, Any]]
    """
    from rasmai.bot.builders.history import play_detail
    detail = judgement_for(cached.user_id, idx)
    if detail is None:
        # never read before, so it has to come from the site, and only the fifty plays still listed there have a page
        if not any(str(record.get("idx", "")) == idx for record in cached.analyzer.recent_songs or []):
            return None
        detail = dict(play_detail(cached, idx))
    detail["lost"] = note_losses(detail.get("notes") or {}, float(detail.get("achievement") or 0))
    return _json_safe(detail)


def charts_payload(cached: CachedAnalysis) -> List[Dict[str, Any]]:
    a = cached.analyzer
    in_new = a.best50.new_pool.in_pool if a.best50 else set()
    in_old = a.best50.old_pool.in_pool if a.best50 else set()
    rows = []
    for song in a.songs:
        if (song.difficulty_type or "").lower() == "utage":
            continue
        key = _chart_key(song)
        ref = a.chart_index.get(key)
        rows.append({
            "title": ref.title if ref else (song.name), "type": key[1], "difficulty": key[2], "level": song.level,
            "constant": round(float(song.difficulty or 0), 1), "accuracy": round(float(song.accuracy or 0), 4),
            "rank": rank_for(float(song.accuracy or 0)), "rating": int(song.rating or 0),
            "fc": song.fc_status or "", "fs": song.fs_status or "", "dx": int(song.dx_score or 0),
            "maxDx": (ref.notes * 3) if ref and ref.notes else 0, "new": bool(song.is_new),
            "plays": max(0, a.play_counts.get(key, 0)), "cover": ref.cover if ref else "",
            "genre": ref.genre if ref else "", "artist": ref.artist if ref else "",
            "inBest50": key in (in_new if song.is_new else in_old),
            "estimated": bool(getattr(song, "constant_estimated", False)),
        })
    return rows


def recent_payload(user_id: str, cached: Optional[CachedAnalysis], limit: int = 400) -> List[Dict[str, Any]]:
    """The stored play history, newest first, with titles, constants and best-50 context filled in.

    The bot records every play it sees on the recent-plays page, so this is the long list:
    it keeps growing past the fifty plays maimai DX NET shows, for as long as the account is linked.

    :param user_id: The Discord user id.
    :type user_id: str
    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param limit: Most entries to return.
    :type limit: int
    :rtype: List[Dict[str, Any]]
    """
    plays = load_play_history(user_id, limit)
    if not plays:
        return []
    a = cached.analyzer if cached else None
    by_key: Dict[Tuple[str, str, str], Any] = {}
    # the site's id for a play: from the fifty it still lists, and from every page already kept, so a play
    # that scrolled off months ago still opens the judgements that were stored for it
    idx_of: Dict[Tuple[Tuple[str, str, str], str], str] = {}
    for (chart_key, when), idx in judged_marks(user_id).items():
        parts = chart_key.split("|")
        if len(parts) == 3:
            idx_of[((parts[0], parts[1], parts[2]), when)] = idx
    if a is not None:
        for song in a.songs:
            by_key[_chart_key(song)] = song
        from rasmai.bot.builders.history import recent_key
        for record in a.recent_songs or []:
            when = record.get("playedAt", "")
            when = when.isoformat(timespec="seconds") if isinstance(when, datetime) else str(when)
            if record.get("idx"):
                idx_of[(recent_key(a, record), when)] = str(record["idx"])
    out: List[Dict[str, Any]] = []
    for position, play in enumerate(plays):
        parts = play["key"].split("|")
        key = (parts[0], parts[1] if len(parts) > 1 else "std", parts[2] if len(parts) > 2 else "")
        song = by_key.get(key)
        ref = a.chart_index.get(key) if a is not None else None
        achievement = float(play["achievement"])
        constant = float(song.difficulty or 0) if song else (ref.constant if ref else 0.0)
        is_new = bool(song.is_new) if song else bool(ref and a and a.current_version and ref.version == a.current_version)
        in_b50 = bool(a and a.best50) and key in a.best50.pool_for(is_new).in_pool
        played_at = str(play["played_at"])
        out.append({
            "position": position + 1, "key": key, "idx": idx_of.get((key, played_at), ""),
            "title": song.name if song else (ref.title if ref else key[0]),
            "difficulty": key[2], "chart_type": key[1], "level": str(song.level if song else (ref.level if ref else "")),
            "constant": round(constant, 1),
            "achievement": achievement, "rank": rank_for(achievement),
            "dx": play["dx_score"], "max_dx": play["max_dx"], "track": play["track"],
            "fc": play["fc"], "fs": play["fs"],
            "time": played_at[11:16], "day": played_at[:10],
            "chart_rating": analysis.calculate_rating(constant, achievement) if constant > 0 else 0,
            "pb": achievement > float(play["best_before"]) + 0.00005, "in_b50": in_b50,
            "cover": (song.cover_url if song else "") or (ref.cover if ref else ""),
        })
    return _json_safe(out)


def export_payload(cached: CachedAnalysis) -> Dict[str, Any]:
    a = cached.analyzer
    payload = compact_snapshot(a)
    payload["playCounts"] = {"|".join(k): v for k, v in a.play_counts.items() if v > 0}
    payload["recentPlays"] = list(a.recent_songs or [])
    payload["playHistory"] = load_play_history(cached.user_id)
    payload["ratingHistory"] = load_rating_history(cached.user_id)
    return _json_safe(payload)
