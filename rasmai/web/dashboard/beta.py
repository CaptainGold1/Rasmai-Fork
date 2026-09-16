from typing import Any, Dict

from rasmai.storage.db import get_user_settings, set_user_settings

# Features that are finished enough to use and not finished enough to be on by default. Each one
# is off until its owner turns it on, and turning it off puts everything back exactly as it was.
FEATURES: Dict[str, Dict[str, str]] = {
    "simai": {
        "label": "Simai Chart Reading",
        "note": "Traits measured from the chart Simai sheet music data, note by note, rather than from the tags. "
    },
}


def _simai_status() -> Dict[str, Any]:
    """Whether chart reading can say anything yet, how far along it is, and how long is left.

    The charts are read a batch at a time over the first hour or so a bot is up, and nothing can be
    measured until enough of them are in to know what a demanding chart looks like. Without this a
    tester switches the feature on, sees their traits sit exactly as they were, and reasonably
    concludes it is broken.
    """
    try:
        from rasmai.scraping import simai
        rows, levels = simai.cached()
        read = sum(1 for row in rows.values() if row)
        dropped = len(rows) - read
        waiting = len(simai._pending(rows))
        done = read + dropped
        total = done + waiting
        rate = simai.pace()
        return {
            "ready": bool(levels),
            "done": done, "total": total, "read": read, "waiting": waiting,
            "percent": round(done / total * 100, 1) if total else 0.0,
            "eta": int(waiting / rate) if rate and waiting else 0,
            "status": f"{read:,} charts read" if not waiting else f"{read:,} of {total:,} charts read",
        }
    except Exception:
        return {"ready": False, "status": ""}


READINESS = {"simai": _simai_status}


def beta_state(user_id: str) -> Dict[str, Any]:
    """Which beta features this person has switched on, what there is to switch on, and whether it is ready.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Dict[str, Any]
    """
    on = get_user_settings(user_id).get("beta") or {}
    features = []
    for key, spec in FEATURES.items():
        ready = READINESS[key]() if key in READINESS else {"ready": True, "status": ""}
        features.append({"key": key, **spec, **ready})
    return {"on": {key: bool(on.get(key)) for key in FEATURES}, "features": features}


def set_beta(user_id: str, wanted: Dict[str, Any]) -> Dict[str, Any]:
    """Turn beta features on or off; anything not named is left alone.

    :param user_id: The Discord user id.
    :type user_id: str
    :param wanted: The features to change, as ``{"simai": true}``.
    :type wanted: Dict[str, Any]
    :rtype: Dict[str, Any]
    """
    settings = get_user_settings(user_id)
    on = dict(settings.get("beta") or {})
    for key, value in (wanted or {}).items():
        if key in FEATURES:
            on[key] = bool(value)
    settings["beta"] = on
    set_user_settings(user_id, settings)
    return beta_state(user_id)


def wants(user_id: str, feature: str) -> bool:
    """Whether this person has a beta feature switched on. Never raises: a fault means off.

    :param user_id: The Discord user id.
    :type user_id: str
    :param feature: The feature's key.
    :type feature: str
    :rtype: bool
    """
    try:
        return bool((get_user_settings(user_id).get("beta") or {}).get(feature))
    except Exception:
        return False
