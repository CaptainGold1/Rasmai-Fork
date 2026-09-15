from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
import logging
import re

logger = logging.getLogger(__name__)


JACKET_DIR = Path("otoge_cache/jackets")


def _send_file(handler: BaseHTTPRequestHandler, path: Path, content_type: str) -> None:
    body = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "public, max-age=2592000, immutable")
    handler.end_headers()
    handler.wfile.write(body)


def jacket(handler: BaseHTTPRequestHandler, name: str) -> bool:
    """A song jacket from the chart-database cache, or 404.

    :param handler: The request being answered.
    :type handler: BaseHTTPRequestHandler
    :param name: The name to look up.
    :type name: str
    :rtype: bool
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", name):
        handler._send_json(404, {"ok": False, "error": "not_found"})
        return False
    stem = Path(name).stem
    for candidate in (JACKET_DIR / f"{stem}{ext}" for ext in (".webp", ".png", ".jpg")):
        if candidate.is_file():
            suffix = candidate.suffix.lower()
            _send_file(handler, candidate, {".webp": "image/webp", ".png": "image/png"}.get(suffix, "image/jpeg"))
            return True
    handler.send_response(404)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    return True


def image_export(handler: Any, cached: Any, kind: str) -> None:
    """Hand over the picture a command would attach, as a download.

    Rendering is a browser screenshot on the bot's event loop, so the request waits on that loop
    rather than starting a second one; a render that will not finish is a 503, never a hung page.

    :param handler: The request being answered.
    :type handler: Any
    :param cached: The player's analysis, held in memory.
    :type cached: Any
    :param kind: Which picture, one of the keys in the export table.
    :type kind: str
    """
    import asyncio
    from rasmai.bot.builders.exports import KINDS, render_export

    if kind not in KINDS:
        handler._send_json(404, {"ok": False, "error": "unknown_image"})
        return
    try:
        from rasmai.bot.core import bot
        loop = getattr(bot, "loop", None)
        if loop is None or not loop.is_running():
            handler._send_json(503, {"ok": False, "error": "not_running"})
            return
        png = asyncio.run_coroutine_threadsafe(render_export(cached, kind), loop).result(timeout=60)
    except Exception:
        logger.exception("could not draw the %s image for the website", kind)
        handler._send_json(502, {"ok": False, "error": "render_failed"})
        return
    if not png:
        handler._send_json(404, {"ok": False, "error": "nothing_to_draw"})
        return
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Content-Length", str(len(png)))
    handler.send_header("Content-Disposition", f'attachment; filename="rasmai-{kind}.png"')
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(png)
