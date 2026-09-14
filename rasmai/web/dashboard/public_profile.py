from typing import Any, Dict, List, Optional, Tuple
import logging
import secrets

from rasmai.bot.state.prefs import PUBLIC_SECTIONS, get_prefs, update_prefs
from rasmai.bot.state.snapshots import snapshot_charts
from rasmai.config import get_public_base_url
from rasmai.engine.analysis import rank_for
from rasmai.storage.db import account_by_share_slug, load_play_history, load_rating_history, set_share_slug
from rasmai.util import _json_safe

logger = logging.getLogger(__name__)

RECENT_ON_SHOW = 20
TRAITS_ON_SHOW = 6


def share_url(slug: str) -> str:
    """The address a public profile lives at.

    :param slug: The account's share slug.
    :type slug: str
    :rtype: str
    """
    return f"{get_public_base_url()}/p/{slug}" if slug else ""


def sharing_payload(user_id: str, account: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the Account tab shows about sharing: the link if there is one, and what it would carry.

    :param user_id: The Discord user id.
    :type user_id: str
    :param account: The linked account, as stored.
    :type account: Optional[Dict[str, Any]]
    :rtype: Dict[str, Any]
    """
    prefs = get_prefs(user_id)
    slug = str((account or {}).get("shareSlug") or "")
    return {
        "on": bool(prefs.get("public")) and bool(slug),
        "url": share_url(slug) if prefs.get("public") else "",
        "sections": {name: bool(prefs.get(f"public_{name}")) for name in PUBLIC_SECTIONS},
    }


def set_sharing(user_id: str, on: Optional[bool], sections: Optional[Dict[str, Any]] = None,
                rotate: bool = False, account: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Turn the public profile on or off, choose what it carries, or issue a fresh link.

    Turning it off leaves the slug in place but stops answering on it; asking for a new link
    replaces the slug, so anything already passed around stops working at once.

    :param user_id: The Discord user id.
    :type user_id: str
    :param on: Whether the profile should answer at all, or ``None`` to leave as is.
    :type on: Optional[bool]
    :param sections: Which parts to carry, by the names in ``PUBLIC_SECTIONS``.
    :type sections: Optional[Dict[str, Any]]
    :param rotate: Whether to replace the link with a new one.
    :type rotate: bool
    :param account: The linked account, as stored.
    :type account: Optional[Dict[str, Any]]
    :rtype: Dict[str, Any]
    """
    changes: Dict[str, Any] = {}
    if on is not None:
        changes["public"] = bool(on)
    for name in PUBLIC_SECTIONS:
        if sections is not None and name in sections:
            changes[f"public_{name}"] = bool(sections[name])
    if changes:
        update_prefs(user_id, **changes)
    slug = str((account or {}).get("shareSlug") or "")
    if rotate or (on and not slug):
        slug = set_share_slug(user_id, secrets.token_urlsafe(18)) or ""
    return sharing_payload(user_id, {**(account or {}), "shareSlug": slug})


def public_payload(slug: str) -> Optional[Dict[str, Any]]:
    """A profile as anyone holding the link may see it, or ``None`` when the link is not in use.

    Nothing here identifies the Discord account behind it, and every section beyond the name and
    rating has to have been opted into. A profile switched off answers as if it never existed.

    :param slug: The slug from the address.
    :type slug: str
    :rtype: Optional[Dict[str, Any]]
    """
    account = account_by_share_slug(slug)
    if account is None:
        return None
    user_id = str(account["userId"])
    prefs = get_prefs(user_id)
    if not prefs.get("public"):
        return None

    profile = account.get("officialProfile") or {}
    snapshot = account.get("latestSnapshot") or {}
    charts = snapshot_charts(snapshot)
    shows = {name: bool(prefs.get(f"public_{name}")) for name in PUBLIC_SECTIONS}
    payload: Dict[str, Any] = {
        "name": str(profile.get("name") or "a maimai player"),
        "title": str(profile.get("title") or ""),
        "dan": str(profile.get("dan") or ""),
        "region": str(account.get("region") or "intl"),
        "rating": int(profile.get("rating") or snapshot.get("rating") or 0),
        "plays": int(profile.get("totalPlayCount") or 0),
        "charts": len(charts),
        "updatedAt": str(profile.get("updatedAt") or snapshot.get("recordedAt") or account.get("updatedAt") or ""),
        "shows": shows,
    }

    covers = _covers() if (shows["best50"] or shows["recent"]) else {}
    if shows["best50"]:
        pool = sorted((c for c in charts if c.get("rating")), key=lambda c: -int(c.get("rating") or 0))
        payload["best50"] = {
            "new": _charts_on_show([c for c in pool if c.get("is_new")][:15], covers),
            "old": _charts_on_show([c for c in pool if not c.get("is_new")][:35], covers),
        }
    if shows["recent"]:
        recent = []
        for play in (load_play_history(user_id, RECENT_ON_SHOW) or []):
            parts = (str(play.get("key") or "").split("|") + ["", "", ""])[:3]
            recent.append({"title": parts[0], "type": parts[1] or "std", "difficulty": parts[2],
                           "achievement": round(float(play.get("achievement") or 0), 4),
                           "rank": rank_for(float(play.get("achievement") or 0)),
                           "day": str(play.get("played_at") or "")[:10],
                           "cover": _cover_for(covers, parts[0], parts[1], parts[2])})
        payload["recent"] = recent
    if shows["traits"]:
        payload["traits"], payload["traitAxes"] = _traits_on_show(user_id, account)
    if shows["areas"]:
        payload["areas"] = _areas_on_show(user_id)
    payload["history"] = [
        {"recordedAt": row.get("recorded_at"), "rating": row.get("rating")}
        for row in (load_rating_history(user_id) or [])[-120:]
    ]
    return _json_safe(payload)


def _covers() -> Dict[Any, str]:
    """Jacket file per chart, from the shared index. Empty when the database has not loaded yet.

    :rtype: Dict[Any, str]
    """
    try:
        from rasmai.bot.builders.charts.index import shared_index
        return {key: chart.cover for key, chart in shared_index().items() if chart.cover}
    except Exception:
        logger.info("no chart index for a public profile's jackets", exc_info=False)
        return {}


def _cover_for(covers: Dict[Any, str], title: str, chart_type: str, difficulty: str) -> str:
    return covers.get((str(title).casefold(), (chart_type or "std").lower(), (difficulty or "").lower()), "")


def _charts_on_show(rows: List[Dict[str, Any]], covers: Dict[Any, str]) -> List[Dict[str, Any]]:
    return [{
        "title": str(row.get("name") or ""), "difficulty": str(row.get("difficulty_type") or "").lower(),
        "type": str(row.get("chart_type") or "std"), "level": str(row.get("level") or ""),
        "constant": round(float(row.get("constant") or row.get("difficulty") or 0), 1),
        "accuracy": round(float(row.get("accuracy") or 0), 4), "rank": rank_for(float(row.get("accuracy") or 0)),
        "rating": int(row.get("rating") or 0), "fc": str(row.get("fc_status") or ""), "fs": str(row.get("fs_status") or ""),
        "cover": _cover_for(covers, row.get("name") or "", str(row.get("chart_type") or ""), str(row.get("difficulty_type") or "")),
    } for row in rows]


def _traits_on_show(user_id: str, account: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The traits worth naming, and the axes the wheel is drawn on.

    :returns: ``(named traits, wheel axes)``, both empty when there is not enough to say.
    :rtype: Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
    """
    def shape(trait: Dict[str, Any]) -> Dict[str, Any]:
        return {"label": english_label(str(trait["label"])), "offset": round(float(trait["offset"]), 2),
                "count": int(trait["count"]), "kind": str(trait["dimension"])}

    try:
        from rasmai.engine import insights
        from rasmai.scraping.mai_notes import english_label
        from rasmai.web.dashboard.analysis import analysis_for_user
        cached = analysis_for_user(user_id, account)
        axes = list(getattr(getattr(cached, "analyzer", None), "play_profile", None).trait_axes or []) if cached else []
        shown = insights.notable(axes) + insights.leaning(axes)
        shown.sort(key=lambda trait: float(trait["offset"]))
        picked = shown[:TRAITS_ON_SHOW // 2] + shown[-(TRAITS_ON_SHOW // 2):]
        named = [shape(t) for t in {id(t): t for t in picked}.values()]
        return named, [shape(a) for a in insights.radar_axes(axes)]
    except Exception:
        logger.info("could not build traits for a public profile", exc_info=False)
        return [], []


def _areas_on_show(user_id: str) -> List[Dict[str, Any]]:
    """Areas under way and finished, without the reward detail the dashboard shows."""
    try:
        from rasmai.scraping import wiki
        from rasmai.storage.db import load_area_progress
        # the table holds every reading over time, oldest first: the last one per area is where they are now
        latest: Dict[str, Dict[str, Any]] = {}
        for row in load_area_progress(user_id) or []:
            if str(row.get("kind") or "") == "area":
                latest[str(row.get("name") or "")] = row
        moving = [row for row in latest.values() if str(row.get("state") or "") != "not_started"]
        moving.sort(key=lambda row: -int(row.get("distance") or 0))
        out = []
        for row in moving[:24]:
            name = str(row.get("name") or "")
            known = wiki.area_lookup(name) or {}
            out.append({"name": name, "english": str(known.get("english") or ""),
                        "distance": int(row.get("distance") or 0), "state": str(row.get("state") or "")})
        return out
    except Exception:
        logger.info("could not build areas for a public profile", exc_info=False)
        return []
