from bs4 import BeautifulSoup, NavigableString
from datetime import datetime
from typing import List, Dict, Optional, Any
import re
import requests
import unicodedata
import logging

from rasmai.config import get_maimai_base_url
from rasmai.scraping.scraper.session import SessionRejected
from rasmai.engine.analysis import calculate_rating
from rasmai.storage.models import SongInfo

logger = logging.getLogger(__name__)


class ScorePages:
    """Reading the score lists and the song pages of maimai DX NET."""

    def _normalize_official_song_name(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text or "").replace("\u3000", " ")
        cleaned = re.sub(r"[◆☆★♪♡♢•·−\s]", "", normalized).strip()
        # the song whose whole title is one ideographic space keeps that as its name, as the database does
        return cleaned or ("　" if text and not text.strip() else "")

    def _music_type_from_icon(self, icon_src: Optional[str], difficulty_number: int) -> str:
        if difficulty_number == 10:
            return "dx"
        if not icon_src:
            return "std"
        if "music_dx.png" in icon_src:
            return "dx"
        if "music_standard.png" in icon_src:
            return "std"
        return "std"

    def _fetch_official_html(self, session: requests.Session, url: str, referer: str) -> str:
        response = session.get(
            url,
            headers={"Referer": referer},
            allow_redirects=False,
            timeout=30,
        )
        if response.status_code != 200:
            location = response.headers.get("Location", "")
            # maimai sends every dead session to the same error page part way through a read: signing
            # in elsewhere ends this one. Naming it lets the command say what to do instead of showing a 302.
            if "/maimai-mobile/error" in location:
                raise SessionRejected(
                    "maimai DX NET signed this session out part way through the read. That usually means the "
                    "account was opened somewhere else. Run /login to link again.")
            suffix = f" -> {location}" if location else ""
            raise ValueError(f"Failed to fetch official page: HTTP {response.status_code}{suffix}")
        return response.text

    def _parse_official_score_page(self, html: str, difficulty_number: int) -> List[SongInfo]:
        soup = BeautifulSoup(html, "html.parser")
        selector_map = {
            0: ".music_basic_score_back",
            1: ".music_advanced_score_back",
            2: ".music_expert_score_back",
            3: ".music_master_score_back",
            4: ".music_remaster_score_back",
            10: ".music_utage_score_back",
        }
        selector = selector_map.get(difficulty_number)
        if not selector:
            return []

        songs: List[SongInfo] = []
        for block in soup.select(selector):
            score_blocks = block.select(".music_score_block")
            if not score_blocks:
                continue

            parent = block.parent if block.parent else block
            icon_element = parent.select_one("img.music_kind_icon") if parent else None
            icon_src = icon_element.get("src") if icon_element else None
            music_type = self._music_type_from_icon(icon_src, difficulty_number)

            name_element = block.select_one(".music_name_block")
            level_element = block.select_one(".music_lv_block")
            if not name_element or not level_element or len(score_blocks) < 2:
                continue

            achievement_match = re.search(r"(\d+\.?\d*)%", score_blocks[0].get_text(" ", strip=True))
            dx_match = re.search(r"([\d,]+)\s*/\s*[\d,]+", score_blocks[1].get_text(" ", strip=True))
            if not achievement_match or not dx_match:
                continue

            fs = "none"
            fc = "none"
            h30_elements = block.select(".h_30")
            if len(h30_elements) >= 1:
                fs_src = h30_elements[0].get("src", "")
                if "fdxp.png" in fs_src:
                    fs = "fdx+"
                elif "fdx.png" in fs_src:
                    fs = "fdx"
                elif "fsp.png" in fs_src:
                    fs = "fs+"
                elif "fs.png" in fs_src:
                    fs = "fs"
                elif "sync.png" in fs_src:
                    fs = "sync"
            if len(h30_elements) >= 2:
                fc_src = h30_elements[1].get("src", "")
                if "app.png" in fc_src:
                    fc = "ap+"
                elif "ap.png" in fc_src:
                    fc = "ap"
                elif "fcp.png" in fc_src:
                    fc = "fc+"
                elif "fc.png" in fc_src:
                    fc = "fc"

            difficulty_name = {
                0: "basic",
                1: "advanced",
                2: "expert",
                3: "master",
                4: "remaster",
                10: "utage",
            }.get(difficulty_number, "basic")

            idx_input = block.select_one("input[name='idx']") or (parent.select_one("input[name='idx']") if parent else None)
            official_idx = str(idx_input.get("value", "")).strip() if idx_input else ""

            level_text = level_element.get_text(" ", strip=True)
            level_match = re.search(r"(\d+\.?\d*)", level_text)
            level_value = float(level_match.group(1)) if level_match else float(difficulty_number)

            accuracy_percent = float(achievement_match.group(1))

            song = SongInfo(
                rank=0,
                name=self._normalize_official_song_name(name_element.get_text(" ", strip=True)),
                genre="",
                difficulty=level_value,
                accuracy=accuracy_percent,
                rating=calculate_rating(level_value, accuracy_percent),
                fc_status=fc.upper(),
                is_new=False,
                potential_gains={},
                level=level_text,
                difficulty_type=difficulty_name,
                chart_type=music_type,
                dx_score=int(dx_match.group(1).replace(",", "")),
                fs_status=fs.upper(),
                official_idx=official_idx,
            )

            if song.name:
                try:
                    extra_data = self.otoge_db.search_song(song.name)
                    if extra_data:
                        song.artist = extra_data.get("artist", song.artist)
                        cover = extra_data.get("cover", "")
                        if cover:
                            if "/" in cover:
                                cover = cover.split("/")[-1]
                            if "?" in cover:
                                cover = cover.split("?")[0]
                            song.cover_url = cover
                except Exception as error:
                    logger.debug(f"Failed to enrich song '{song.name}' from cache: {error}")

            songs.append(song)

        return songs

    def _parse_official_recent_songs(self, html: str, region: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        recent_songs: List[Dict[str, Any]] = []

        for record in soup.select(".p_10.t_l.f_0.v_b"):
            track_text = record.select_one(".sub_title > .red")
            track_match = re.search(r"(?:TRACK|曲目)\s*(\d+)", track_text.get_text(" ", strip=True) if track_text else "", re.I)
            if not track_match:
                continue

            time_text_elem = record.select_one(".sub_title > .v_b:not(.red)")
            time_match = re.search(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", time_text_elem.get_text(" ", strip=True) if time_text_elem else "")
            if not time_match:
                continue

            year, month, day, hour, minute = time_match.groups()
            played_at = datetime.fromisoformat(f"{year}-{month}-{day}T{hour}:{minute}:00+09:00")

            level = record.select_one(".music_lv_back").get_text(" ", strip=True) if record.select_one(".music_lv_back") else ""

            diff_img = record.select_one("img.playlog_diff")
            diff_img_src = diff_img.get("src", "") if diff_img else ""
            difficulty_number = 0
            difficulty = "basic"
            if "utage" in diff_img_src:
                difficulty_number = 10
                difficulty = "utage"
            elif "remaster" in diff_img_src:
                difficulty_number = 4
                difficulty = "remaster"
            elif "master" in diff_img_src:
                difficulty_number = 3
                difficulty = "master"
            elif "expert" in diff_img_src:
                difficulty_number = 2
                difficulty = "expert"
            elif "advanced" in diff_img_src:
                difficulty_number = 1
                difficulty = "advanced"

            basic_block = record.select_one(".basic_block")
            song_name = ""
            if basic_block:
                for node in basic_block.contents:
                    if isinstance(node, NavigableString):
                        text = str(node).strip()
                        if text:
                            song_name = text
                song_name = self._normalize_official_song_name(song_name)
            if not song_name:
                continue

            # rendered as 92<span>.6173%</span>, so the pieces must be joined without a separator
            achievement_text = record.select_one(".playlog_achievement_txt").get_text("", strip=True) if record.select_one(".playlog_achievement_txt") else ""
            achievement_match = re.search(r"(\d+\.?\d*)%", achievement_text)
            if not achievement_match:
                continue

            dx_score_text = record.select_one(".playlog_score_block > .f_15").get_text(" ", strip=True) if record.select_one(".playlog_score_block > .f_15") else ""
            dx_score_match = re.search(r"(\d+(?:,\d+)?)\s*/\s*(\d+(?:,\d+)?)", dx_score_text)
            if not dx_score_match:
                continue

            result_images = record.select(".playlog_result_innerblock > img")
            fc = "NONE"
            fs = "NONE"
            if result_images:
                fc_src = result_images[0].get("src", "")
                if "appplus.png" in fc_src or "app.png" in fc_src:
                    fc = "AP+"
                elif "ap.png" in fc_src:
                    fc = "AP"
                elif "fcplus.png" in fc_src or "fcp.png" in fc_src:
                    fc = "FC+"
                elif "fc.png" in fc_src:
                    fc = "FC"
            if len(result_images) > 1:
                fs_src = result_images[1].get("src", "")
                if "fsdplus.png" in fs_src:
                    fs = "FDX+"
                elif "fsd.png" in fs_src:
                    fs = "FDX"
                elif "fsplus.png" in fs_src or "fsp.png" in fs_src:
                    fs = "FS+"
                elif "fs.png" in fs_src:
                    fs = "FS"
                elif "sync.png" in fs_src:
                    fs = "SYNC"

            music_kind_icon = record.select_one("img.playlog_music_kind_icon")
            music_type = "dx" if difficulty == "utage" else self._music_type_from_icon(music_kind_icon.get("src") if music_kind_icon else None, difficulty_number)

            idx_input = record.select_one("input[name='idx']")
            idx = idx_input.get("value", "") if idx_input else ""
            if not idx:
                continue

            recent_songs.append({
                "songName": song_name,
                "level": level,
                "musicType": music_type,
                "difficulty": difficulty,
                "difficultyNumber": difficulty_number,
                "achievement": round(float(achievement_match.group(1)) * 10000),
                "dxScore": int(dx_score_match.group(1).replace(",", "")),
                "maxDxScore": int(dx_score_match.group(2).replace(",", "")),
                "fc": fc,
                "fs": fs,
                "track": int(track_match.group(1)),
                "playedAt": played_at,
                "idx": idx,
            })

        return recent_songs

    def _parse_official_albums(self, html: str, region: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        albums: List[Dict[str, Any]] = []
        base_url = get_maimai_base_url(region)

        for block in soup.select(".m_10.p_5.f_0"):
            song_name_block = block.select_one(".black_block")
            if not song_name_block:
                continue

            diff_element = block.select_one(".p_r")
            diff_class_name = diff_element.get("class", []) if diff_element else []
            diff_class_str = " ".join(diff_class_name) if isinstance(diff_class_name, list) else str(diff_class_name)
            difficulty = "basic"
            if "utage" in diff_class_str:
                difficulty = "utage"
            elif "remaster" in diff_class_str:
                difficulty = "remaster"
            elif "master" in diff_class_str:
                difficulty = "master"
            elif "expert" in diff_class_str:
                difficulty = "expert"
            elif "advanced" in diff_class_str:
                difficulty = "advanced"

            music_kind_icon = block.select_one(".music_kind_icon")
            music_type = "dx" if difficulty == "utage" else self._music_type_from_icon(music_kind_icon.get("src") if music_kind_icon else None, 0)

            block_info = block.select_one(".block_info")
            taken_at_text = block_info.get_text(" ", strip=True) if block_info else ""
            taken_at_match = re.search(r"(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})", taken_at_text)
            if not taken_at_match:
                continue
            year, month, day, hour, minute = taken_at_match.groups()
            taken_at = datetime.fromisoformat(f"{year}-{month}-{day}T{hour}:{minute}:00+09:00")

            image_element = block.select_one("img.w_430")
            image_url = ""
            if image_element and image_element.get("src"):
                image_src = image_element.get("src")
                image_url = image_src if image_src.startswith("http") else f"{base_url}{image_src}"
            if not image_url:
                continue

            venue_block = block.select_one(".see_through_block")
            venue = venue_block.get_text(" ", strip=True) if venue_block else None

            albums.append({
                "songName": self._normalize_official_song_name(song_name_block.get_text(" ", strip=True)),
                "musicType": music_type,
                "difficulty": difficulty,
                "takenAt": taken_at,
                "imageUrl": image_url,
                "venue": venue,
            })

        return albums

    def _parse_hidden_official_songs(self, html: str, all_songs_data: Dict[int, List[SongInfo]]) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        hidden_songs: List[Dict[str, Any]] = []
        selector_map = {
            0: ".music_basic_score_back",
            1: ".music_advanced_score_back",
            2: ".music_expert_score_back",
            3: ".music_master_score_back",
            4: ".music_remaster_score_back",
        }

        for difficulty_number, selector in selector_map.items():
            for block in soup.select(selector):
                name_element = block.select_one(".music_name_block")
                icon_element = block.select_one("img.music_kind_icon")
                score_blocks = block.select(".music_score_block")
                if not name_element or not icon_element or not score_blocks:
                    continue
                song_name = self._normalize_official_song_name(name_element.get_text(" ", strip=True))
                if any(song.name == song_name for song in all_songs_data.get(difficulty_number, [])):
                    continue
                achievement_match = re.search(r"(\d+\.?\d*)%", score_blocks[0].get_text(" ", strip=True))
                if not achievement_match:
                    continue
                hidden_accuracy = float(achievement_match.group(1))
                hidden_idx_input = block.select_one("input[name='idx']") or (
                    block.parent.select_one("input[name='idx']") if block.parent else None
                )
                hidden_songs.append({
                    "difficultyNumber": difficulty_number,
                    "song": SongInfo(
                        rank=0,
                        name=song_name,
                        genre="",
                        difficulty=float(difficulty_number),
                        accuracy=hidden_accuracy,
                        rating=0,
                        fc_status="",
                        is_new=False,
                        potential_gains={},
                        level={0: "BASIC", 1: "ADVANCED", 2: "EXPERT", 3: "MASTER", 4: "Re:MASTER"}.get(difficulty_number, "MASTER"),
                        difficulty_type={0: "basic", 1: "advanced", 2: "expert", 3: "master", 4: "remaster"}.get(difficulty_number, "basic"),
                        chart_type=self._music_type_from_icon(icon_element.get("src"), difficulty_number),
                        official_idx=str(hidden_idx_input.get("value", "")).strip() if hidden_idx_input else "",
                    ),
                })

        return hidden_songs
