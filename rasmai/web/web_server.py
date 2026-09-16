from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Any
from urllib.parse import urlparse, parse_qs
import gzip
import hmac
import json
import re
import threading
import logging

from rasmai.config import (
    DEBUG_EXPORT_JSON,
    DEBUG_MODE,
    INTERNAL_API_SECRET,
    MAIMAI_BASE_URLS,
    WEBSERVER_HOST,
    WEBSERVER_PORT,
)
from rasmai.storage.db import (
    consume_login_code,
    get_database_connection,
    get_connected_account,
    login_code_expiry,
    login_code_issued_at,
    login_code_verified,
    mark_login_code_verified,
    peek_login_code,
    upsert_connected_account,
)
from rasmai.web import dashboard
from rasmai.web.links import build_login_link_payload
from rasmai.scraping.scraper import MaimaiRatingAnalyzer
from rasmai.security import decode_opaque_user_id, login_attempt_allowed, normalize_login_token, public_reason
from rasmai.util import _json_safe, export_debug_payload

logger = logging.getLogger(__name__)


class InternalApiServer:
    """The bot's side of the website: JSON only, for the Next.js server to call.

    The public site (pages, Discord sign-in, sessions, the Turnstile check, headers and
    rate limits) is the Next.js app in `web/`. It talks to this server over the local
    network with a shared secret and tells it who the signed-in person is."""

    def __init__(self, host: str = WEBSERVER_HOST, port: int = WEBSERVER_PORT):
        self.host = host
        self.port = port
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not INTERNAL_API_SECRET and self.host not in ("127.0.0.1", "localhost", "::1"):
            logger.warning("RASMAI_INTERNAL_SECRET is empty while the internal API listens on %s; "
                           "anything that can reach the port can read accounts", self.host)

        class Handler(BaseHTTPRequestHandler):
            timeout = 20

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                status = args[1] if len(args) > 1 else ""
                path = urlparse(self.path).path
                # the dashboard polls these every couple of seconds; at info they bury everything else
                said = logger.debug if path in ("/internal/me/refresh", "/internal/me/beta",
                                                "/health", "/api/health") else logger.info
                said(f"internal api: {self.command} {path} -> {status}")

            # ---- plumbing

            def _authorized(self) -> bool:
                if not INTERNAL_API_SECRET:
                    return True
                return hmac.compare_digest(self.headers.get("X-Rasmai-Internal", ""), INTERNAL_API_SECRET)

            def _user(self) -> Optional[Dict[str, Any]]:
                """The signed-in Discord user, as the web server authenticated them.

                :rtype: Optional[Dict[str, Any]]
                """
                raw = self.headers.get("X-Rasmai-User", "")
                if not raw:
                    return None
                try:
                    user = json.loads(raw)
                except json.JSONDecodeError:
                    return None
                if not isinstance(user, dict) or not re.fullmatch(r"\d{5,25}", str(user.get("id", ""))):
                    return None
                return {"id": str(user["id"]), "name": str(user.get("name", "")), "handle": str(user.get("handle", "")),
                        "avatar": str(user.get("avatar", ""))}

            def _client_key(self) -> str:
                """The visitor's address as the web server saw it, for per-client limits.

                :rtype: str
                """
                return self.headers.get("X-Rasmai-Client", "") or self.client_address[0]

            def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(_json_safe(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
                    body = gzip.compress(body, compresslevel=6)
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _parse_payload(self, limit: int = 65536) -> Dict[str, Any]:
                content_type = self.headers.get("Content-Type", "")
                length = int(self.headers.get("Content-Length", "0"))
                if length > limit:
                    raise ValueError("request body too large")
                raw_body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
                if "application/json" in content_type:
                    return json.loads(raw_body or "{}")
                parsed = parse_qs(raw_body)
                return {key: values[0] for key, values in parsed.items() if values}

            # ---- routes

            def do_GET(self) -> None:  # noqa: N802
                route = urlparse(self.path)
                query = parse_qs(route.query)
                if route.path in ("/health", "/api/health"):
                    # a bot whose database has gone is not healthy, however well it answers: the container's
                    # health check reads this, so a stale bind mount shows up in docker ps instead of in every command
                    try:
                        get_database_connection().close()
                    except Exception as error:
                        logger.error("the health check could not open the database: %s", error)
                        self._send_json(503, {"ok": False, "error": "database"})
                        return
                    self._send_json(200, {"ok": True, "time": datetime.now().isoformat()})
                    return
                if not self._authorized():
                    self._send_json(401, {"ok": False, "error": "unauthorized"})
                    return
                if route.path.startswith("/internal/jacket/"):
                    dashboard.jacket(self, route.path[len("/internal/jacket/"):])
                    return
                if route.path.startswith("/internal/area-image/"):
                    dashboard.area_image(self, route.path[len("/internal/area-image/"):])
                    return
                if route.path.startswith("/internal/me"):
                    user = self._user()
                    if user is None:
                        self._send_json(401, {"ok": False, "error": "signed_out"})
                        return
                    if dashboard.handle_get(self, route.path, query, user):
                        return
                    self._send_json(404, {"ok": False, "error": "not_found"})
                    return
                if route.path == "/internal/status":
                    self._status(query)
                    return
                if route.path.startswith("/internal/public/"):
                    # no sign-in: the slug is the whole credential, and the payload carries only
                    # what its owner opted into. A profile switched off answers as if it never existed.
                    slug = route.path[len("/internal/public/"):]
                    if not login_attempt_allowed(self._client_key()):
                        self._send_json(429, {"ok": False, "error": "rate_limited"})
                        return
                    try:
                        shared = dashboard.public_payload(slug)
                    except Exception:
                        # a shared link is opened by people with no way to report a fault: answer, log, move on
                        logger.exception("building a public profile failed")
                        self._send_json(502, {"ok": False, "error": "unavailable"})
                        return
                    if shared is None:
                        self._send_json(404, {"ok": False, "error": "not_found"})
                        return
                    self._send_json(200, shared)
                    return
                if route.path == "/internal/servers":
                    self._send_json(200, dashboard.servers_payload())
                    return
                if route.path == "/internal/notice":
                    self._send_json(200, dashboard.notice_payload())
                    return
                if route.path == "/internal/connect-info":
                    self._connect_info(query)
                    return
                self._send_json(404, {"ok": False, "error": "not_found"})

            def _status(self, query: Dict[str, Any]) -> None:
                opaque = (query.get("user") or [""])[0].strip()
                code = (query.get("code") or [""])[0].strip()
                user_id = decode_opaque_user_id(opaque) if opaque else None
                if not user_id:
                    self._send_json(200, {"connected": False})
                    return
                account = get_connected_account(user_id)
                connected = bool(account)
                if connected and code:
                    # linked *by this link*: the account was written after the code was issued
                    issued = login_code_issued_at(code)
                    try:
                        updated = datetime.fromisoformat(str(account.get("updatedAt", "")))
                    except ValueError:
                        updated = None
                    connected = bool(issued and updated and updated >= issued)
                profile = (account or {}).get("officialProfile") or {}
                self._send_json(200, {
                    "connected": connected,
                    "player": profile.get("name", "") if connected else "",
                    "region": (account or {}).get("region", "") if connected else "",
                })

            def _connect_info(self, query: Dict[str, Any]) -> None:
                code = (query.get("code") or [""])[0].strip()
                opaque = (query.get("user") or [""])[0].strip()
                user_id = decode_opaque_user_id(opaque) if opaque else None
                if not user_id:
                    self._send_json(400, {"ok": False, "kind": "invalid_user"})
                    return
                record = peek_login_code(code)
                if not record or record[0] != user_id:
                    self._send_json(400, {"ok": False, "kind": "expired"})
                    return
                region = record[1] if record[1] in MAIMAI_BASE_URLS else "intl"
                login_info = build_login_link_payload(opaque, code, region)
                try:
                    expires_at = login_code_expiry(datetime.fromisoformat(record[2]))
                except ValueError:
                    expires_at = login_code_expiry()
                self._send_json(200, {
                    "ok": True,
                    "loginLink": login_info["loginLink"],
                    "bookmarklet": login_info["bookmarklet"],
                    "expiresAt": expires_at.isoformat(),
                    "expiresDisplay": expires_at.strftime("%H:%M"),
                    "region": region,
                    "verified": login_code_verified(code),   # the web server passed the human check for this code
                })

            def do_POST(self) -> None:  # noqa: N802
                path = urlparse(self.path).path
                if not self._authorized():
                    self._send_json(401, {"ok": False, "error": "unauthorized"})
                    return
                try:
                    # an export of a big account is a few hundred KB; nothing else posted here comes near 64 KB
                    payload = self._parse_payload(limit=4 * 1024 * 1024 if path == "/internal/me/import" else 65536)
                except Exception as error:
                    self._send_json(400, {"ok": False, "error": f"invalid_request: {error}"})
                    return
                try:
                    if path.startswith("/internal/me"):
                        user = self._user()
                        if user is None:
                            self._send_json(401, {"ok": False, "error": "signed_out"})
                            return
                        if dashboard.handle_post(self, path, user, payload):
                            return
                        self._send_json(404, {"ok": False, "error": "not_found"})
                        return
                    if path == "/internal/verify":
                        self._verify(payload)
                        return
                    if path == "/internal/login":
                        self._login(payload)
                        return
                    self._send_json(404, {"ok": False, "error": "not_found"})
                except Exception as error:
                    logger.exception("internal api request failed")
                    self._send_json(502, {"ok": False, "kind": "unknown", "error": public_reason(error)})

            def _verify(self, payload: Dict[str, Any]) -> None:
                """The web server verified a Turnstile token for this code; remember it on the code.

                :param payload: The data to store or send.
                :type payload: Dict[str, Any]
                """
                opaque_user = str(payload.get("user", "")).strip()
                code = str(payload.get("code", "")).strip()
                user_id = decode_opaque_user_id(opaque_user) if opaque_user else None
                record = peek_login_code(code)
                if not user_id or not record or record[0] != user_id:
                    self._send_json(401, {"ok": False, "kind": "expired", "error": "invalid or expired login code"})
                    return
                mark_login_code_verified(code)
                self._send_json(200, {"ok": True, "verified": True})

            def _login(self, payload: Dict[str, Any]) -> None:
                """The bookmarklet's hand-off: a login code plus the session cookie it read on SEGA's gateway.

                :param payload: The data to store or send.
                :type payload: Dict[str, Any]
                """
                opaque_user = str(payload.get("user", "")).strip()
                code = str(payload.get("code", "")).strip()
                token = str(payload.get("token", "")).strip()
                require_verified = bool(payload.get("requireVerified"))

                def fail(status: int, kind: str, message: str) -> None:
                    self._send_json(status, {"ok": False, "kind": kind, "error": message})

                if not login_attempt_allowed(self._client_key()):
                    fail(429, "rate_limited", "too many sign-in attempts")
                    return
                if not opaque_user or not code or not token:
                    fail(400, "no_login", "missing required form fields")
                    return
                user_id = decode_opaque_user_id(opaque_user)
                if not user_id:
                    fail(401, "invalid_user", "invalid user identifier")
                    return
                if not re.fullmatch(r"[A-Za-z0-9]{64}", token):
                    fail(400, "no_login", "session token has an unexpected format")
                    return
                record = peek_login_code(code)
                if not record or record[0] != user_id:
                    fail(401, "expired", "invalid or expired login code")
                    return
                if require_verified and not login_code_verified(code):
                    fail(403, "verify", "complete the check on the connect page first")
                    return
                # the session can only be proved against the score site, and the Aime gateway being up says
                # nothing about that one. Refusing here leaves the login code unspent, so the same link works later.
                down = dashboard.servers_down_note()
                if down:
                    fail(503, "maintenance", down)
                    return
                region = record[1] if record[1] in MAIMAI_BASE_URLS else "intl"
                final_token = normalize_login_token(token)
                try:
                    official_profile = MaimaiRatingAnalyzer(debug=DEBUG_MODE).fetch_official_player_profile(final_token, region)
                except Exception as error:
                    reason = public_reason(error)
                    # a 5xx from the score site is the site, not the session: name it as such and keep the link alive
                    server_side = bool(re.search(r"HTTP 5\d\d", str(error)))
                    if server_side:
                        logger.info("maimai DX NET could not confirm a session right now: %s", reason)
                        fail(503, "maintenance", "maimai DX NET answered with an error; it is probably down")
                    else:
                        logger.exception("Failed to validate connected token")
                        fail(502, "upstream", reason)
                    return
                # the session works: spend the code now, so nothing above can burn the link on its way to failing
                if not consume_login_code(code):
                    fail(401, "expired", "invalid or expired login code")
                    return
                upsert_connected_account(user_id, region, final_token, official_profile=_json_safe(official_profile))
                # linking only proves the session works; the scores still have to be read. Start that
                # here so the dashboard and the first command find them ready instead of scraping on demand.
                try:
                    account = get_connected_account(user_id)
                    if account is not None:
                        dashboard.refresh_jobs.start(user_id, account)
                except Exception:
                    logger.exception("Could not start the first score read after linking")
                if DEBUG_EXPORT_JSON:
                    export_debug_payload({
                        "connectedAt": datetime.now().isoformat(), "source": "api/login",
                        "userId": user_id, "region": region, "officialProfile": official_profile,
                    })
                self._send_json(200, {
                    "ok": True, "connected": True, "region": region,
                    "player": {"name": getattr(official_profile, "name", ""), "rating": getattr(official_profile, "rating", "")},
                })

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Internal API for the website listening on http://{self.host}:{self.port}")

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
