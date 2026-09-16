from typing import Any, Dict

from rasmai.storage.db import get_user_settings, set_user_settings

# Features that are finished enough to use and not finished enough to be on by default. Each one
# is off until its owner turns it on, and turning it off puts everything back exactly as it was.
FEATURES: Dict[str, Dict[str, str]] = {
    "simai": {
        "label": "Chart reading",
        "note": "Traits measured from the charts themselves, note by note, rather than from the tags "
                "volunteers have written. Covers far more charts, and names things a tag cannot: long "
                "holds, fast slides, spins, and passages that keep both hands working.",
    },
}


def beta_state(user_id: str) -> Dict[str, Any]:
    """Which beta features this person has switched on, and what there is to switch on.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Dict[str, Any]
    """
    on = get_user_settings(user_id).get("beta") or {}
    return {
        "on": {key: bool(on.get(key)) for key in FEATURES},
        "features": [{"key": key, **spec} for key, spec in FEATURES.items()],
    }


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
