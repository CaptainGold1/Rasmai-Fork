from typing import Any, Callable, Dict, List, Optional, Tuple
import logging

from rasmai.bot.state.cache import CachedAnalysis

logger = logging.getLogger(__name__)


async def _analyze(cached: CachedAnalysis):
    from rasmai.bot.builders.results import build_analyze
    return await build_analyze(cached)


async def _profile(cached: CachedAnalysis):
    from rasmai.bot.builders.results import build_profile
    return await build_profile(cached)


async def _new(cached: CachedAnalysis):
    from rasmai.bot.builders.results import build_new
    return await build_new(cached, None)


async def _traits(cached: CachedAnalysis):
    from rasmai.bot.builders.traits import build_traits
    return await build_traits(cached)


async def _progress(cached: CachedAnalysis):
    from rasmai.bot.builders.history import build_progress
    return await build_progress(cached)


async def _best50(cached: CachedAnalysis):
    from rasmai.bot.builders.charts import build_b50
    return await build_b50(cached)


async def _recent(cached: CachedAnalysis):
    from rasmai.bot.builders.history import build_recent
    return await build_recent(cached)


# what the site may ask for, and the command that already draws it. The picture the website hands
# over is the one Discord gets, because it is made by the same builder rather than a second copy.
KINDS: Dict[str, Tuple[str, Callable[[CachedAnalysis], Any]]] = {
    "analyze": ("what to play", _analyze),
    "profile": ("play profile", _profile),
    "new": ("new charts", _new),
    "traits": ("traits", _traits),
    "progress": ("rating over time", _progress),
    "best50": ("best 50", _best50),
    "recent": ("recent plays", _recent),
}


async def render_export(cached: CachedAnalysis, kind: str) -> Optional[bytes]:
    """The PNG a command would attach, for the site to hand over as a download.

    The builders return Discord attachments, and the bytes are still in them: reading those back
    is what keeps this a view of the bot's own work rather than a second renderer to keep in step.

    :param cached: The player's analysis, held in memory.
    :type cached: CachedAnalysis
    :param kind: Which picture, one of :data:`KINDS`.
    :type kind: str
    :returns: The PNG, or None when there was nothing to draw.
    :rtype: Optional[bytes]
    """
    entry = KINDS.get(kind)
    if entry is None:
        return None
    built = await entry[1](cached)
    files: List[Any] = built[1] if isinstance(built, tuple) and len(built) > 1 else []
    for attachment in files:
        name = str(getattr(attachment, "filename", ""))
        if not name.endswith(".png") or "avatar" in name:
            continue
        data = getattr(attachment, "fp", None)
        if data is not None and hasattr(data, "getvalue"):
            return bytes(data.getvalue())
    return None
