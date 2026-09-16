from datetime import datetime
from typing import Dict, Optional, Any

from rasmai.bot.state.prefs import get_prefs
from rasmai.engine.insights import rating_forecast
from rasmai.storage.db import count_play_history, load_rating_history, since_last_look
from rasmai.util import _json_safe
from rasmai.web.dashboard.analysis import analysis_for_user
from rasmai.web.dashboard.picks import _englished, trait_practice
from rasmai.web.dashboard.refresh import refresh_jobs


def notice_payload() -> Dict[str, Any]:
    """The banner every visitor should see, whoever they are.

    Public and player-free. Until someone sets one from Discord there is no stored notice and the
    built-in one stands; once set, what they set is the whole truth, empty text included.

    :rtype: Dict[str, Any]
    """
    from rasmai.config import DEFAULT_NOTICE
    from rasmai.storage.db import site_notice_get
    stored = site_notice_get()
    notice = dict(DEFAULT_NOTICE) if stored is None else stored
    # whoever set it is nobody's business but ours
    return {key: value for key, value in notice.items() if key != "setBy"}


def servers_payload() -> Dict[str, Any]:
    """Whether maimai DX NET can be read right now, from the presence watch: maintenance on the schedule, or a site that does not answer.

    Public and player-free, so the site can show a band saying that what it shows is the last read.

    :rtype: Dict[str, Any]
    """
    from rasmai.bot.tasks.presence import maintenance_at
    window = maintenance_at()
    try:
        from rasmai.bot.core import watch
        reachable = bool(getattr(watch, "reachable", True))
        checked = getattr(watch, "checked_at", None)
    except Exception:
        reachable, checked = True, None
    return {
        "maintenance": bool(window.active),
        "reachable": reachable,
        "until": window.moment.isoformat() if window.active else None,
        "next": None if window.active else window.moment.isoformat(),
        "checkedAt": checked.isoformat() if checked else None,
    }


def servers_down_note() -> str:
    """Why maimai DX NET cannot be read right now, in plain words; "" when it can be.

    SEGA's Aime gateway is a separate site that stays up through maintenance, so someone can sign in
    there and still not be able to link an account. Saying which site is down is the whole point.

    :rtype: str
    """
    state = servers_payload()
    if state["maintenance"]:
        until = ""
        try:
            until = f" until {datetime.fromisoformat(str(state['until'])).strftime('%H:%M')} JST" if state.get("until") else ""
        except ValueError:
            until = ""
        return f"maimai DX NET is in maintenance{until}"
    if not state["reachable"]:
        return "maimai DX NET is not answering right now"
    return ""


def overview_payload(user: Dict[str, Any], account: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    from rasmai.storage.db import touch_account
    from rasmai.web.dashboard.admin import is_admin
    from rasmai.web.dashboard.beta import beta_state
    from rasmai.web.dashboard.public_profile import sharing_payload
    if account is not None:
        touch_account(user["id"])
    payload: Dict[str, Any] = {"user": user, "linked": account is not None, "admin": is_admin(user["id"])}
    if account is None:
        return payload
    history = load_rating_history(user["id"])
    profile = account.get("officialProfile") or {}
    snapshot = account.get("latestSnapshot") or {}
    payload.update({
        "region": account.get("region", "intl"),
        "profile": {
            "name": profile.get("name", ""), "rating": int(profile.get("rating") or 0), "dan": profile.get("dan", ""),
            "title": profile.get("title", ""), "totalPlayCount": int(profile.get("totalPlayCount") or 0),
            "updatedAt": profile.get("updatedAt") or snapshot.get("recordedAt") or account.get("updatedAt"),
        },
        "snapshot": {
            "recordedAt": snapshot.get("recordedAt"), "best50": snapshot.get("best50", 0),
            "newTotal": snapshot.get("newTotal", 0), "oldTotal": snapshot.get("oldTotal", 0),
            "charts": len(snapshot.get("charts") or []),
        },
        "history": [
            {"recordedAt": row.get("recorded_at"), "rating": row.get("rating"), "best50": row.get("best50"),
             "newTotal": row.get("new_total"), "oldTotal": row.get("old_total"), "charts": row.get("charts"), "plays": row.get("plays")}
            for row in history
        ],
        "settings": get_prefs(user["id"]),
        "refresh": refresh_jobs.status(user["id"]),
        "sessionExpired": account.get("sessionExpired") or "",
        "sharing": sharing_payload(user["id"], account),
        "beta": beta_state(user["id"]),
    })
    payload["forecast"] = rating_forecast(history)
    cached = analysis_for_user(user["id"], account)
    if cached is not None:
        summary = cached.analyzer.analysis_summary or {}
        payload["analysis"] = _json_safe({"profile": _englished(summary.get("profile")), "best50": summary.get("best50"),
                                          "reachableGain": summary.get("reachableGain"), "traitPractice": trait_practice(cached)})
    payload["playHistory"] = count_play_history(user["id"])
    from rasmai.engine.judgements import judgement_profile
    from rasmai.storage.db import load_judgements
    payload["judgements"] = judgement_profile(load_judgements(user["id"]))
    try:
        payload["sinceLast"] = since_last_look(user["id"], int(profile.get("rating") or 0), int(profile.get("totalPlayCount") or 0))
    except Exception:
        payload["sinceLast"] = None
    return payload
