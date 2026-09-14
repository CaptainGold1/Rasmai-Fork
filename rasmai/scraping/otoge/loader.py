from datetime import datetime
from typing import Any
import json


def load_songs_from_repo(db: Any) -> bool:
    """Read the songs out of the checkout into ``songs_data``.

    :returns: True when at least one song was read; on any failure the data already held is kept.
    :rtype: bool
    """
    try:
        db._log("=" * 60, "info")
        db._log("STARTING SONG LOAD FROM REPO", "info")
        db._log("=" * 60, "info")

        # the database snapshots the live music-ex.json into music-ex-<version>-final.json every time
        # the game rolls over, so the set is found rather than listed and a new version needs no edit.
        # First file wins, so the live one leads and the deleted list trails: a song still in the game
        # must not be marked deleted because an older file also holds it.
        data_dir = db.repo_path / 'maimai' / 'data'
        finals = sorted(path.name for path in data_dir.glob('music-ex-*-final.json'))
        music_files = [('music-intl.json', 'intl'), ('music-ex.json', 'ex')]
        music_files += [(name, 'ex') for name in finals] + [('music-ex-deleted.json', 'ex')]

        all_music_data = {}
        source_stats = {}

        for music_file, file_type in music_files:
            music_json_path = db.repo_path / 'maimai' / 'data' / music_file
            if music_json_path.exists():
                db._log(f"Loading {music_file}...", "info")
                try:
                    with open(music_json_path, 'r', encoding='utf-8') as f:
                        music_data = json.load(f)

                    count = 0
                    if isinstance(music_data, list):
                        for song in music_data:
                            title = song.get('title', song.get('name', ''))
                            if title:
                                title_key = title.lower()
                                # a second song with the same title (the two "Link"s) keeps its own entry
                                if title_key in all_music_data and str(all_music_data[title_key]['data'].get('artist', '')) != str(song.get('artist', '')):
                                    title_key = f"{title_key}|{str(song.get('artist', '')).lower()}"
                                if title_key not in all_music_data:
                                    all_music_data[title_key] = {
                                        'data': song,
                                        'source': file_type,
                                        'source_file': music_file
                                    }
                                    if 'xaleid' in title_key or 'scopix' in title_key:
                                        db._log(f"  FOUND TARGET SONG in {music_file}: {title}", "info")
                                        db._log(f"    Cover: {song.get('image_url', 'NONE')}", "info")
                                else:
                                    existing = all_music_data[title_key]
                                    if file_type == 'ex' and existing['source'] != 'ex':
                                        existing['data'] = song
                                        existing['source'] = file_type
                                        existing['source_file'] = music_file
                        count = len(music_data)

                    elif isinstance(music_data, dict):
                        songs_list = None
                        if 'songs' in music_data:
                            songs_list = music_data['songs']
                        elif 'music' in music_data:
                            songs_list = music_data['music']
                        else:
                            for key, value in music_data.items():
                                if isinstance(value, list) and len(value) > 0:
                                    if isinstance(value[0], dict):
                                        if 'title' in value[0] or 'image_url' in value[0]:
                                            songs_list = value
                                            break

                        if songs_list:
                            for song in songs_list:
                                title = song.get('title', song.get('name', ''))
                                if title:
                                    title_key = title.lower()
                                    if title_key not in all_music_data:
                                        all_music_data[title_key] = {
                                            'data': song,
                                            'source': file_type,
                                            'source_file': music_file
                                        }
                                        if 'xaleid' in title_key or 'scopix' in title_key:
                                            db._log(f"  FOUND TARGET SONG in {music_file}: {title}", "info")
                                            db._log(f"    Cover: {song.get('image_url', 'NONE')}", "info")
                                    else:
                                        existing = all_music_data[title_key]
                                        if file_type == 'ex' and existing['source'] != 'ex':
                                            existing['data'] = song
                                            existing['source'] = file_type
                                            existing['source_file'] = music_file
                            count = len(songs_list)

                    source_stats[music_file] = count
                    db._log(f"  Loaded {count} songs from {music_file}", "info")

                except Exception as e:
                    db._log(f"  Error loading {music_file}: {e}", "error")
            else:
                db._log(f"  {music_file} not found", "debug")

        if not all_music_data:
            db._log("No music data files found!", "error")
            return False

        db._log(f"Total loaded {len(all_music_data)} unique songs from all sources", "info")

        cover_count = 0
        songs_by_title = {}
        db.cover_cache = {}

        for title_lower, entry in all_music_data.items():
            song = entry['data'].copy()
            title = song.get('title', song.get('name', ''))
            if not title:
                continue

            alt_title = song.get('altTitle', song.get('title_kana', ''))
            alt_title_lower = alt_title.lower() if alt_title else ''

            cover = song.get('image_url', '')
            if not cover:
                cover = song.get('cover', '')
            if not cover:
                cover = song.get('jacket', '')

            if cover and '/' in cover:
                cover = cover.split('/')[-1]
                if '?' in cover:
                    cover = cover.split('?')[0]

            if 'xaleid' in title_lower or 'scopix' in title_lower:
                db._log(f"Processing target song: {title}", "info")
                db._log(f"  Cover from data: {cover}", "info")
                db._log(f"  Source file: {entry['source_file']}", "info")

            song_info = {
                'id': song.get('id'),
                'title': title,
                'alt_title': alt_title,
                'artist': song.get('artist', ''),
                'genre': song.get('catcode', song.get('genre', '')),
                'bpm': song.get('bpm'),
                'cover': cover,
                'charts': song.get('charts', []),
                'lev_bas': song.get('lev_bas', ''),
                'lev_adv': song.get('lev_adv', ''),
                'lev_exp': song.get('lev_exp', ''),
                'lev_mas': song.get('lev_mas', ''),
                'lev_remas': song.get('lev_remas', ''),
                'version': song.get('version', ''),
                'sort': song.get('sort', ''),
                'dx_lev_bas': song.get('dx_lev_bas', ''),
                'dx_lev_adv': song.get('dx_lev_adv', ''),
                'dx_lev_exp': song.get('dx_lev_exp', ''),
                'dx_lev_mas': song.get('dx_lev_mas', ''),
                'dx_lev_remas': song.get('dx_lev_remas', ''),
                'dx_lev_bas_i': song.get('dx_lev_bas_i', ''),
                'dx_lev_adv_i': song.get('dx_lev_adv_i', ''),
                'dx_lev_exp_i': song.get('dx_lev_exp_i', ''),
                'dx_lev_mas_i': song.get('dx_lev_mas_i', ''),
                'dx_lev_remas_i': song.get('dx_lev_remas_i', ''),
                'lev_bas_i': song.get('lev_bas_i', ''),
                'lev_adv_i': song.get('lev_adv_i', ''),
                'lev_exp_i': song.get('lev_exp_i', ''),
                'lev_mas_i': song.get('lev_mas_i', ''),
                'lev_remas_i': song.get('lev_remas_i', ''),
                'lev_bas_notes': song.get('lev_bas_notes', ''),
                'lev_adv_notes': song.get('lev_adv_notes', ''),
                'lev_exp_notes': song.get('lev_exp_notes', ''),
                'lev_mas_notes': song.get('lev_mas_notes', ''),
                'lev_remas_notes': song.get('lev_remas_notes', ''),
                'dx_lev_bas_notes': song.get('dx_lev_bas_notes', ''),
                'dx_lev_adv_notes': song.get('dx_lev_adv_notes', ''),
                'dx_lev_exp_notes': song.get('dx_lev_exp_notes', ''),
                'dx_lev_mas_notes': song.get('dx_lev_mas_notes', ''),
                'dx_lev_remas_notes': song.get('dx_lev_remas_notes', ''),
                'lev_bas_designer': song.get('lev_bas_designer', ''),
                'lev_adv_designer': song.get('lev_adv_designer', ''),
                'lev_exp_designer': song.get('lev_exp_designer', ''),
                'lev_mas_designer': song.get('lev_mas_designer', ''),
                'lev_remas_designer': song.get('lev_remas_designer', ''),
                'wiki_url': song.get('wiki_url', ''),
                'intl': song.get('intl', ''),
                'deleted': entry['source_file'] == 'music-ex-deleted.json',
            }

            songs_by_title[title_lower] = song_info
            # an alternate title is only an alias while no song owns that title itself:
            # utage charts like "[音]snooze" carry alt title "SNOOZE" and must not
            # replace the real "snooze"
            alias = alt_title_lower if alt_title_lower and alt_title_lower != title_lower else ''
            if cover:
                cover_count += 1
                db.cover_cache[title_lower] = cover
                if alias and alias not in all_music_data:
                    db.cover_cache[alias] = cover

                if 'xaleid' in title_lower or 'scopix' in title_lower:
                    db._log(f"  Added cover to cache for {title}: {cover}", "info")

            if alias and alias not in all_music_data:
                songs_by_title[alias] = song_info

        db.songs_data = songs_by_title

        with open(db.last_update_file, 'w') as f:
            f.write(datetime.now().isoformat())

        db._save_cache()

        db._log(f"Cached {len(db.songs_data)} song entries with {cover_count} covers", "info")

        db._log("=" * 60, "info")
        db._log("FINAL TARGET SONG CHECK:", "info")
        for key in db.songs_data.keys():
            if 'xaleid' in key or 'scopix' in key:
                db._log(f"  In songs_data: {key}", "info")
                data = db.songs_data[key]
                db._log(f"    Cover: {data.get('cover', 'NONE')}", "info")

        for key in db.cover_cache.keys():
            if 'xaleid' in key or 'scopix' in key:
                db._log(f"  In cover_cache: {key} -> {db.cover_cache[key]}", "info")
        db._log("=" * 60, "info")
        return bool(db.songs_data)

    except Exception as e:
        db._log(f"Error loading songs from repo: {e}", "error")
        import traceback
        traceback.print_exc()
        return False
