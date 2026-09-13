from bs4 import BeautifulSoup
from typing import List, Dict, Tuple, Any
import re
import time
import urllib.parse
import logging

from rasmai.config import PLAY_COUNT_FETCH_LIMIT, PLAY_COUNT_UNKNOWN, get_maimai_base_url

logger = logging.getLogger(__name__)


class PlaylogPages:
    """Reading the recent plays, the playlog detail pages and the play counts."""

    def enrich_recent_play_judgements(self, recent: List[Dict[str, Any]], region: str = "intl") -> None:
        """Attach compact judgement data to imported recent plays when available."""
        for record in recent:
            idx = str(record.get("idx") or "")
            if not idx:
                continue
            try:
                detail = self.fetch_playlog_detail(idx, region)
            except Exception as error:
                logger.info("Playlog detail unavailable for %s: %s", idx, error)
                continue
            record["judgement"] = {
                "fast": int(detail.get("fast") or 0),
                "late": int(detail.get("late") or 0),
                "notes": detail.get("notes") or {},
            }

    def play_count_targets(self, limit: int = PLAY_COUNT_FETCH_LIMIT, recommendations=None, plan=None) -> List[Tuple[str, str, str]]:
        """Charts worth a detail-page fetch, in poster order, minus known ones.

        Defaults to the recommendations and plan of the last analysis; pass another
        challenge level's picks to cover what that view shows.

        :param limit: Most entries to return.
        :type limit: int
        :param recommendations: The charts worth playing, best first.
        :param plan: The route to a rating target.
        :rtype: List[Tuple[str, str, str]]
        """
        recommendations = self.recommendations if recommendations is None else recommendations
        plan = self.plan if plan is None else plan
        wanted: List[Tuple[str, str, str]] = []
        ordered_keys: List[Tuple[str, str, str]] = []
        for rec in recommendations[:60]:
            ordered_keys.append((rec.song.casefold(), rec.chart_type, rec.difficulty_type))
        if plan:
            for step in plan.steps:
                ordered_keys.append(step.option.key)
        by_key = {
            (song.name.casefold(), (song.chart_type or "std").lower(), (song.difficulty_type or "").lower()): song
            for song in self.songs
        }
        seen_idx: set = set()
        for key in ordered_keys:
            if key in self.play_counts:
                continue
            song = by_key.get(key)
            if not song or not song.official_idx or song.official_idx in seen_idx:
                continue
            seen_idx.add(song.official_idx)
            wanted.append((song.official_idx, song.name, (song.chart_type or "std").lower()))
            if len(wanted) >= limit:
                break
        return wanted

    def _parse_official_music_detail(self, html: str) -> Dict[str, int]:
        """Play count per difficulty from a song's detail page.

        :param html: The page source to read.
        :type html: str
        :rtype: Dict[str, int]
        """
        soup = BeautifulSoup(html, "html.parser")
        pattern = re.compile(r"(?:PLAY\s*COUNT|プレイ回数|游玩次数|遊玩次數)\s*[:：]?\s*([\d,]+)", re.I)
        counts: Dict[str, int] = {}
        for image in soup.select("img[src*='diff_']"):
            src = image.get("src", "")
            if "utage" in src:
                difficulty = "utage"
            elif "remaster" in src:
                difficulty = "remaster"
            elif "master" in src:
                difficulty = "master"
            elif "expert" in src:
                difficulty = "expert"
            elif "advanced" in src:
                difficulty = "advanced"
            elif "basic" in src:
                difficulty = "basic"
            else:
                continue
            container = image
            found = None
            for _ in range(7):
                container = container.parent
                if container is None:
                    break
                if len(container.select("img[src*='diff_']")) > 1:
                    break
                match = pattern.search(container.get_text(" ", strip=True))
                if match:
                    found = int(match.group(1).replace(",", ""))
                    break
            if found is not None and difficulty not in counts:
                counts[difficulty] = found
        return counts

    def fetch_playlog_detail(self, idx: str, region: str = "intl") -> Dict[str, Any]:
        """Judgement breakdown for one play from the recent-plays list.

        :param idx: The site's own id for the row.
        :type idx: str
        :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
        :type region: str
        :rtype: Dict[str, Any]
        """
        session = getattr(self, "_official_session", None)
        if session is None:
            raise ValueError("Not signed in")
        base_url = get_maimai_base_url(region)
        html = self._fetch_official_html(
            session, f"{base_url}/maimai-mobile/record/playlogDetail/?idx={urllib.parse.quote(idx, safe='')}",
            f"{base_url}/maimai-mobile/record/",
        )
        return self._parse_playlog_detail(html)

    def _parse_playlog_detail(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")

        def number(text: str) -> int:
            digits = re.sub(r"[^\d]", "", text or "")
            return int(digits) if digits else 0

        def pair(text: str) -> Tuple[int, int]:
            match = re.search(r"([\d,]+)\s*/\s*([\d,]+)", text or "")
            return (number(match.group(1)), number(match.group(2))) if match else (0, 0)

        detail: Dict[str, Any] = {"fast": 0, "late": 0, "notes": {}}
        fl = [n.get_text(" ", strip=True) for n in soup.select(".playlog_fl_block .p_t_5")]
        if len(fl) >= 2:
            detail["fast"], detail["late"] = number(fl[0]), number(fl[1])
        scores = [d.get_text(" ", strip=True) for d in soup.select(".playlog_score_block > div")]
        detail["dx_score"], detail["max_dx_score"] = pair(scores[0]) if scores else (0, 0)
        detail["combo"], detail["max_combo"] = pair(scores[1]) if len(scores) > 1 else (0, 0)
        detail["sync"], detail["max_sync"] = pair(scores[2]) if len(scores) > 2 else (0, 0)
        rating = soup.select_one(".playlog_rating_detail_block .rating_block")
        detail["rating"] = number(rating.get_text(" ", strip=True)) if rating else 0
        change = soup.select_one(".playlog_rating_detail_block span")
        change_match = re.search(r"([+-]\d+)", change.get_text(" ", strip=True)) if change else None
        detail["rating_change"] = int(change_match.group(1)) if change_match else 0
        achievement = soup.select_one(".playlog_achievement_txt")
        ach_match = re.search(r"(\d+\.?\d*)%", achievement.get_text("", strip=True)) if achievement else None
        detail["achievement"] = float(ach_match.group(1)) if ach_match else 0.0
        for row in soup.select(".playlog_notes_detail tr"):
            icon = row.select_one("img")
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
            if not icon or len(cells) < 5:
                continue
            kind = icon.get("src", "").split("/")[-1].split(".")[0].lower()
            if kind not in ("tap", "hold", "slide", "touch", "break"):
                continue
            critical, perfect, great, good, miss = cells[-5:]
            detail["notes"][kind] = {
                "critical": number(critical), "perfect": number(perfect), "great": number(great),
                "good": number(good), "miss": number(miss),
            }
        subtitles = [s.get_text(" ", strip=True) for s in soup.select(".sub_title span")]
        detail["track"] = subtitles[0] if subtitles else ""
        detail["played_at"] = subtitles[1] if len(subtitles) > 1 else ""
        return detail

    def fetch_official_play_counts(
        self, targets: List[Tuple[str, str, str]], region: str = "intl", on_progress=None
    ) -> Dict[Tuple[str, str, str], int]:
        """Scrape play counts for (idx, name, chart_type) songs with the current session.

        :param targets: The charts to fetch counts for.
        :type targets: List[Tuple[str, str, str]]
        :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
        :type region: str
        :param on_progress: Called as each stage finishes.
        :rtype: Dict[Tuple[str, str, str], int]
        """
        session = getattr(self, "_official_session", None)
        if session is None or not targets:
            return {}
        base_url = get_maimai_base_url(region)
        referer = f"{base_url}/maimai-mobile/record/"

        scored: Dict[Tuple[str, str], set] = {}
        for song in self.songs:
            scored.setdefault(((song.name or "").casefold(), (song.chart_type or "std").lower()), set()).add(
                (song.difficulty_type or "").lower()
            )

        results: Dict[Tuple[str, str, str], int] = {}
        misses = 0
        fetched_pages = 0
        consecutive_failures = 0
        tell = on_progress or (lambda *args, **kwargs: None)
        for number, (idx, name, chart_type) in enumerate(targets, 1):
            tell("plays", number - 1, len(targets))
            try:
                try:
                    html = self._fetch_official_html(
                        session, f"{base_url}/maimai-mobile/record/musicDetail/?idx={urllib.parse.quote(idx, safe='')}", referer
                    )
                except ValueError as first:
                    if "HTTP 302" not in str(first):
                        raise
                    # The site answers 302 when asked too quickly; back off and try once more.
                    time.sleep(1.5)
                    html = self._fetch_official_html(
                        session, f"{base_url}/maimai-mobile/record/musicDetail/?idx={urllib.parse.quote(idx, safe='')}", referer
                    )
            except Exception as error:
                consecutive_failures += 1
                # A single bad idx (hidden rating-target songs use a different one)
                # is remembered as a miss; a run of them means the session is gone.
                for difficulty in scored.get((name.casefold(), chart_type), ()):
                    results.setdefault((name.casefold(), chart_type, difficulty), PLAY_COUNT_UNKNOWN)
                if consecutive_failures >= 3:
                    logger.warning(f"Play count fetch stopped at {name}: {error}")
                    break
                logger.info(f"Play count unavailable for {name}: {error}")
                time.sleep(0.2)
                continue
            consecutive_failures = 0
            fetched_pages += 1
            per_difficulty = self._parse_official_music_detail(html)
            for difficulty, plays in per_difficulty.items():
                results[(name.casefold(), chart_type, difficulty)] = plays
            for difficulty in scored.get((name.casefold(), chart_type), ()):
                key = (name.casefold(), chart_type, difficulty)
                if key not in results:
                    results[key] = PLAY_COUNT_UNKNOWN
                    misses += 1
            time.sleep(0.4)
        if fetched_pages and all(v == PLAY_COUNT_UNKNOWN for v in results.values()):
            logger.warning("Fetched detail pages but found no play counts - the page layout may have changed")
        elif misses:
            logger.info(f"Play counts: {misses} chart(s) had no count on their detail page")
        return results

    def fetch_official_recent_plays(self, token: str, region: str = "intl") -> List[Dict[str, Any]]:
        """Sign in and read the recent-plays page only: one page, for the daily history read.

        :param token: The saved maimai session.
        :type token: str
        :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
        :type region: str
        :rtype: List[Dict[str, Any]]
        """
        self.region = region
        self.fetch_official_player_profile(token, region)
        session = getattr(self, "_official_session", None)
        if session is None:
            raise ValueError("Official session was not preserved after login")
        base_url = get_maimai_base_url(region)
        recent_html = self._fetch_official_html(session, f"{base_url}/maimai-mobile/record/", f"{base_url}/maimai-mobile/")
        recent = self._parse_official_recent_songs(recent_html, region)
        self.enrich_recent_play_judgements(recent, region)
        return recent
