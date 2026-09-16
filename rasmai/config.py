from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path
import logging
import os
import threading


load_dotenv()


logging.basicConfig(level=logging.INFO)


DEBUG_EXPORT_JSON = os.getenv("MAIMAI_DEBUG_EXPORT_JSON", "false").lower() == "true"


DEBUG_EXPORT_DIR = Path("debug/maimai-exports")


# The bot's internal API, for the Next.js site in web/ to call. Not for browsers: keep it on
# loopback or the container network, and give both processes the same RASMAI_INTERNAL_SECRET.
WEBSERVER_HOST = os.getenv("MAIMAI_WEBSERVER_HOST", "127.0.0.1")
INTERNAL_API_SECRET = os.getenv("RASMAI_INTERNAL_SECRET", "").strip()

# the only Discord account the developer page answers to; everyone else gets a 404 from it
ADMIN_USER_ID = os.getenv("MAIMAI_ADMIN_ID", "178277628522921984").strip()

# where /notice is registered. A guild command exists only in that one server, so the rest of
# Discord never sees it in the picker; the admin check is what actually stops anyone using it.
CONTROL_GUILD_ID = int(os.getenv("MAIMAI_CONTROL_GUILD_ID", "1326596020146143283") or 0)

# the band the site shows until one is set from Discord; taking that one down leaves the site bare
DEFAULT_NOTICE = {
    "text": "Rasmai is moving to rasmai.lol. Your account and scores move with it, so there is nothing to "
            "re-link. This address keeps working until the switch.",
    "tone": "notice",
    "link": "",
    "id": "move-rasmai-lol",
    "hideOnHost": "rasmai.lol",
}

# the linking walkthrough recordings: "walkthrough" in the container, web/public in a checkout
WALKTHROUGH_DIR = next((p for p in (Path("walkthrough"), Path("web/public/walkthrough")) if p.is_dir()), Path("walkthrough"))
# where a bot-run cloudflared tunnel should point: the public site, which is the Next.js server
TUNNEL_ORIGIN = os.getenv("MAIMAI_TUNNEL_ORIGIN", "http://127.0.0.1:3000").strip().rstrip("/")


WEBSERVER_PORT = int(os.getenv("MAIMAI_WEBSERVER_PORT", "8765"))


PUBLIC_URL = os.getenv("MAIMAI_PUBLIC_URL", "https://rasmai.lol").strip().rstrip("/")


TUNNEL_MODE = os.getenv("MAIMAI_TUNNEL", "").strip()   # "quick", or the name of a cloudflared tunnel


_public_base_url = PUBLIC_URL


_public_url_lock = threading.Lock()


DATABASE_PATH = Path(os.getenv("MAIMAI_DATABASE_PATH", "data/maimai.sqlite3"))


MAIMAI_BASE_URLS = {
    "jp": "https://maimaidx.jp",
    "intl": "https://maimaidx-eng.com",
    "cn": "https://maimai.wahlap.com",
}


def get_maimai_base_url(region: str) -> str:
    return MAIMAI_BASE_URLS.get(region, MAIMAI_BASE_URLS["intl"])


def get_public_base_url() -> str:
    with _public_url_lock:
        return _public_base_url or f"http://{WEBSERVER_HOST}:{WEBSERVER_PORT}"


def set_public_base_url(url: str) -> None:
    global _public_base_url
    with _public_url_lock:
        _public_base_url = url.strip().rstrip("/")


def public_url_is_shareable() -> bool:
    """True when the login script can be loaded from an https origin.

    :rtype: bool
    """
    return get_public_base_url().startswith("https://")


# ---- capacity. Scraping is thread-per-analysis on top of asyncio; these bound the process, not a server.
MAX_CONCURRENT_SCRAPES = int(os.getenv("MAIMAI_MAX_CONCURRENT", "24"))     # full score reads running at once
MAX_CONCURRENT_RENDERS = int(os.getenv("MAIMAI_MAX_RENDERS", "4"))          # Chromium pages open at once
SCRAPE_WORKERS = MAX_CONCURRENT_SCRAPES + 16     # thread pool behind every blocking call
REQUESTS_PER_SECOND = float(os.getenv("MAIMAI_REQUESTS_PER_SECOND", "25"))  # to maimai DX NET from this process, all users together
PROGRESS_EDITS_PER_SECOND = float(os.getenv("MAIMAI_PROGRESS_EDITS_PER_SECOND", "8"))   # loading-bar edits, all users together
ANALYSIS_CACHE_MAX = int(os.getenv("MAIMAI_ANALYSIS_CACHE_MAX", "500"))     # finished analyses kept in memory
SHARD_COUNT = int(os.getenv("DISCORD_SHARD_COUNT", "0") or 0)              # 0 lets Discord pick


# ---- the web dashboard signs people in with Discord; both come from the application's OAuth2 page
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()


# the link that adds the bot to a server; /invite in Discord and /invite on the site both hand it out
DISCORD_BOT_INVITE = os.getenv("DISCORD_BOT_INVITE", "").strip()


def site_label() -> str:
    """The public address without its scheme, for footers and captions.

    :rtype: str
    """
    return get_public_base_url().split("://", 1)[-1].rstrip("/")


PLAY_COUNT_TTL = timedelta(hours=12)
# a stored read is reused while a light check says nothing changed; after this long it is read in full regardless,
# so chart constants and the profile never drift for more than a week
SNAPSHOT_MAX_AGE = timedelta(hours=int(os.getenv("MAIMAI_SNAPSHOT_MAX_AGE_HOURS", "168")))
# a command run this long after the last check of maimai DX NET checks again before answering from memory
RECHECK_AFTER = timedelta(minutes=int(os.getenv("MAIMAI_RECHECK_MINUTES", "3")))


PLAY_COUNT_FETCH_LIMIT = int(os.getenv("MAIMAI_PLAY_COUNT_FETCH_LIMIT", "60"))
WIKI_VIDEOS = os.getenv("MAIMAI_WIKI_VIDEOS", "true").lower() == "true"     # /chart links the chart's video from SilentBlue RemyWiki


PLAY_COUNT_UNKNOWN = -1   # fetched, but the page had no count for that difficulty


# ---- how the bot names itself when it reads the wikis and chart databases. Left unset it carries
# this deployment's own address, so a copy of the bot identifies itself rather than whoever it was
# copied from; set it to say more, such as an address the site owners can write to.
USER_AGENT = os.getenv("USER_AGENT", "").strip() or f"rasmai/1.0 (+{PUBLIC_URL})"
# maimai DX NET serves its mobile pages to browsers and to nothing else, so those reads carry this
# instead. It is not a setting: a string that does not read as a browser gets the scraper turned away.
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


DEBUG_MODE = os.getenv("MAIMAI_DEBUG", "false").lower() == "true"


GUILD_ID = int(os.getenv("MAIMAI_GUILD_ID", "0") or 0)


PRESENCE_ENABLED = os.getenv("MAIMAI_PRESENCE", "true").lower() == "true"


PRESENCE_REGION = os.getenv("MAIMAI_PRESENCE_REGION", "intl").strip().lower()
