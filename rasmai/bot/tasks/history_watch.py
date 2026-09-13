from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import asyncio
import logging

import discord

from rasmai.bot.tasks.presence import maintenance_at
from rasmai.bot.state.prefs import get_prefs
from rasmai.bot.state.snapshots import collect_judgements, play_rows, store_recent
from rasmai.bot.ui.formatting import stamp
from rasmai.bot.ui.login import dm_login_card
from rasmai.config import MAIMAI_BASE_URLS
from rasmai.scraping.scraper import MaimaiRatingAnalyzer, SessionRejected
from rasmai.security import public_reason
from rasmai.storage.db import (
    best_recorded_scores, mark_session_expired, notified_rating, quiet_read_done, quiet_read_status, quiet_reads_due,
    record_chart_scores, set_notified_rating,
)

logger = logging.getLogger(__name__)

TICK = 15 * 60                    # seconds between looks at the due list
READ_EVERY = timedelta(hours=20)  # one quiet read per opted-in account per day
PER_TICK = 4                      # accounts read per tick, so a big user base spreads over the day
PAUSE_BETWEEN = 20                # seconds between two quiet reads


class HistoryWatch:
    """Reads the recent-plays page once a day for people who asked, so no play falls off the list.

    maimai DX NET shows only the last fifty plays. A player who visits the cabinet often
    and runs a command rarely loses the plays in between; this read keeps the per-chart
    history, and the model's self-check that depends on it, complete. It is a light read:
    one sign-in and one page, no score tables."""

    def __init__(self, bot: discord.Client, watch: Any):
        self.bot = bot
        self.watch = watch                # the server watch: reachable or not
        self._task: Optional[asyncio.Task] = None

    def _read_one(self, account: Dict[str, Any]) -> Dict[str, Any]:
        """One quiet read: the profile and the recent plays. Returns what was new: plays added, bests beaten, the rating."""
        region = str(account.get("region", "intl"))
        if region not in MAIMAI_BASE_URLS:
            region = "intl"
        user_id = str(account["userId"])
        analyzer = MaimaiRatingAnalyzer()
        player, plays = analyzer.fetch_official_check(str(account["token"]), region, with_areas=False)
        rows = play_rows(analyzer, plays)
        known = best_recorded_scores(user_id)
        bests: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            before = known.get(row[0], 0.0)
            if row[2] > before + 0.00005 and row[2] > bests.get(row[0], {}).get("now", 0.0):
                bests[row[0]] = {"key": row[0], "before": before, "now": row[2], "difficulty": row[0].rsplit("|", 1)[-1]}
        added = record_chart_scores(user_id, rows)
        store_recent(user_id, plays)
        collect_judgements(user_id, analyzer, plays, region)
        return {"added": added, "bests": list(bests.values()), "rating": int(player.rating or 0)}

    async def _note(self, user_id: str, found: Dict[str, Any]) -> None:
        """DM what the read found, for people who asked; nothing when nothing moved."""
        if not get_prefs(user_id).get("notify"):
            return
        last_rating = notified_rating(user_id)
        rating = int(found.get("rating") or 0)
        bests = found.get("bests") or []
        moved = rating and last_rating and rating != last_rating
        if not bests and not moved:
            if rating and not last_rating:
                set_notified_rating(user_id, rating)
            return
        lines: List[str] = []
        if moved:
            lines.append(f"Rating **{last_rating:,} → {rating:,}** ({rating - last_rating:+,})")
        if bests:
            titles = _title_lookup()
            shown = sorted(bests, key=lambda b: -(b["now"] - b["before"]))[:8]
            for best in shown:
                name = best["key"].split("|", 1)[0]
                title = titles.get(name, name)
                tier = str(best["difficulty"]).replace("remaster", "Re:MASTER").upper()
                was = f"{best['before']:.4f}% → " if best["before"] > 0 else "first pass · "
                lines.append(f"**{title}** {tier} · {was}**{best['now']:.4f}%**")
            if len(bests) > len(shown):
                lines.append(f"-# and {len(bests) - len(shown)} more")
        embed = discord.Embed(title=f"{len(bests)} new best{'s' if len(bests) != 1 else ''} since the last read" if bests else "Your rating moved",
                              description="\n".join(lines), color=discord.Color.from_rgb(255, 61, 143))
        embed.set_footer(text="from the daily read · /settings notify:False turns these off")
        try:
            user = self.bot.get_user(int(user_id)) or await self.bot.fetch_user(int(user_id))
            await user.send(embed=embed)
        except (discord.HTTPException, ValueError) as error:
            logger.info("daily note to %s not delivered: %s", user_id, error)
            return
        if rating:
            set_notified_rating(user_id, rating)

    async def run_due(self) -> None:
        if maintenance_at().active or not getattr(self.watch, "reachable", True):
            return
        due: List[Dict[str, Any]] = quiet_reads_due(READ_EVERY)[:PER_TICK]
        for account in due:
            user_id = str(account["userId"])
            try:
                found = await asyncio.to_thread(self._read_one, account)
                quiet_read_done(user_id, found["added"], "")
                logger.info("history: quiet read for %s added %d play(s)", user_id, found["added"])
                await self._note(user_id, found)
            except SessionRejected as error:
                previous = quiet_read_status(user_id)
                quiet_read_done(user_id, 0, public_reason(error))
                mark_session_expired(user_id)
                logger.info("history: %s needs /login again (%s)", user_id, public_reason(error))
                # the first failure after a run of good reads gets a card; a link that stays dead is not nagged about daily
                if not (previous or {}).get("error"):
                    await dm_login_card(self.bot, user_id, str(account.get("region", "intl")),
                                        "Your daily history read could not sign in to maimai DX NET: the saved session has expired. "
                                        "Link again below and the reads carry on.")
            except Exception as error:
                quiet_read_done(user_id, 0, public_reason(error))
                logger.warning("history: quiet read for %s failed: %s", user_id, public_reason(error))
            await asyncio.sleep(PAUSE_BETWEEN)

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(120)          # let the start-up work settle first
        while not self.bot.is_closed():
            try:
                await self.run_due()
            except Exception:
                logger.exception("history watch tick failed")
            await asyncio.sleep(TICK)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())


def describe_quiet_read(row: Optional[Dict[str, Any]]) -> str:
    """One line for /settings: when the last quiet read ran and what it found.

    :param row: One row of the table.
    :type row: Optional[Dict[str, Any]]
    :rtype: str
    """
    if not row:
        return "no quiet read yet"
    try:
        when = stamp(datetime.fromisoformat(str(row["read_at"])), "R")
    except (KeyError, ValueError):
        when = "?"
    if row.get("error"):
        return f"last try {when} failed: {row['error']}"
    return f"last read {when}, {int(row.get('plays_added') or 0)} new play(s)"


_titles: Dict[str, str] = {}


def _title_lookup() -> Dict[str, str]:
    """Database titles by their casefolded name, to print a chart key's song the way the game spells it."""
    if not _titles:
        try:
            from rasmai.bot.builders.charts.index import shared_index
            for chart in shared_index().values():
                _titles.setdefault(str(chart.title).casefold(), str(chart.title))
        except Exception:
            logger.exception("title lookup failed")
    return _titles
