from typing import Dict, Optional
import threading

# one full read per account at a time, whoever asked for it. The Discord commands and the site's
# read-now button used to guard themselves separately, so a read from each ran at once on the
# same account: twice the pages fetched from maimai for one set of scores.
_LOCK = threading.Lock()
_RUNNING: Dict[str, str] = {}

DISCORD = "a Discord command"
WEBSITE = "the website"


def claim(user_id: str, source: str) -> Optional[str]:
    """Take the read slot for an account, or find out who already holds it.

    :param user_id: The Discord user id.
    :type user_id: str
    :param source: Where this read was asked for, ``DISCORD`` or ``WEBSITE``.
    :type source: str
    :returns: ``None`` when the slot was taken, otherwise what is already reading.
    :rtype: Optional[str]
    """
    with _LOCK:
        held = _RUNNING.get(user_id)
        if held is not None:
            return held
        _RUNNING[user_id] = source
        return None


def release(user_id: str) -> None:
    """Give the read slot back, whether the read worked or not.

    :param user_id: The Discord user id.
    :type user_id: str
    """
    with _LOCK:
        _RUNNING.pop(user_id, None)


def running(user_id: str) -> Optional[str]:
    """What is reading this account right now, or ``None``.

    :param user_id: The Discord user id.
    :type user_id: str
    :rtype: Optional[str]
    """
    with _LOCK:
        return _RUNNING.get(user_id)
