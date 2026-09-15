from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
import logging

from rasmai.engine.analysis import ChartIndex, PlayProfile, ScoredCandidate
from rasmai.engine import analysis
from rasmai.engine import insights
from rasmai.config import get_maimai_base_url
from rasmai.storage.models import PlayerInfo, Recommendation, SongInfo
from rasmai.scraping.otoge import CachedOtogeDB
from rasmai.scraping.scraper.session import download_image_base64
from rasmai.scraping.scraper.areas import AreaPages
from rasmai.scraping.scraper.profile import ProfilePages
from rasmai.scraping.scraper.pages import ScorePages
from rasmai.scraping.scraper.plays import PlaylogPages

logger = logging.getLogger(__name__)


class MaimaiRatingAnalyzer(ScorePages, AreaPages, PlaylogPages, ProfilePages):
    def __init__(self, debug: bool = False):
        self.player = PlayerInfo()
        self.songs: List[SongInfo] = []
        self.recommendations: List[Recommendation] = []
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        self.debug = debug
        # the weekly refresh runs from the bot's own upkeep, never inside the request that happens to come first
        self.otoge_db = CachedOtogeDB(debug=debug)
        self.jacket_path = str(self.otoge_db.jacket_dir) + "/"
        self._chart_index: Optional[ChartIndex] = None
        self.recent_songs: List[Dict[str, Any]] = []
        self.play_profile: Optional[PlayProfile] = None
        self.best50 = None
        self.current_version: int = 0
        self.analysis_summary: Dict[str, Any] = {}
        self.plan: Optional[analysis.Plan] = None
        self.play_counts: Dict[Tuple[str, str, str], int] = {}
        self.recorded_plays: List[Dict[str, Any]] = []     # stored plays with the best held before each, for calibration
        self.judgements: List[Dict[str, Any]] = []        # stored judgement pages, for the note-type traits
        self.events_data: Dict[str, Any] = {"areaEvents": [], "eventAreaEvents": []}   # the map pages, as last read
        self.events_read_at: Optional[datetime] = None
        self.plan_stretch: bool = False
        self.region: str = "intl"
        self.challenge: str = "balanced"

    @property
    def chart_index(self) -> ChartIndex:
        if self._chart_index is None:
            self._chart_index = analysis.build_chart_index(self.otoge_db.songs_data, region=getattr(self, "region", None))
        return self._chart_index

    def fetch_official_maimai_snapshot(self, token: str, region: str = "intl", on_progress=None) -> Dict[str, Any]:
        """Everything the analysis needs from maimai DX NET, reporting each stage to `on_progress`.

        :param token: The saved maimai session.
        :type token: str
        :param region: ``"intl"``, ``"jp"`` or ``"cn"``.
        :type region: str
        :param on_progress: Called as each stage finishes.
        :rtype: Dict[str, Any]
        """
        tell = on_progress or (lambda *args, **kwargs: None)
        self.region = region
        self._chart_index = None
        tell("login", 0, 1)
        player = self.fetch_official_player_profile(token, region)
        tell("login", 1, 1, detail=f"Signed in as {player.name}")
        session = getattr(self, "_official_session", None)
        if session is None:
            raise ValueError("Official session was not preserved after login")

        base_url = get_maimai_base_url(region)
        referer = f"{base_url}/maimai-mobile/"
        player_data_html = self._fetch_official_html(session, f"{base_url}/maimai-mobile/playerData/", referer)
        player, _ = self._parse_official_player_info(player_data_html, region)
        player.region = region
        if getattr(self, "_official_cookie_header", ""):
            player.avatar_base64 = download_image_base64(player.icon_url, self._official_cookie_header)

        all_songs_data: Dict[int, List[SongInfo]] = {}
        difficulties = [0, 1, 2, 3, 4, 10]
        tell("scores", 0, len(difficulties))
        for number, difficulty in enumerate(difficulties, 1):
            songs_html = self._fetch_official_html(session, f"{base_url}/maimai-mobile/record/musicGenre/search/?genre=99&diff={difficulty}", referer)
            tell("scores", number, len(difficulties))
            all_songs_data[difficulty] = self._parse_official_score_page(songs_html, difficulty)

        if region == "intl":
            try:
                hidden_html = self._fetch_official_html(session, f"{base_url}/maimai-mobile/home/ratingTargetMusic/", referer)
                hidden_songs = self._parse_hidden_official_songs(hidden_html, all_songs_data)
                for hidden_song in hidden_songs:
                    all_songs_data.setdefault(hidden_song["difficultyNumber"], []).append(hidden_song["song"])
            except Exception as error:
                logger.warning(f"Failed to fetch hidden songs data: {error}")

        tell("recent", 0, 1)
        recent_html = self._fetch_official_html(session, f"{base_url}/maimai-mobile/record/", referer)
        recent_songs_data = self._parse_official_recent_songs(recent_html, region)
        self.enrich_recent_play_judgements(recent_songs_data, region)
        tell("recent", 1, 1, detail=f"{len(recent_songs_data)} recent plays")
        tell("extras", 0, 1)

        album_html = self._fetch_official_html(session, f"{base_url}/maimai-mobile/playerData/photo/", referer)
        album_data = self._parse_official_albums(album_html, region)

        events_data: Dict[str, Any] = {"areaEvents": [], "eventAreaEvents": []}
        try:
            events_data = self.fetch_official_areas(region)
        except Exception as error:
            logger.warning(f"Failed to fetch official event data: {error}")

        tell("extras", 1, 1)
        flattened_songs: List[SongInfo] = []
        for difficulty in [0, 1, 2, 3, 4, 10]:
            flattened_songs.extend(all_songs_data.get(difficulty, []))

        snapshot = {
            "player": player,
            "allSongsData": all_songs_data,
            "recentSongsData": recent_songs_data,
            "albumData": album_data,
            "eventsData": events_data,
            "songs": flattened_songs,
            "cookies": getattr(self, "_official_cookie_header", ""),
            "region": region,
        }
        return snapshot

    def generate_recommendations(self) -> Tuple[List[Recommendation], Dict]:
        """Rank what the player should play next.

        :rtype: Tuple[List[Recommendation], Dict]
        """
        chart_index = self.chart_index

        self.current_version = analysis.detect_current_version(self.songs, chart_index)
        chart_index.current_version = self.current_version
        analysis.enrich_songs(self.songs, chart_index, self.current_version)

        self.play_profile = analysis.build_play_profile(
            self.songs, self.recent_songs, chart_index, self.current_version,
            play_counts=self.play_counts, recorded_plays=self.recorded_plays, judgements=self.judgements,
        )
        self.best50 = analysis.build_best50(self.songs)
        # needs the pools, so it is filled once they exist rather than inside the profile build
        self.play_profile.habits = insights.play_habits(
            self.songs, self.recent_songs, chart_index, self.play_counts, self.best50,
            recorded_plays=self.recorded_plays, profile=self.play_profile)

        print(
            f"Analyzing {len(self.songs)} charts "
            f"(version {self.current_version}, best-50 {self.best50.total})..."
        )

        candidates = analysis.generate_recommendations(
            self.songs,
            self.play_profile,
            self.best50,
            chart_index,
            self.current_version,
        )
        self.analysis_summary = analysis.summarise(candidates, self.play_profile, self.best50)

        start_rating = int(getattr(self.player, "rating", 0) or 0) or self.best50.total
        self.plan = analysis.build_plan(
            self.songs, self.play_profile, self.best50, chart_index,
            self.current_version, start_rating=start_rating, stretch=self.plan_stretch,
        )

        recommendations = [self._candidate_to_recommendation(c) for c in candidates]
        print(f"Generated {len(recommendations)} behaviour-weighted recommendations")

        value_charts = {
            candidate.title: {
                "difficulty": candidate.constant,
                "reason": candidate.reason,
                "gain": candidate.rating_gain,
                "value_score": candidate.score,
            }
            for candidate in candidates
            if candidate.rating_gain > 0
        }

        self.recommendations = recommendations
        return recommendations, value_charts

    def _candidate_to_recommendation(self, candidate: ScoredCandidate) -> Recommendation:
        cover_url = candidate.cover
        if cover_url:
            cover_url = cover_url.split("/")[-1].split("?")[0]
        max_gain = analysis.calculate_rating(candidate.constant, 100.5) - candidate.current_rating
        accuracy_gap = max(0.01, candidate.target_accuracy - candidate.current_accuracy)
        effort = accuracy_gap * 20 + max(0.0, candidate.constant - 13.5) * 1.5
        if candidate.fc_status.upper() in ("FC", "FC+", "AP", "AP+"):
            effort *= 0.7
        estimated = any(
            getattr(s, "constant_estimated", False) and str(s.name).casefold() == candidate.title.casefold()
            and (s.chart_type or "std") == candidate.chart_type and str(s.difficulty_type).lower() == candidate.difficulty_type
            for s in self.songs
        )
        return Recommendation(
            estimated=estimated,
            song=candidate.title,
            difficulty=candidate.constant,
            current_accuracy=candidate.current_accuracy,
            target_accuracy=candidate.target_accuracy,
            current_rating=candidate.current_rating,
            target_rating=candidate.target_rating,
            potential_gain=candidate.rating_gain or candidate.chart_gain,
            max_possible_gain=max(max_gain, candidate.chart_gain),
            current_rank=candidate.current_rank,
            target_rank=candidate.target_rank,
            fc_status=candidate.fc_status,
            is_new=candidate.is_new,
            priority_score=candidate.score,
            effort_score=effort,
            efficiency=candidate.rating_gain / max(1.0, effort),
            is_value_chart=candidate.rating_gain > 0,
            value_chart_reason=candidate.reason,
            level=candidate.level,
            cover_url=cover_url,
            artist=candidate.artist,
            is_unplayed=candidate.is_unplayed,
            feasibility=candidate.feasibility,
            required_accuracy=candidate.required_accuracy,
            chart_type=candidate.chart_type,
            difficulty_type=candidate.difficulty_type,
            category=candidate.category,
            plays=candidate.plays,
            expected=candidate.expected,
        )

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
