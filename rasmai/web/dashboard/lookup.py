from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Dict, List, Optional, Any
import logging

from rasmai.bot.state.cache import CachedAnalysis
from rasmai.config import WIKI_VIDEOS
from rasmai.engine.analysis import rank_for
from rasmai.scraping.mai_notes import english_label as mainotes_english
from rasmai.engine import patterns as patterns_engine
from rasmai.util import _json_safe

logger = logging.getLogger(__name__)


_video_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chart-video")


_TIER_LABEL = {"basic": "Basic", "advanced": "Advanced", "expert": "Expert", "master": "Master", "remaster": "Re:Master"}


def _lookup_index(cached: Optional[CachedAnalysis]) -> Any:
    from rasmai.bot.builders.charts import shared_index   # the bot's index and search tables; only wanted when it runs
    return cached.analyzer.chart_index if cached else shared_index()


def search_payload(cached: Optional[CachedAnalysis], query: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Songs matching typed text, with every chart each has and the player's score where there is one.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param query: What the player typed.
    :type query: str
    :param limit: Most entries to return.
    :type limit: int
    :rtype: List[Dict[str, Any]]
    """
    from rasmai.bot.builders.charts import (charts_for, chart_designer, search_titles, song_alias, song_for_chart,
                                            song_record, songs_by_loose_key)
    index = _lookup_index(cached)
    loose_map = songs_by_loose_key(cached) if cached else {}
    out: List[Dict[str, Any]] = []
    for title in search_titles(query, limit=limit * 2):
        refs = charts_for(title, index)
        if not refs:
            continue
        charts = []
        for ref in refs:
            song = song_for_chart(loose_map, ref)
            charts.append({
                "chart_type": ref.chart_type, "difficulty": ref.difficulty, "level": ref.level, "constant": ref.constant,
                "played": song is not None,
                "accuracy": float(song.accuracy or 0) if song is not None else None,
                "rank": (song.current_rank or rank_for(float(song.accuracy or 0))) if song is not None else "",
            })
        # who charted it, so a hit that matched on a charter's name rather than on the title says so
        record = song_record(title)
        charters = sorted({name for name in (chart_designer(record, ref) for ref in refs) if name}, key=str.casefold)
        out.append({"title": title, "alias": song_alias(title), "artist": refs[0].artist, "genre": refs[0].genre,
                    "cover": refs[0].cover, "charters": charters, "charts": charts})
        if len(out) >= limit:
            break
    return _json_safe(out)


def _song_page_now(title: str, reading: str, refs: List[Any]) -> Dict[str, Any]:
    """The wiki's page for a song (chart videos, unlock notes) within a short wait; a slow first fetch finishes in the background and is cached.

    :param title: The song title.
    :type title: str
    :param reading: The song's title as it is read.
    :type reading: str
    :param refs: Every chart the song has.
    :type refs: List[Any]
    :rtype: Dict[str, Any]
    """
    empty: Dict[str, Any] = {"page": "", "videos": {}, "unlock": []}
    if not WIKI_VIDEOS or not refs:
        return empty
    from rasmai.scraping import wiki
    future = _video_pool.submit(wiki.lookup_page, title, reading, [ref.chart_type for ref in refs])
    try:
        return future.result(timeout=6.0)
    except FutureTimeout:
        return empty
    except Exception as error:          # a wiki hiccup must never break the page
        logger.info("wiki lookup failed for %r: %s", title, error)
        return empty


def title_for_cover(index: Any, stem: str) -> str:
    """The song whose jacket file has this stem, from a map built once per chart index.

    :param index: The chart database to look charts up in.
    :type index: Any
    :rtype: str
    """
    from rasmai.web.links import cover_stem
    table = getattr(index, "_by_cover", None)
    if table is None:
        table = {}
        for ref in index.values():
            key = cover_stem(ref.cover)
            if key:
                table.setdefault(key, ref.title)
        try:
            index._by_cover = table
        except AttributeError:
            pass
    return table.get(stem, "")


def chart_payload(cached: Optional[CachedAnalysis], title: str, chart_type: str = "", difficulty: str = "",
                  cover: str = "") -> Optional[Dict[str, Any]]:
    """Everything /chart shows for one song: each chart with the player's score, the prediction, the rank ladder and the score history.

    A `cover` (jacket id, as the bot's short links carry) names the song instead of a title.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param title: The song title.
    :type title: str
    :param chart_type: ``"std"`` or ``"dx"``.
    :type chart_type: str
    :param difficulty: The difficulty tier, such as ``"master"``.
    :type difficulty: str
    :param cover: The jacket file name.
    :type cover: str
    :rtype: Optional[Dict[str, Any]]
    """
    from rasmai.bot.builders.charts import (
        _chart_rows, _default_page, _history_points, chart_designer, chart_ladder, charts_for, difficulty_page, page_index,
        prediction_for, resolve_title, song_alias, song_record, version_name, youtube_search_url,
    )
    index = _lookup_index(cached)
    if cover and not title:
        title = title_for_cover(index, cover)
        if not title:
            return None
    refs = charts_for(title, index)
    if not refs:
        resolved = resolve_title(title, index)
        refs = charts_for(resolved, index) if resolved else []
        title = resolved or title
    if not refs:
        return None
    record = song_record(title)
    rows = _chart_rows(cached, refs)
    selected: Optional[int] = None
    if chart_type and difficulty:
        selected = page_index(refs, chart_type, difficulty)
    if selected is None and difficulty:
        selected = difficulty_page(refs, rows, difficulty)
    if selected is None:
        selected = _default_page(rows)
    both_types = len({ref.chart_type for ref in refs}) > 1
    profile = cached.analyzer.play_profile if cached else None
    current_version = cached.analyzer.current_version if cached else 0
    from rasmai.scraping import mai_notes
    # the traits the player already scores away from their own curve on, so a chart can say which of its own they are
    trait_offsets = {t["label"]: float(t["offset"]) for t in ((profile.traits if profile else None) or [])}
    charts: List[Dict[str, Any]] = []
    for ref, row in zip(refs, rows):
        item: Dict[str, Any] = dict(row)
        item.update({
            "title": ref.title, "notes": ref.notes, "version": ref.version, "intl": ref.intl, "deleted": ref.deleted,
            "released": ref.released,
            "designer": chart_designer(record, ref), "is_new": bool(current_version) and ref.version == current_version,
            "usual": profile.expected_for(ref.constant, ref.difficulty) if profile and profile.sample_size else None,
            "prediction": None, "ladder": [], "history": [],
            "noteSplit": None, "patterns": [],
        })
        facts = mai_notes.cached_facts().get(ref.key)
        if facts:
            item["noteSplit"] = {name: int(facts.get(field) or 0) for field, name in
                                 (("t", "tap"), ("h", "hold"), ("s", "slide"), ("u", "touch"), ("b", "break"))}
        item["patterns"] = [{**tag, "offset": trait_offsets.get(tag["label"])}
                            for tag in patterns_engine.tags_for(ref, patterns_engine.reading_for(cached))]
        if cached is not None:
            prediction = prediction_for(cached, ref, row)
            if prediction:
                prediction["tier"] = _TIER_LABEL.get(ref.difficulty, ref.difficulty)
            item["prediction"] = prediction
            item["ladder"] = chart_ladder(cached, ref, row)
            item["history"] = [
                {"when": point["when"].isoformat(), "achievement": point["achievement"], "dx": point["dx"],
                 "fc": point["fc"], "fs": point["fs"], "source": point["source"],
                 "constant": point["constant"], "rating": point["rating"]}
                for point in _history_points(cached, ref)
            ]
        item["video"] = None            # filled in by /internal/me/video, which may wait on the wiki
        item["youtube"] = youtube_search_url(ref, both_types)
        charts.append(item)
    reading = str(record.get("alt_title", "") or "").strip()
    return _json_safe({
        "title": title, "alias": song_alias(title), "artist": refs[0].artist, "genre": refs[0].genre, "cover": refs[0].cover,
        "bpm": str(record.get("bpm", "") or "").strip(), "reading": reading if reading.casefold() != title.casefold() else "",
        "version": version_name(record), "selected": selected, "charts": charts,
    })


def patterns_payload(cached: Optional[CachedAnalysis], tag: str, level: str, difficulty: str) -> Dict[str, Any]:
    """The pattern catalogue, and the charts carrying one tag with the player's scores beside them.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param tag: The tag as typed or chosen; empty for the catalogue alone.
    :type tag: str
    :param level: A displayed level, or "".
    :type level: str
    :param difficulty: A difficulty tier, or "".
    :type difficulty: str
    :rtype: Dict[str, Any]
    """
    from rasmai.engine import patterns
    from rasmai.bot.builders.charts import pattern_rows
    index = _lookup_index(cached)
    reading = patterns.reading_for(cached)
    catalogue = patterns.catalogue(index, reading)
    resolved = patterns.resolve(tag, index, reading) if tag else None
    rows: List[Dict[str, Any]] = []
    if resolved:
        for row in pattern_rows(cached, resolved, level or None, difficulty or None):
            rows.append({**row, "tags": [mainotes_english(t) for t in row["tags"]]})
    return _json_safe({
        "tags": catalogue, "tag": resolved or "", "english": patterns.english_of(resolved) if resolved else "",
        "level": level or "", "difficulty": difficulty or "", "charts": rows,
    })


def video_payload(cached: Optional[CachedAnalysis], title: str) -> Dict[str, Any]:
    """What the wiki says about a song: a video per chart keyed "type|difficulty", the unlock notes, and the page; empty when it has none or is slow.

    :param cached: The player's analysis, held in memory.
    :type cached: Optional[CachedAnalysis]
    :param title: The song title.
    :type title: str
    :rtype: Dict[str, Any]
    """
    from rasmai.bot.builders.charts import charts_for, song_record
    from rasmai.scraping import wiki
    refs = charts_for(title, _lookup_index(cached))
    if not refs:
        return {"videos": {}, "unlock": [], "wiki": ""}
    record = song_record(title)
    found = _song_page_now(title, str(record.get("alt_title", "") or ""), refs)
    unlock = list(found.get("unlock") or [])
    areas: List[Dict[str, Any]] = []
    if cached is not None and getattr(cached.analyzer, "events_data", None) and unlock:
        from rasmai.bot.builders.areas import area_summary, area_title
        from rasmai.engine.areas import area_mentions
        summary = area_summary(cached)
        for line_index, line in enumerate(unlock):
            for area in area_mentions(line, summary)[:2]:
                areas.append({"line": line_index, "name": area["name"], "title": area_title(area), "distance": area["distance"],
                              "state": area["state"], "milestone": area.get("milestone")})
    return {
        "videos": {f"{chart_type}|{difficulty}": wiki.video_url(video) for (chart_type, difficulty), video in found["videos"].items()},
        "unlock": unlock,
        "unlockAreas": areas,
        "wiki": wiki.wiki_url(found["page"]) if found.get("page") else "",
    }
