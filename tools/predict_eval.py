from pathlib import Path
from typing import Dict, List, Tuple
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rasmai.engine import analysis
from rasmai.engine.analysis import rank_for
from rasmai.scraping.otoge import CachedOtogeDB
from tools.replay import load

RANKS = ["D", "C", "B", "BB", "BBB", "A", "AA", "AAA", "S", "S+", "SS", "SS+", "SSS", "SSS+"]
PLACE = {name: i for i, name in enumerate(RANKS)}


def runs() -> List[Tuple[str, float, float, float, bool]]:
    """Every recent play in the exports, against what the model would have said about it.

    :returns: ``(player, expected, spread, actual, this run set their best)`` per play.
    """
    database = CachedOtogeDB()
    out = []
    seen = set()
    for path in sorted(Path("data").glob("maimai-export-*.json")):
        try:
            name, rating, songs, recent = load(path)
        except SystemExit:
            continue
        if not songs or name in seen:
            continue
        seen.add(name)
        index = analysis.build_chart_index(database.songs_data, region="intl")
        version = analysis.detect_current_version(songs, index)
        index.current_version = version
        analysis.enrich_songs(songs, index, version)
        judgements = [dict(p, notes=(p.get("judgement") or {}).get("notes") or {}) for p in recent if p.get("judgement")]
        profile = analysis.build_play_profile(songs, [], index, version, judgements=judgements)
        bests: Dict[Tuple[str, str, str], float] = {}
        for song in songs:
            key = (str(song.name).casefold(), str(song.chart_type or "std").lower(), str(song.difficulty_type).lower())
            bests[key] = max(bests.get(key, 0.0), float(getattr(song, "accuracy", 0) or 0))
        for play in recent:
            key = (str(play.get("songName", "")).casefold(), str(play.get("musicType", "")).lower() or "std",
                   str(play.get("difficulty", "")).lower())
            chart = index.get(key)
            actual = float(play.get("achievement") or 0) / 10000.0
            if not chart or chart.constant <= 0 or actual <= 0:
                continue
            best = bests.get(key, 0.0)
            expected, sigma = profile.chart_expectation(key, chart.constant, best)
            out.append((name, expected, sigma, actual, actual >= best - 0.0001))
    return out


def report(rows, label: str) -> None:
    if not rows:
        return
    errors = sorted(abs(actual - expected) for _n, expected, _s, actual, _pb in rows)
    signed = [actual - expected for _n, expected, _s, actual, _pb in rows]
    one = sum(1 for _n, e, s, a, _p in rows if abs(a - e) <= s) / len(rows)
    two = sum(1 for _n, e, s, a, _p in rows if abs(a - e) <= 2 * s) / len(rows)
    exact = sum(1 for _n, e, _s, a, _p in rows if rank_for(a) == rank_for(e))
    near = sum(1 for _n, e, _s, a, _p in rows
               if rank_for(a) in PLACE and rank_for(e) in PLACE and abs(PLACE[rank_for(a)] - PLACE[rank_for(e)]) <= 1)
    print(f"\n{label}  ({len(rows)} runs)")
    print(f"  median miss {errors[len(errors) // 2]:.2f}%   three quarters within {errors[int(0.75 * len(errors))]:.2f}%"
          f"   nine in ten within {errors[int(0.90 * len(errors))]:.2f}%")
    print(f"  bias {statistics.fmean(signed):+.2f}%   exact rank {exact / len(rows):.0%}   within a rank {near / len(rows):.0%}")
    print(f"  inside one spread {one:.0%} (want 68%)   inside two {two:.0%} (want 95%)"
          f"   spread stated {statistics.fmean(s for _n, _e, s, _a, _p in rows):.2f}%")


def main() -> None:
    rows = runs()
    report(rows, "every recent play")
    report([r for r in rows if not r[4]], "only runs that did not set a new best, so the score was not known in advance")


if __name__ == "__main__":
    main()
