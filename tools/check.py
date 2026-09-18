from pathlib import Path
import ast
import importlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []

# song titles, charter names and pattern tags are mostly Japanese, and a Windows console defaults to
# a codepage that cannot print them: without this the sweep dies on the first check that names one
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

print("Rasmai verification sweep")


def check(name):
    """Mark a step and record whatever it reports.

    :param name: What the step is called in the output.
    :type name: str
    :returns: A decorator that runs the step and collects its complaints.
    :rtype: Callable
    """
    def wrap(fn):
        try:
            problems = fn() or []
        except Exception as error:
            problems = [f"the check itself failed: {type(error).__name__}: {error}"]
        # printed after the step runs, so a library logging on import cannot split the line
        print(f"  {'FAIL' if problems else 'ok  '}  {name}", flush=True)
        for problem in problems:
            print(f"          {problem}")
        if problems:
            FAILURES.append(name)
        return fn
    return wrap


def python_files():
    """Every Python file the project owns.

    :rtype: List[Path]
    """
    return sorted(list((ROOT / "rasmai").rglob("*.py")) + list((ROOT / "tools").rglob("*.py")) + [ROOT / "dev.py"])


@check("no undefined names, shadowed definitions or repeated keys")
def _pyflakes():
    # this is what catches a name that only fails when the line runs, which no import test reaches
    result = subprocess.run([sys.executable, "-m", "pyflakes", "rasmai", "tools", "dev.py"],
                            cwd=str(ROOT), capture_output=True, text=True)
    if "No module named" in result.stderr:
        return ["pyflakes is not installed: pip install pyflakes"]
    ignore = ("imported but unused", "unable to detect undefined names", "'from .* import \\*' used")
    return [line for line in result.stdout.splitlines() if line.strip() and not any(skip in line for skip in ignore)]


@check("every module imports")
def _imports():
    problems = []
    for path in sorted((ROOT / "rasmai").rglob("*.py")):
        if path.name in ("__init__.py", "__main__.py"):
            continue
        module = str(path.relative_to(ROOT).with_suffix("")).replace("\\", ".").replace("/", ".")
        try:
            importlib.import_module(module)
        except Exception as error:
            problems.append(f"{module}: {type(error).__name__}: {error}")
    return problems


@check("starting the bot fills the command tree")
def _commands():
    # An empty tree once told Discord to delete every command, because the import that registers
    # them read as unused and was removed. This runs the real start-up path in a clean interpreter
    # and never imports the commands itself, so it fails if setup_hook stops filling the tree.
    script = """
import asyncio, sys
sys.path.insert(0, %r)
from rasmai.bot import core
async def _skip_sync():
    pass
core.sync_commands_if_changed = _skip_sync
asyncio.run(core.setup_hook())
print("NAMES:" + ",".join(sorted(c.name for c in core.bot.tree.get_commands())))
"""
    result = subprocess.run([sys.executable, "-c", script % str(ROOT)], cwd=str(ROOT),
                            capture_output=True, text=True)
    line = next((l for l in result.stdout.splitlines() if l.startswith("NAMES:")), None)
    if line is None:
        return [f"start-up did not reach the command tree: {result.stderr.strip().splitlines()[-1:] or result.stdout}"]
    names = [n for n in line[len("NAMES:"):].split(",") if n]
    problems = []
    if not names:
        return ["start-up left the command tree empty: syncing that would delete every registered command"]
    if len(names) < 20:
        problems.append(f"only {len(names)} commands registered, expected the full set")
    for wanted in ("analyze", "plan", "session", "new", "chart", "charts", "recent", "area", "refresh", "login"):
        if wanted not in names:
            problems.append(f"/{wanted} is missing from the tree")
    # folded into other commands: a stray registration means an old module came back
    for gone in ("song", "level", "lastplay", "traits"):
        if gone in names:
            problems.append(f"/{gone} is registered again; it was folded into /chart, /charts, /recent and the results view")
    from rasmai.bot.builders.results import ResultsView
    if "traits" not in {key for key, _label in ResultsView.MODES}:
        problems.append("the results view has no Traits mode, so traits are unreachable")
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        problems.append(f"the same name is registered twice: {sorted(duplicates)}")
    return problems


@check("no component sends more defaults than Discord allows")
def _components():
    # a select may pre-select at most max_values options; sending two is a 400 that only shows at runtime
    import discord
    from rasmai.bot.builders.results import ResultsView, NEW_LEVELS
    problems = []
    for mode in ("analyze", "plan", "session", "new", "profile", "traits"):
        for difficulty in (None, "master"):
            for level in [None] + list(NEW_LEVELS)[:3]:
                for focus in (None, "weak", "strong"):
                    view = ResultsView(1, mode, difficulty=difficulty, level=level, focus=focus)
                    for item in view.children:
                        if isinstance(item, discord.ui.Select):
                            chosen = [option for option in item.options if option.default]
                            if len(chosen) > item.max_values:
                                problems.append(
                                    f"{mode} difficulty={difficulty} level={level} focus={focus}: "
                                    f"{len(chosen)} defaults but max_values={item.max_values}")
                            if len(item.options) > 25:
                                problems.append(f"{mode}: a select holds {len(item.options)} options, the cap is 25")
    return problems[:5]


@check("the level bands match the game")
def _levels():
    from rasmai.engine.analysis import level_range, level_floor
    problems = []
    expected = {"13": (13.0, 13.5), "13+": (13.6, 13.9), "14": (14.0, 14.5), "14+": (14.6, 14.9),
                "6": (6.0, 6.9), "6+": None, "x": None}
    for level, want in expected.items():
        got = level_range(level)
        if got != want:
            problems.append(f"level_range({level!r}) is {got}, expected {want}")
    if level_floor("13+") != 13.6:
        problems.append(f"level_floor('13+') is {level_floor('13+')}, expected 13.6 to match level_range")
    return problems


@check("the rating maths is unchanged")
def _rating():
    from rasmai.engine.analysis import calculate_rating, rank_for, accuracy_for_rating
    problems = []
    for accuracy, rank in ((100.5, "SSS+"), (100.0, "SSS"), (99.5, "SS+"), (97.0, "S"), (80.0, "A")):
        if rank_for(accuracy) != rank:
            problems.append(f"rank_for({accuracy}) is {rank_for(accuracy)!r}, expected {rank!r}")
    if calculate_rating(13.5, 100.5) != 303:
        problems.append(f"calculate_rating(13.5, 100.5) is {calculate_rating(13.5, 100.5)}, expected 303")
    if accuracy_for_rating(0, 250) is not None:
        problems.append("accuracy_for_rating with no constant should be None")
    return problems


@check("a failed attempt does not raise the ceiling searches reach from")
def _ceiling():
    from rasmai.engine.analysis import ChartIndex, build_play_profile, unplayed_window
    from rasmai.engine.analysis.picks import MAX_UNPLAYED_PICKS
    from rasmai.storage.models import SongInfo
    # a 12,000-ish player: SS territory to 11.5, S to 12.8, then one failed attempt at a 15
    songs = []
    for tenth in range(90, 129):
        constant = tenth / 10.0
        for i in range(3):
            accuracy = 100.2 - (constant - 9.0) * 0.55 - i * 0.4
            songs.append(SongInfo(name=f"c{tenth}-{i}", chart_type="dx", difficulty_type="master", accuracy=round(accuracy, 4),
                                  level="12", difficulty=constant, rating=200))
    songs.append(SongInfo(name="the wall", chart_type="dx", difficulty_type="master", accuracy=68.7, level="15", difficulty=15.0, rating=100))
    profile = build_play_profile(songs, [], ChartIndex(), 26)
    problems = []
    if profile.played_ceiling != 15.0:
        problems.append(f"played_ceiling should still record the attempt, got {profile.played_ceiling}")
    if profile.search_ceiling >= 14.0 or profile.search_ceiling < profile.hardest_s:
        problems.append(f"search_ceiling {profile.search_ceiling} should sit at the hardest S ({profile.hardest_s}), not at the failed 15")
    low, high = unplayed_window(profile, "balanced")
    if high > profile.search_ceiling + 0.3 + 1e-9:
        problems.append(f"balanced /new reaches {high}, past the search ceiling {profile.search_ceiling} + 0.3")
    if profile.reach_constant - profile.comfort_constant > 1.0 + 1e-9:
        problems.append(f"comfort {profile.comfort_constant} sits more than a level under reach {profile.reach_constant}")
    if not 3 <= MAX_UNPLAYED_PICKS <= 10:
        problems.append(f"MAX_UNPLAYED_PICKS is {MAX_UNPLAYED_PICKS}; a handful is the point")
    return problems


@check("the new-chart list spans its window instead of one constant")
def _spread():
    from rasmai.engine.analysis import (ChartIndex, ChartRef, build_best50, build_play_profile, challenge_for,
                                        recommend_unplayed, unplayed_window)
    from rasmai.storage.models import SongInfo
    index = ChartIndex("intl")
    for tenth in range(100, 141):
        constant = tenth / 10.0
        for n in range(6):
            index.add(ChartRef(title=f"unplayed {tenth} {n}", chart_type="dx", difficulty="master", constant=constant,
                               level=str(int(constant)), notes=700, genre="maimai", artist="a", cover="", version=26, intl=True))
    songs = []
    for tenth in range(95, 126):
        constant = tenth / 10.0
        for n in range(3):
            accuracy = round(100.4 - (constant - 9.5) * 0.12 - n * 0.2, 4)     # flat and high, so many constants clear the first-pass floor
            songs.append(SongInfo(name=f"played {tenth} {n}", chart_type="dx", difficulty_type="master", accuracy=accuracy,
                                  level=str(int(constant)), difficulty=constant, rating=250))
    profile = build_play_profile(songs, [], index, 26)
    problems = []
    for tier in ("easy", "balanced", "hard", "extreme"):
        low, high = unplayed_window(profile, tier)
        floor = challenge_for(tier).new_floor
        offered = {round(chart.constant, 1) for chart in index.values()
                   if low <= chart.constant <= high
                   and profile.expected_for(chart.constant, chart.difficulty) - 0.35 - 0.4 * profile.sigma_at(chart.constant) >= floor}
        picks = recommend_unplayed(songs, profile, build_best50(songs), index, 26, limit=12, challenge=tier)
        if not picks or not offered:
            continue
        shown = {round(p.constant, 1) for p in picks}
        # the list should spend the window: as many distinct constants as it has room for, not one repeated
        want = min(len(offered), 12 // max(2, 12 // 6))
        if len(shown) < want:
            problems.append(f"{tier}: 12 picks cover {len(shown)} constant(s) {sorted(shown)} of the {len(offered)} the window offers")
    # the same call twice must give the same order, or the page reshuffles between reads
    first = [p.title for p in recommend_unplayed(songs, profile, build_best50(songs), index, 26, limit=12)]
    again = [p.title for p in recommend_unplayed(songs, profile, build_best50(songs), index, 26, limit=12)]
    if first != again:
        problems.append("two identical calls returned different orders")
    return problems


@check("no annotation names something defined further down its own file")
def _forward_refs():
    """Python 3.12 evaluates annotations when a def is executed; 3.14 defers them.

    A signature that names a class defined later in the same file therefore runs here and fails on
    the version CI uses, so the local sweep has to reproduce the older reading rather than trust it.
    """
    problems = []
    for path in python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue                      # the compile check reports these on its own
        defined_at = {}
        for index, node in enumerate(tree.body):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                defined_at.setdefault(node.name, index)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined_at.setdefault(target.id, index)
        for index, node in enumerate(tree.body):
            for inner in ast.walk(node):
                if not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                pieces = [arg.annotation for arg in inner.args.args + inner.args.kwonlyargs if arg.annotation]
                if inner.returns is not None:
                    pieces.append(inner.returns)
                for piece in pieces:
                    for name in {n.id for n in ast.walk(piece) if isinstance(n, ast.Name)}:
                        later = defined_at.get(name)
                        if later is not None and later > index:
                            problems.append(f"{path}: {inner.name}() is annotated with {name}, which this file only defines further down")
    return sorted(set(problems))


@check("a short pick list is continued with charts worth a first run")
def _topup():
    from rasmai.engine.analysis import ChartIndex, ChartRef, build_best50, build_play_profile, generate_recommendations
    from rasmai.engine.analysis.picks import MIN_PICKS
    from rasmai.storage.models import SongInfo
    index = ChartIndex("intl")
    for tenth in range(100, 141):
        constant = tenth / 10.0
        for n in range(6):
            index.add(ChartRef(title=f"unplayed {tenth} {n}", chart_type="dx", difficulty="master", constant=constant,
                               level=str(int(constant)), notes=700, genre=f"genre {n % 3}", artist="a", cover="", version=26, intl=True))
    # a player with a handful of scores: almost nothing of theirs can move a best-50 that is not full
    songs = []
    for tenth in range(118, 125):
        constant = tenth / 10.0
        songs.append(SongInfo(name=f"played {tenth}", chart_type="dx", difficulty_type="master", accuracy=99.8,
                              level=str(int(constant)), difficulty=constant, rating=250))
    profile = build_play_profile(songs, [], index, 26)
    best50 = build_best50(songs)
    problems = []
    picks = generate_recommendations(songs, profile, best50, index, 26, challenge="balanced")
    grind = [c for c in picks if c.category not in ("near", "try")]
    tries = [c for c in picks if c.category == "try"]
    if len(grind) < MIN_PICKS and not tries:
        problems.append(f"only {len(grind)} played picks and no charts to try were offered")
    if len(grind) + len(tries) < min(MIN_PICKS, len(grind) + len(tries)):
        problems.append("the top-up did not fill the list")
    for candidate in tries:
        if not candidate.is_unplayed or candidate.current_accuracy:
            problems.append(f"{candidate.title}: offered as a first run but carries a score")
        if not candidate.reason:
            problems.append(f"{candidate.title}: offered with no reason given")
    seen = [(c.title, c.difficulty_type) for c in picks]
    if len(seen) != len(set(seen)):
        problems.append("a chart is listed twice")
    # a full list must not be padded
    many = generate_recommendations(songs * 1, profile, best50, index, 26, challenge="extreme")
    if len([c for c in many if c.category not in ("near", "try")]) >= MIN_PICKS and any(c.category == "try" for c in many):
        problems.append("a list that is already long was padded with charts to try")
    return problems


@check("the target levels stay in order, easier through to long shots")
def _ladder():
    from rasmai.engine.analysis import CHALLENGES
    order = ["easy", "balanced", "hard", "extreme"]
    problems = []
    missing = [key for key in order if key not in CHALLENGES]
    if missing:
        return [f"missing target level(s): {missing}"]
    if list(CHALLENGES) != order:
        problems.append(f"CHALLENGES is ordered {list(CHALLENGES)}; the bolder-level search and the menus read it in order")
    for earlier, later in zip(order, order[1:]):
        a, b = CHALLENGES[earlier], CHALLENGES[later]
        if not b.sigmas > a.sigmas:
            problems.append(f"{later} reaches {b.sigmas} spreads, no further than {earlier} at {a.sigmas}")
        if not b.min_feasibility < a.min_feasibility:
            problems.append(f"{later} floors odds at {b.min_feasibility}, no lower than {earlier} at {a.min_feasibility}")
    # a level must never offer a target it would then refuse to plan
    for key, mode in CHALLENGES.items():
        if mode.plan_min_feasibility < mode.min_feasibility:
            problems.append(f"{key}: the route accepts {mode.plan_min_feasibility} odds, under the {mode.min_feasibility} the picks demand")
    return problems


@check("chart trait labels carry their English wording")
def _labels():
    from rasmai.scraping.mai_notes import english_label
    cases = {"乱打 (streams)": "streams",
             "slow songs (under 130 BPM)": "slow songs (under 130 BPM)",
             "charts by rioN": "charts by rioN"}
    return [f"english_label({k!r}) is {english_label(k)!r}, expected {v!r}"
            for k, v in cases.items() if english_label(k) != v]


@check("a best that was one dropped run is offered again at what the player scores at that level")
def _dropped():
    from rasmai.engine.analysis import ChartIndex, build_best50, build_play_profile, calculate_rating, generate_recommendations
    from rasmai.storage.models import SongInfo
    # a player who scores ~99 on everything 11.5 to 13.0, with room left in their best-50 (32 charts, 35 old slots)
    songs = []
    for tenth in range(115, 131):
        constant = tenth / 10.0
        for n in range(2):
            accuracy = round(99.6 - (constant - 11.5) * 0.3 - n * 0.15, 4)
            songs.append(SongInfo(name=f"played {tenth} {n}", chart_type="dx", difficulty_type="master", accuracy=accuracy, is_new=False,
                                  level=str(int(constant)), difficulty=constant, rating=calculate_rating(constant, accuracy)))
    songs.append(SongInfo(name="Dropped", chart_type="dx", difficulty_type="master", accuracy=86.5, level="12", is_new=False,
                          difficulty=12.8, rating=calculate_rating(12.8, 86.5)))
    index = ChartIndex()
    best50 = build_best50(songs)
    problems = []
    # no play counts: the one score is proof of one play, and 86.5 on a 12.8 is a run that was dropped
    profile = build_play_profile(songs, [], index, 26)
    picks = {c.title: c for c in generate_recommendations(songs, profile, best50, index, 26, challenge="balanced")}
    pick = picks.get("Dropped")
    if pick is None:
        problems.append("a 12.8 scored 86.5 once, by a player who scores ~99 on 12.8s, was not offered at all")
    elif pick.target_accuracy < 97.0:
        problems.append(f"the dropped run's target is {pick.target_accuracy}, under the S its level supports")
    elif "one run" not in pick.reason:
        problems.append(f"the pick does not say why: {pick.reason!r}")
    # a dozen plays ending at 86.5 is the chart's difficulty for them, and the target stays near the score
    profile = build_play_profile(songs, [], index, 26, play_counts={("dropped", "dx", "master"): 12})
    picks = {c.title: c for c in generate_recommendations(songs, profile, best50, index, 26, challenge="balanced")}
    pick = picks.get("Dropped")
    if pick is not None and pick.target_accuracy >= 97.0:
        problems.append(f"twelve plays ending at 86.5 were still offered an S ({pick.target_accuracy})")
    # the index folds a key itself, so a title with capitals finds its chart under either spelling
    from rasmai.engine.analysis import ChartRef
    index.add(ChartRef(title="Dropped", chart_type="dx", difficulty="master", constant=12.8, level="12", notes=700,
                       genre="maimai", artist="a", cover="", version=26, intl=True))
    if index.get(("Dropped", "dx", "master")) is None or index.get(("dropped", "dx", "master")) is None:
        problems.append("ChartIndex.get does not fold the title it is given")
    return problems


@check("an expired maimai session is flagged until the player links again")
def _expired():
    import tempfile, pathlib
    from rasmai.storage.db import connection as store
    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    try:
        from rasmai.storage.db import get_connected_account, mark_session_expired, upsert_connected_account
        problems = []
        upsert_connected_account("u1", "intl", "cookie://abc")
        if get_connected_account("u1")["sessionExpired"]:
            problems.append("a freshly linked account is already flagged")
        mark_session_expired("u1", "2026-09-13T10:00:00")
        if get_connected_account("u1")["sessionExpired"] != "2026-09-13T10:00:00":
            problems.append("the refusal was not recorded")
        mark_session_expired("u1", "2026-09-14T10:00:00")
        if get_connected_account("u1")["sessionExpired"] != "2026-09-13T10:00:00":
            problems.append("a later refusal moved the date; it should keep the first one")
        upsert_connected_account("u1", "intl", "cookie://new")
        if get_connected_account("u1")["sessionExpired"]:
            problems.append("linking again did not clear the flag, so the banner would never go away")
        # not every refusal is a dead cookie: maimai serves the same error page for passing faults,
        # so a read that lands afterwards has to clear the flag without making anyone link again
        from rasmai.storage.db import update_account_snapshot
        mark_session_expired("u1", "2026-09-13T10:00:00")
        update_account_snapshot("u1", {"name": "Nek"}, {"charts": []})
        if get_connected_account("u1")["sessionExpired"]:
            problems.append("a read that succeeded left the account flagged as expired")
        return problems
    finally:
        store.DATABASE_PATH = was
        store._database_ready = False


@check("a play-count refresh drops every poster built for that level and nothing else")
def _forget():
    from rasmai.bot.state.cache import CachedAnalysis
    cached = CachedAnalysis(user_id="1", region="intl", analyzer=None, recommendations=[], value_charts=[])   # type: ignore[arg-type]
    cached.analyses = {("balanced", ""): 1, ("balanced", "13+"): 1, ("hard", ""): 1}
    cached.plans = {(None, False, "balanced", "", ""): 1, (None, False, "hard", "", ""): 1}
    cached.images = {"analyze:balanced:": 1, "analyze:balanced:level 13+": 1, "plan:None:False:balanced::": 1,
                     "new:master::balanced:": 1, "session:3:balanced:": 1, "analyze:hard:": 1, "profile:x": 1}
    cached.forget("balanced")
    problems = []
    stale = [k for k in list(cached.analyses) + list(cached.plans) + list(cached.images) if "balanced" in str(k)]
    if stale:
        problems.append(f"still cached after forgetting balanced: {stale}")
    if set(cached.images) != {"analyze:hard:", "profile:x"} or ("hard", "") not in cached.analyses:
        problems.append(f"forgetting balanced took other levels with it: {sorted(cached.images)}")
    return problems


@check("what a play lost per note type adds up to what was missing from 101%")
def _losses():
    from rasmai.engine.losses import note_losses
    tap = {"critical": 95, "perfect": 0, "great": 5, "good": 0, "miss": 0}
    breaks = {"critical": 10, "perfect": 0, "great": 0, "good": 0, "miss": 0}
    # 100 taps + 10 breaks: 150 shares, so one tap is 2/3 of a point and five greats cost one fifth each
    lost = note_losses({"tap": tap, "break": breaks}, 101 - 100 / 150)
    problems = []
    if abs(lost.get("tap", 0) - 100 / 150) > 1e-9 or lost.get("break", 0) > 1e-9:
        problems.append(f"five tap greats among 150 shares: {lost}")
    # a break miss loses its five shares and its slice of the 1% bonus; a break perfect's bonus loss lands on breaks too
    breaks = {"critical": 8, "perfect": 1, "great": 0, "good": 0, "miss": 1}
    lost = note_losses({"tap": {"critical": 100, "perfect": 0, "great": 0, "good": 0, "miss": 0}, "break": breaks}, 101 - (500 / 150 + 0.1) - 0.25)
    if abs(lost.get("break", 0) - (500 / 150 + 0.1 + 0.25)) > 1e-9 or lost.get("tap", 0) > 1e-9:
        problems.append(f"one break miss and one break perfect: {lost}")
    if note_losses({}, 100.0):
        problems.append("no judgements should cost nothing")
    return problems


@check("one full read per account, whichever side asked for it")
def _one_read():
    from rasmai.bot.state import reads
    problems = []
    reads.release("u1")
    if reads.claim("u1", reads.DISCORD) is not None:
        problems.append("a free account would not start a read")
    held = reads.claim("u1", reads.WEBSITE)
    if held != reads.DISCORD:
        problems.append(f"the website started a second read while Discord was reading: {held!r}")
    if reads.claim("u1", reads.DISCORD) != reads.DISCORD:
        problems.append("a second Discord read was allowed alongside the first")
    if reads.running("u1") != reads.DISCORD:
        problems.append("the slot does not say who holds it")
    reads.release("u1")
    if reads.running("u1") is not None:
        problems.append("the slot was not given back")
    if reads.claim("u1", reads.WEBSITE) is not None:
        problems.append("the account could not be read again after the slot was released")
    reads.release("u1")
    # one account reading must never block a different one
    reads.claim("u1", reads.DISCORD)
    if reads.claim("u2", reads.WEBSITE) is not None:
        problems.append("one account reading blocked a different account")
    reads.release("u1")
    reads.release("u2")
    return problems


@check("a public profile carries only what its owner turned on")
def _public_profile():
    import tempfile, pathlib
    from rasmai.storage.db import connection as store
    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    try:
        from rasmai.bot.state.prefs import PUBLIC_SECTIONS
        from rasmai.storage.db import get_connected_account, upsert_connected_account
        from rasmai.web.dashboard.public_profile import public_payload, set_sharing, sharing_payload
        problems = []
        # the stored snapshot keeps rows against a field list, not dicts: building the profile from
        # dict-shaped charts passed every test and crashed on every real account
        from rasmai.bot.state.snapshots import CHART_FIELDS
        rows = [[f"song {i}", "dx", "master", 100.2 - i * 0.01, 300 - i, "13+", 13.7, "FC", "", i < 20, 2900]
                for i in range(60)]
        upsert_connected_account("u1", "intl", "cookie://x",
                                 official_profile={"name": "Nek", "rating": 13551, "totalPlayCount": 574},
                                 snapshot={"fields": list(CHART_FIELDS), "charts": rows, "recordedAt": "2026-09-14T04:00:00"})
        account = get_connected_account("u1")

        if sharing_payload("u1", account)["on"]:
            problems.append("a fresh account is already sharing; the profile must be opt-in")
        state = set_sharing("u1", True, {"best50": True}, account=account)
        slug = state["url"].rsplit("/", 1)[-1]
        if not state["on"] or len(slug) < 16:
            problems.append(f"turning sharing on gave no usable link: {state}")
            return problems

        shown = public_payload(slug)
        if shown is None:
            problems.append("the link does not answer while sharing is on")
            return problems
        if "userId" in shown or "token" in shown or "u1" in str(shown):
            problems.append("the public payload leaks the account behind it")
        for name in PUBLIC_SECTIONS:
            if name != "best50" and name in shown:
                problems.append(f"{name} was never turned on but is on the profile")
        if "best50" not in shown:
            problems.append("best50 was turned on but is missing")
        elif len(shown["best50"]["new"]) != 15 or len(shown["best50"]["old"]) != 35:
            problems.append(f"the pools did not fill from the stored rows: "
                            f"{len(shown['best50']['new'])} new, {len(shown['best50']['old'])} old")
        elif not shown["best50"]["new"][0]["title"]:
            problems.append("the charts came back nameless: the snapshot rows were not read")

        # switching it off has to take effect at once, not at the next link
        account = get_connected_account("u1")
        set_sharing("u1", False, account=account)
        if public_payload(slug) is not None:
            problems.append("the link still answers after sharing was switched off")

        # a fresh link must break the old one
        set_sharing("u1", True, account=get_connected_account("u1"))
        again = set_sharing("u1", True, rotate=True, account=get_connected_account("u1"))
        if public_payload(slug) is not None:
            problems.append("the old link still answers after a new one was issued")
        if public_payload(again["url"].rsplit("/", 1)[-1]) is None:
            problems.append("the new link does not answer")
        return problems
    finally:
        store.DATABASE_PATH = was
        store._database_ready = False


@check("the linking walkthroughs are web sized and small enough for Discord")
def _walkthrough():
    from rasmai.config import WALKTHROUGH_DIR
    # a master dropped in by mistake is both a slow page and an upload Discord refuses
    DISCORD_LIMIT = 8 * 1024 * 1024
    SENSIBLE = 6 * 1024 * 1024
    problems = []
    for clip in ("desktop", "ios-safari"):
        video = WALKTHROUGH_DIR / f"{clip}.mp4"
        poster = WALKTHROUGH_DIR / f"{clip}.jpg"
        if not video.is_file():
            problems.append(f"{video} is missing, so the /login button has nothing to send")
            continue
        size = video.stat().st_size
        if size > DISCORD_LIMIT:
            problems.append(f"{clip}.mp4 is {size / 1048576:.1f} MB, over Discord's {DISCORD_LIMIT / 1048576:.0f} MB limit")
        elif size > SENSIBLE:
            problems.append(f"{clip}.mp4 is {size / 1048576:.1f} MB; transcode it before shipping")
        if not poster.is_file():
            problems.append(f"{poster.name} is missing, so the video box collapses before it loads")
        elif poster.stat().st_mtime < video.stat().st_mtime - 60:
            problems.append(f"{poster.name} is older than {clip}.mp4: the poster is from a previous cut")
    return problems


@check("the developer page answers one account and 404s for everyone else")
def _admin():
    from rasmai.config import ADMIN_USER_ID
    from rasmai.web.dashboard import routes
    from rasmai.web.dashboard.admin import is_admin
    problems = []
    if not ADMIN_USER_ID.isdigit():
        problems.append(f"the admin id should be a Discord snowflake, it is {ADMIN_USER_ID!r}")
    for other in ("", "0", ADMIN_USER_ID + "1", ADMIN_USER_ID[:-1], " " + ADMIN_USER_ID):
        if is_admin(other):
            problems.append(f"{other!r} was let in")
    if not is_admin(ADMIN_USER_ID):
        problems.append("the admin id itself was refused")

    class Fake:
        def __init__(self):
            self.sent = []

        def _send_json(self, status, body):
            self.sent.append((status, body))

    for who in (ADMIN_USER_ID + "9", "1"):
        handler = Fake()
        routes.handle_get(handler, "/internal/me/admin", {}, {"id": who})
        if not handler.sent or handler.sent[0][0] != 404:
            problems.append(f"the route answered {handler.sent} to {who}, expected a 404")
        elif handler.sent[0][1].get("error") != "not_found":
            problems.append(f"the refusal names the page: {handler.sent[0][1]}")

    # the page lists both halves of what the bot reaches, and neither is allowed to throw on the
    # awkward server: no icon, no member count, not sharded, and no record of the bot joining
    import sys, types
    from rasmai.web.dashboard import admin as admin_module
    was = sys.modules.get("rasmai.bot.core")

    class Server:
        def __init__(self, **fields):
            self.__dict__.update(fields)

    joined = types.SimpleNamespace(joined_at=None)
    sys.modules["rasmai.bot.core"] = types.SimpleNamespace(bot=types.SimpleNamespace(guilds=[
        Server(id=1, name="small", icon=None, member_count=None, owner_id=None, me=None, shard_id=None),
        Server(id=2, name="big", icon=None, member_count=900, owner_id=None, me=joined, shard_id=0),
    ]))
    try:
        listed = admin_module.guilds_payload()
    except Exception as error:
        listed = []
        problems.append(f"a server the gateway told us little about broke the list: {type(error).__name__}: {error}")
    finally:
        if was is not None:
            sys.modules["rasmai.bot.core"] = was
        else:
            sys.modules.pop("rasmai.bot.core", None)
    if [g["name"] for g in listed] != ["big", "small"]:
        problems.append(f"servers should be listed biggest first: {[g.get('name') for g in listed]}")
    if listed and listed[1]["members"] != 0:
        problems.append("a server with no member count should read as zero, not None")

    handler = Fake()
    routes.handle_get(handler, "/internal/me/admin", {}, {"id": ADMIN_USER_ID})
    body = handler.sent[0][1] if handler.sent else {}
    for half in ("guilds_list", "accounts_list"):
        if half not in body:
            problems.append(f"the developer page no longer carries {half}")
    return problems


@check("note types become traits measured against what was at stake on them")
def _judgement_traits():
    from rasmai.engine.judgements import JUDGEMENT_CONFIRM_PLAYS, judgement_traits
    clean = {"tap": {"critical": 800, "perfect": 0, "great": 0, "good": 0, "miss": 0},
             "break": {"critical": 40, "perfect": 0, "great": 0, "good": 0, "miss": 0}}

    # 800 taps at one share and 40 breaks at five make 1000 shares, so a share is 0.1%: a dropped
    # break costs five of them plus its slice of the 1% bonus, and a great keeps four fifths of a tap
    BREAK_MISS, TAP_GREAT = 5 * 0.1 + 1.0 / 40, 0.1 / 5

    def play(break_misses=0, tap_greats=0):
        notes = {k: dict(v) for k, v in clean.items()}
        notes["break"]["critical"] -= break_misses
        notes["break"]["miss"] = break_misses
        notes["tap"]["critical"] -= tap_greats
        notes["tap"]["great"] = tap_greats
        # the achievement has to be what those judgements actually cost, or note_losses charges
        # the unexplained remainder to breaks and the test measures its own mistake
        return {"notes": notes, "achievement": 101.0 - break_misses * BREAK_MISS - tap_greats * TAP_GREAT}

    problems = []
    if judgement_traits([play()] * 5):
        problems.append("five plays is too few to name a note type, but traits came back")
    # a player who only ever drops breaks: breaks must read negative and taps positive
    rows = [play(break_misses=2) for _ in range(JUDGEMENT_CONFIRM_PLAYS)]
    traits = {t["label"]: t for t in judgement_traits(rows)}
    if set(traits) != {"tap notes", "break notes"}:
        problems.append(f"expected a trait per note type, got {sorted(traits)}")
        return problems
    if traits["break notes"]["offset"] >= 0:
        problems.append(f"breaks cost every point yet read {traits['break notes']['offset']:+.2f}")
    if traits["tap notes"]["offset"] <= 0:
        problems.append(f"taps were clean yet read {traits['tap notes']['offset']:+.2f}")
    if not traits["break notes"]["verified"]:
        problems.append("25 plays of dropped breaks should be stated, not left as a lean")
    total = sum(t["offset"] for t in traits.values())
    if abs(total) > 0.05:
        problems.append(f"offsets should cancel against the player's own rate, they sum to {total:+.2f}")
    # a break is worth five taps, so losing proportionally to the stake is not a weakness
    even = judgement_traits([play(break_misses=1, tap_greats=100) for _ in range(JUDGEMENT_CONFIRM_PLAYS)])
    if any(t["verified"] or t["leaning"] for t in even):
        problems.append(f"loss spread across the stake should name nobody: {[(t['label'], t['offset']) for t in even]}")
    # a gap too small to state is still a lean; plenty of plays must not make it vanish instead
    small = judgement_traits([play(break_misses=1) for _ in range(JUDGEMENT_CONFIRM_PLAYS * 2)])
    breaks = next(t for t in small if t["label"] == "break notes")
    if not 0.3 <= abs(breaks["offset"]) < 0.5:
        problems.append(f"expected a gap between the lean and stated bars to test with, got {breaks['offset']:+.2f}")
    elif not breaks["leaning"] or breaks["verified"]:
        problems.append(f"{breaks['offset']:+.2f} over {breaks['count']} plays should lean, not disappear")
    return problems


@check("the judgement profile names the note type carrying more than its share of the loss")
def _judgements():
    from rasmai.engine.judgements import judgement_profile
    clean = {"critical": 100, "perfect": 0, "great": 0, "good": 0, "miss": 0}
    # 900 taps clean, 100 breaks with a miss each play: the breaks are a tenth of the notes and nearly all of the loss
    play = {"notes": {"tap": dict(clean, critical=900), "break": dict(clean, critical=98, miss=2)}, "fast": 3, "late": 9}
    play["achievement"] = 101 - 2 * (5 * 100 / 1400 + 1 / 100)
    problems = []
    if judgement_profile([play, play]) is not None:
        problems.append("two plays should not be enough")
    profile = judgement_profile([play, play, play])
    if not profile or profile["weak"] != "break":
        problems.append(f"breaks should be the weak type: {profile and profile['weak']}")
    if profile and profile["lateShare"] != 0.75:
        problems.append(f"late share should be 0.75: {profile['lateShare']}")
    if profile and abs(profile["lostPerPlay"] - (101 - play["achievement"])) > 1e-3:
        problems.append(f"loss per play should match what the plays lost: {profile['lostPerPlay']}")
    return problems


@check("a version the player's region has not had yet is never suggested to them")
def _version_rollover():
    from rasmai.bot.builders.charts import VERSION_NAMES, version_name
    from rasmai.engine.analysis.charts import ChartIndex, ChartRef
    from rasmai.engine.analysis.rating import version_major

    def chart(version, intl):
        return ChartRef(title=f"v{version}", chart_type="std", difficulty="master", constant=13.0,
                        level="13", notes=800, genre="", artist="", cover="", version=version, intl=intl)

    problems = []
    index = ChartIndex("intl")
    index.current_version = 26                      # the player is on CiRCLE PLUS, as international is
    # the chart database tracks the Japanese game, so the next version's charts appear months early
    if index.playable(chart(27, intl=False)):
        problems.append("a chart from a version international has not had yet should not be suggested")
    if not index.playable(chart(26, intl=False)):
        problems.append("the flag lags on the player's own version, so those charts must still be suggested")
    if not index.playable(chart(27, intl=True)):
        problems.append("once the flag says international has it, a newer chart is suggestable")
    if not index.playable(chart(25, intl=True)):
        problems.append("an older chart that international has should be suggested")
    if index.playable(chart(25, intl=False)):
        problems.append("an older chart international never got should stay hidden")

    # the first three digits are the version, and a PLUS shares its major with the version it extends
    if version_major("270") != 27 or version_major("265") != version_major("260"):
        problems.append("version codes should fold a PLUS into the version it extends")
    for code in ("260", "265", "270"):
        if code not in VERSION_NAMES:
            problems.append(f"version {code} has no name")
    named = version_name({"version": "27000"})
    if named != "MAGiCAL":
        problems.append(f"the newest version should be named, not numbered: {named}")
    return problems


def _notice_writes(admin, notice_payload):
    from rasmai.storage.db import site_notice_set
    problems = []
    if not (notice_payload().get("text") and notice_payload().get("id")):
        problems.append("with nothing set the site should still have its built-in banner")

    stored = site_notice_set("  Two   spaces  collapse ", "warning", "https://example.com", by=admin)
    shown = notice_payload()
    if shown.get("text") != "Two spaces collapse" or shown.get("tone") != "warning":
        problems.append(f"the banner should read back as it was set: {shown.get('text')!r} {shown.get('tone')!r}")
    if "setBy" in shown:
        problems.append("the payload names who set the banner, and visitors should not see that")
    if site_notice_set("Two spaces collapse")["id"] != stored["id"]:
        problems.append("the same words should keep their id, so a dismissal is not undone by a re-save")
    if site_notice_set("Different words entirely")["id"] == stored["id"]:
        problems.append("new words should get a new id, so everyone sees the new banner")
    for bad in ("http://insecure", "javascript:alert(1)", "data:text/html,<script>", "https://x.example/\" onmouseover="):
        if site_notice_set("x", "notice", bad)["link"]:
            problems.append(f"a link that is not a plain https address should be dropped: {bad!r}")
    if site_notice_set("x", "purple")["tone"] != "notice":
        problems.append("an unknown tone should fall back rather than reach the page as a class name")
    if len(site_notice_set("A" * 5000)["text"]) > 300:
        problems.append("a banner should not be able to run the length of the page")
    # a right-to-left override can print a link backwards, and a zero-width space hides inside a word
    tricky = "Go to " + chr(0x202E) + "moc.live" + chr(0x202C) + " now" + chr(0x200B) + "please"
    if site_notice_set(tricky)["text"] != "Go to moc.live nowplease":
        problems.append("characters that let text lie about itself should not survive")
    if site_notice_set("one" + chr(10) + "two" + chr(13) + chr(10) + "three")["text"] != "one two three":
        problems.append("a banner is one line, however it was typed")
    # a row the command never wrote, as if the table had been edited by hand or restored from a backup
    from rasmai.storage.db.sources import _clean
    forged = _clean({"text": "x", "tone": "evil", "link": "javascript:alert(1)", "id": "i"})
    if forged["link"] or forged["tone"] != "notice":
        problems.append("a row that never went through the command should still be cleaned when read")

    site_notice_set("")
    if notice_payload().get("text"):
        problems.append("a banner taken down should stay down, not fall back to the built-in one")
    return problems


@check("the site banner is set by one account, in one place, and says only what it was told to")
def _site_notice():
    import discord
    import tempfile, pathlib
    from rasmai.bot.core import bot
    from rasmai.config import ADMIN_USER_ID, CONTROL_GUILD_ID
    from rasmai.storage.db import connection as store
    from rasmai.web.dashboard import notice_payload

    problems = []
    # the command must not be in the global set, or it lands in every server's picker
    if any(command.name == "notice" for command in bot.tree.get_commands()):
        problems.append("/notice is registered globally, so everyone can see it")
    if CONTROL_GUILD_ID and not any(c.name == "notice" for c in bot.tree.get_commands(guild=discord.Object(id=CONTROL_GUILD_ID))):
        problems.append("/notice is not registered in the control guild, so nobody can reach it")

    source = (ROOT / "rasmai" / "bot" / "commands" / "notice.py").read_text(encoding="utf-8")
    if "ADMIN_USER_ID" not in source:
        problems.append("/notice does not check who is running it")
    if not ADMIN_USER_ID:
        problems.append("no admin account is set, so the check would let anyone through")

    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    try:
        problems += _notice_writes(ADMIN_USER_ID, notice_payload)
    finally:
        store.DATABASE_PATH = was
        store._database_ready = False
    return problems


@check("the permutation test can resolve the threshold it is judged against")
def _trait_confirmation():
    import math
    from rasmai.engine.insights import traits as T

    problems = []
    # a permutation p-value can only land on k/(n+1). If the threshold sits below the second step
    # the gate silently becomes "not one shuffle may beat it", and a trait measured over hundreds
    # of charts gets refused on the luck of a single shuffle rather than on the player's data.
    # This was true at 80 shuffles against p <= 0.02, where 1/81 was the only value that passed.
    for name, threshold in (("TRAIT_P", T.TRAIT_P), ("TRAIT_LEAN_P", T.TRAIT_LEAN_P)):
        room = math.floor(threshold * (T.TRAIT_PERMUTATIONS + 1))
        if room < 4:
            problems.append(f"{name} <= {threshold} over {T.TRAIT_PERMUTATIONS} shuffles lets only {room} of them "
                            f"beat a trait: the test cannot resolve its own threshold")
    if T.TRAIT_CONFIRM_CHARTS < T.TRAIT_MIN_CHARTS:
        problems.append("a trait cannot need fewer charts to be confirmed than to be measured at all")
    if T.TRAIT_LEAN_OFFSET >= T.TRAIT_THRESHOLD:
        problems.append("a leaning trait should be a weaker claim than a confirmed one, not a stronger one")
    if T.TRAIT_LEAN_P < T.TRAIT_P:
        problems.append("a leaning trait should be a weaker claim than a confirmed one, not a rarer one")

    # the note types are judged on plays rather than on shuffled tags, but they end up in the same
    # list, and notable() re-checks every row against TRAIT_THRESHOLD. A note type confirmed under a
    # lower bar than that would pass its own gate, fail notable(), and be excluded from leaning() for
    # being confirmed: shown nowhere at all.
    from rasmai.engine import judgements as J
    if J.JUDGEMENT_OFFSET < T.TRAIT_THRESHOLD:
        problems.append(f"a note type confirmed at {J.JUDGEMENT_OFFSET} would vanish from every list, "
                        f"because a confirmed trait is shown only above {T.TRAIT_THRESHOLD}")
    if J.JUDGEMENT_LEAN_OFFSET > J.JUDGEMENT_OFFSET:
        problems.append("a note type should not need a bigger offset to lean than to be confirmed")
    if J.JUDGEMENT_LEAN_PLAYS > J.JUDGEMENT_CONFIRM_PLAYS:
        problems.append("a note type should not need more plays to lean than to be confirmed")

    # every trait row carries the same keys whichever side it came from, or the pages that read
    # both lists have to know which is which
    rows = J.judgement_traits([{"notes": {k: {"critical": 500, "perfect": 0, "great": 0, "good": 0, "miss": 0}
                                          for k in J.KINDS}, "achievement": 100.0} for _ in range(30)])
    for row in rows:
        missing = {"dimension", "label", "offset", "count", "p", "verified", "leaning"} - set(row)
        if missing:
            problems.append(f"a note-type trait is missing {sorted(missing)}, which the trait lists expect")
        break
    return problems


@check("a play page met with a session maimai has closed signs in again rather than failing")
def _stale_session():
    from rasmai.bot.builders.history.lastplay import play_detail
    from rasmai.bot.state.cache import CachedAnalysis
    from rasmai.scraping.scraper import SessionRejected
    import rasmai.bot.builders.history.lastplay as lastplay

    class Analyzer:
        def __init__(self):
            self._official_session = object()      # a session from an earlier read, since closed
            self.recent_songs = []
            self.signed_in = 0
            self.reads = 0

        def fetch_official_player_profile(self, token, region):
            self.signed_in += 1
            self._official_session = object()

        def fetch_playlog_detail(self, idx, region):
            self.reads += 1
            if self.signed_in == 0:
                raise SessionRejected("maimai signed this session out")
            return {"notes": {}, "achievement": 99.0}

    analyzer = Analyzer()
    cached = CachedAnalysis(user_id="1", region="intl", analyzer=analyzer, recommendations=[], value_charts=[])   # type: ignore[arg-type]
    account = {"token": "cookie://x"}
    kept = lastplay.get_connected_account
    lastplay.get_connected_account = lambda user_id: account
    problems = []
    try:
        detail = play_detail(cached, "1,2")
        if not detail:
            problems.append("the retry returned nothing")
        if analyzer.signed_in != 1:
            problems.append(f"signed in {analyzer.signed_in} times, expected exactly one")
        if analyzer.reads != 2:
            problems.append(f"read the page {analyzer.reads} times, expected the failure and the retry")
        analyzer.reads = 0
        play_detail(cached, "1,2")
        if analyzer.reads:
            problems.append("the page was read again instead of being taken from the analysis")
        # a token maimai will not accept is a dead end, not an endless retry
        analyzer.signed_in = 0
        analyzer.fetch_official_player_profile = lambda token, region: (_ for _ in ()).throw(SessionRejected("dead"))
        try:
            play_detail(cached, "3,4")
            problems.append("a dead token should have raised")
        except SessionRejected:
            pass
    except Exception as error:
        problems.append(f"{type(error).__name__}: {error}")
    finally:
        lastplay.get_connected_account = kept
    return problems


def _web_text():
    """Every line of the site that could name an address on the bot."""
    out = []
    for root in (ROOT / "web" / "app", ROOT / "web" / "components", ROOT / "web" / "lib"):
        for path in root.rglob("*.ts*"):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            out.append(path.read_text(encoding="utf-8"))
    return chr(10).join(out)


@check("the website and the bot agree on every address between them")
def _seam_addresses():
    import re
    web = _web_text()
    server = (ROOT / "rasmai" / "web" / "web_server.py").read_text(encoding="utf-8")
    routes = (ROOT / "rasmai" / "web" / "dashboard" / "routes.py").read_text(encoding="utf-8")
    problems = []

    # the dashboard's own reads: the site asks /api/me/<name>, the bot answers /internal/me/<name>,
    # and a rename on one side alone leaves a button that quietly answers 404
    asked = set(re.findall(r"/api/me/([a-z-]+)", web))
    answered = set(re.findall(r'"/internal/me/([a-z-]+)"', routes))
    for name in sorted(asked - answered):
        problems.append(f"the site calls /api/me/{name} and the bot serves no /internal/me/{name}")
    for name in sorted(answered - asked):
        problems.append(f"the bot serves /internal/me/{name} and nothing on the site asks for it")

    # everything else the site proxies, against what the server dispatches, prefixes included
    served = set(re.findall(r'(?:(?:route\.)?path == |startswith\()"(/internal/[a-z/-]*)"', server))
    served |= {path.rstrip("/") for path in served}
    for target in sorted(set(re.findall(r'internal\(\s*[`"](/internal/[a-z-]+)', web))):
        if target == "/internal/me":
            continue
        if target not in served and target + "/" not in served:
            problems.append(f"the site proxies {target} and the bot dispatches no such path")

    # writes are allow-listed on both sides, and a list that drifts is a form that stops working
    allowed = re.search(r"\[((?:\"[a-z/]+\",?\s*)+)\]\.includes\(path\)", web)
    posts = set(re.findall(r'"/internal/me/([a-z/]+)"', routes[routes.index("def handle_post"):]))
    if not allowed:
        problems.append("the site no longer allow-lists which writes under /api/me it will forward")
    else:
        site_posts = set(re.findall(r'"([a-z/]+)"', allowed.group(1)))
        for name in sorted(site_posts - posts):
            problems.append(f"the site forwards a write to /api/me/{name} that the bot does not accept")
        for name in sorted(posts - site_posts):
            problems.append(f"the bot accepts a write at /internal/me/{name} that the site will not forward")
    return problems


@check("the bot's side of the website answers, and refuses anyone without the shared secret")
def _seam_live():
    import json as jsonlib
    import urllib.error
    import urllib.request
    from rasmai.config import ADMIN_USER_ID
    from rasmai.web import web_server

    kept = web_server.INTERNAL_API_SECRET
    web_server.INTERNAL_API_SECRET = "check-only-secret"
    server = web_server.InternalApiServer(host="127.0.0.1", port=0)
    problems = []
    try:
        server.start()
        port = server.httpd.server_address[1]

        def ask(path, secret=True, user=None):
            request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
            if secret:
                request.add_header("X-Rasmai-Internal", "check-only-secret")
            if user is not None:
                request.add_header("X-Rasmai-User", jsonlib.dumps(user))
            try:
                with urllib.request.urlopen(request, timeout=10) as answer:
                    return answer.status, answer.read()
            except urllib.error.HTTPError as error:
                return error.code, error.read()

        # the shared secret is the whole door: nothing behind it may answer without one
        for path in ("/internal/notice", "/internal/servers", "/internal/me", "/internal/me/admin"):
            status, _ = ask(path, secret=False)
            if status != 401:
                problems.append(f"{path} answered {status} with no shared secret, expected 401")

        # the container's health check is deliberately in front of that door
        status, _ = ask("/health", secret=False)
        if status != 200:
            problems.append(f"/health answered {status} without a secret; the container check reads it")

        # the two the site polls for every visitor, signed in or not
        for path in ("/internal/notice", "/internal/servers"):
            status, body = ask(path)
            if status != 200:
                problems.append(f"{path} answered {status}, expected 200")
                continue
            try:
                jsonlib.loads(body)
            except ValueError:
                problems.append(f"{path} did not answer with JSON")

        # a dashboard read with nobody signed in is a refusal, never a stack trace
        status, _ = ask("/internal/me/charts")
        if status not in (401, 404):
            problems.append(f"/internal/me/charts answered {status} with nobody signed in, expected a refusal")

        # the developer page is one account's, and everyone else is told it does not exist
        stranger = ("1" + ADMIN_USER_ID)[:19] if ADMIN_USER_ID.isdigit() else "100000000000000001"
        status, _ = ask("/internal/me/admin", user={"id": stranger})
        if status != 404:
            problems.append(f"/internal/me/admin answered {status} to a stranger, expected 404")
        # a user header that is not a Discord id is not a user, however well formed the JSON is
        status, _ = ask("/internal/me/charts", user={"id": "1"})
        if status != 401:
            problems.append(f"a made-up user id was accepted: /internal/me/charts answered {status}")

        for path in ("/internal/nothing-here", "/nope"):
            status, _ = ask(path)
            if status != 404:
                problems.append(f"{path} answered {status}, expected 404")
    finally:
        server.stop()
        web_server.INTERNAL_API_SECRET = kept
    return problems


@check("a trait names a skill or a pattern, never who charted it")
def _traits_are_skills():
    from rasmai.engine.insights import even, leaning, notable
    from rasmai.engine.insights.tags import NOT_A_SKILL

    # one of each kind, all far enough out and confirmed, so only the dimension decides
    def axis(dimension, label, offset=0.9, **rest):
        row = {"dimension": dimension, "label": label, "offset": offset, "count": 40, "p": 0.001,
               "verified": True, "leaning": False}
        row.update(rest)
        return row

    skills = [axis("pattern", "fast rotations"), axis("judgement", "tap notes"), axis("tempo", "very fast songs"),
              axis("density", "dense charts"), axis("slide", "slide-heavy")]
    not_skills = [axis("designer", "charts by someone"), axis("genre", "POPS"), axis("era", "BUDDiES and newer"),
                  axis("type", "DX charts")]
    problems = []
    for name, chosen in (("notable", notable(skills + not_skills)),
                         ("leaning", leaning([dict(a, verified=False, leaning=True) for a in skills + not_skills])),
                         ("even", even([dict(a, verified=False, leaning=False, offset=0.0) for a in skills + not_skills]))):
        named = {row["dimension"] for row in chosen}
        for dimension in sorted(named & NOT_A_SKILL):
            problems.append(f"{name}() offered a {dimension} trait; a trait should name a skill the player can work on")
        if name != "even" and not named:
            problems.append(f"{name}() dropped the skills along with the rest")
    if "designer" not in NOT_A_SKILL:
        problems.append("who charted a song is not a skill and should never be named as a trait")

    # the site builds the leaning and level lists itself rather than taking them from the bot, so it
    # keeps its own copy of this rule. Two copies of one rule is how the designer traits came back.
    import re
    source = (ROOT / "web" / "components" / "dash" / "Traits.tsx").read_text(encoding="utf-8")
    found = re.search(r"const NOT_A_SKILL = new Set\(\[([^\]]*)\]\)", source)
    if not found:
        problems.append("the site no longer names the dimensions it refuses to call a trait")
    else:
        theirs = set(re.findall(r'"([a-z]+)"', found.group(1)))
        if theirs != NOT_A_SKILL:
            problems.append(f"the site refuses {sorted(theirs)} where the bot refuses {sorted(NOT_A_SKILL)}")
    # the same goes for the numbers the rule is made of. The site kept showing a lean on nine charts
    # after the bot had stopped, because the bar was raised in one copy of the rule and not the other
    from rasmai.engine.insights.traits import TRAIT_CONFIRM_CHARTS, TRAIT_LEAN_OFFSET
    from rasmai.engine.insights.traits import TRAIT_LEAN_P
    for name, ours in (("CONFIRM_CHARTS", TRAIT_CONFIRM_CHARTS), ("LEAN", TRAIT_LEAN_OFFSET),
                       ("LEAN_P", TRAIT_LEAN_P)):
        found = re.search(rf"const {name} = ([0-9.]+);", source)
        if not found:
            problems.append(f"the site no longer keeps a {name} of its own, so the rule cannot be compared")
        elif abs(float(found.group(1)) - float(ours)) > 1e-9:
            problems.append(f"the site uses {name} of {found.group(1)} where the bot uses {ours}")
    lean = [line for line in source.splitlines() if line.strip().startswith("const isLean =")]
    if not lean:
        problems.append("the site no longer says what it counts as leaning")
    elif "CONFIRM_CHARTS" not in lean[0]:
        problems.append("the site shows a lean however few charts are behind it, where the bot does not")

    # the site fills both sides out to a baseline so the tab answers "what should I work on" either
    # way, and every row it adds still has to carry enough charts to mean anything
    watch = [line for line in source.splitlines() if line.strip().startswith("const isWatch =")]
    if not watch:
        problems.append("the site no longer says what it is willing to show beyond what it can claim")
    else:
        if "CONFIRM_CHARTS" not in watch[0]:
            problems.append("the site would fill its lists with traits on too few charts to mean anything")
        if "verified" not in watch[0] or "isLean" not in watch[0]:
            problems.append("the site would show a confirmed or leaning trait twice, once per tier")
    # and the page says how much of its own leaning list chance alone would produce
    if "byChance" not in source:
        problems.append("the site no longer says how many of its leans are what chance produces")
    if not re.search(r"const BASELINE = [1-9]", source):
        problems.append("the site no longer fills both sides out, so one can be empty while the other is not")
    if "t.verified).length" not in source:
        problems.append("the two sides are levelled without keeping every confirmed trait, which can drop one")

    # the curve spreads its dots inside their own constant so a stack of them reads as a stack; more
    # than half a tenth and a dot would sit under a constant the chart does not have
    curve = (ROOT / "web" / "components" / "dash" / "SkillCurve.tsx").read_text(encoding="utf-8")
    spread = re.search(r"const SPREAD = ([0-9.]+)", curve)
    if not spread:
        problems.append("the curve no longer spreads its dots, so a constant's charts draw as one line")
    elif float(spread.group(1)) >= 0.05:
        problems.append(f"a dot may be nudged {spread.group(1)} from its constant, which is into the next one")

    # Windows' Japanese IME does not compose into an input typed as a search box, so a player typing
    # 乱打 into the trait search got nothing. The boxes are plain text with the role that carries the
    # same meaning, and a new one must not go back to the type that breaks.
    boxes = []
    for name in ("Charts", "Lookup", "PatternBrowser", "Picks"):
        text = (ROOT / "web" / "components" / "dash" / f"{name}.tsx").read_text(encoding="utf-8")
        if 'type="search"' in text:
            boxes.append(name)
        if 'className="search' in text and 'role="searchbox"' not in text:
            problems.append(f"the search box in {name}.tsx no longer says it is one, so it is read as a plain field")
    if boxes:
        problems.append(f"{boxes} type a search box as \"search\", which a Japanese IME will not compose into")

    # and the lists it builds have to be built from the filtered set, not the raw axes
    defines = [line for line in source.splitlines() if line.strip().startswith("const all =")]
    if not defines:
        problems.append("the site no longer says where its trait lists come from")
    elif "NOT_A_SKILL" not in defines[0]:
        problems.append("the site builds its trait lists from every axis, rule or no rule")
    return problems


@check("the lookup finds a chart by its artist or its charter, on both the site and the bot")
def _search_by_credit():
    import rasmai.bot.builders.charts.index as charts_index
    from rasmai.bot.builders.charts import search_titles

    problems = []
    # a table of our own, so this proves the same thing on a fresh checkout where the chart
    # database has not been downloaded yet, and proves it the same way every run
    kept = {name: getattr(charts_index, name) for name in
            ("_shared_index", "_titles", "_search", "_search_bones", "_aliases", "_credits")}

    class Stub:
        def values(self):
            return []

    class Chart:
        def __init__(self, title, artist, designer):
            self.title, self.artist, self.designer = title, artist, designer

    # the artist of one is a word inside the other's title, which is what makes the order mean something
    made_up = [Chart("Rotation Study", "Blues", "譜面-100号"),
               Chart("Slow Rotation Blues", "Another Band", "someone else")]

    class Fake(Stub):
        def values(self):
            return made_up

    try:
        charts_index._shared_index = Fake()          # so nothing tries to fetch the real database
        charts_index._titles = [chart.title for chart in made_up]
        charts_index._aliases = {"held": "so the table is not rebuilt mid-check"}
        # the real indexing runs, so dropping a credited field from it fails here too
        charts_index._build_search({}, Fake())

        for typed, what in (("blues", "artist"), ("譜面-100号", "charter")):
            hits = search_titles(typed, limit=5)
            if "Rotation Study" not in hits:
                problems.append(f"searching the {what} {typed!r} did not find the song they are credited on")
        # a name typed in full means that name, above a song that merely contains it in its title
        ranked = search_titles("blues", limit=5)
        if ranked and ranked[0] != "Rotation Study":
            problems.append(f"a credited name typed in full put {ranked[0]!r} first, ahead of what they made")
        # a title still beats a credit: someone typing a song name means the song
        first = (search_titles("Slow Rotation Blues", limit=5) or [""])[0]
        if first != "Slow Rotation Blues":
            problems.append(f"searching an exact title put {first!r} first instead of the song itself")
        # and a name too short to mean one person must not drag half the database in
        if any(len(key) < 4 for key in charts_index._credit_keys("譜面-100号")):
            problems.append("a two or three letter credit key would match almost everything")
    finally:
        for name, value in kept.items():
            setattr(charts_index, name, value)

    # then against the real database, wherever it has been downloaded
    index = charts_index._shared_index
    if index is None or not any(True for _ in index.values()):
        return problems
    from rasmai.web.dashboard.lookup import search_payload
    titles = [chart.title.casefold() for chart in index.values()]

    def credited(field):
        for chart in index.values():
            name = str(getattr(chart, field, "") or "").strip()
            if len(name) >= 5 and name != "-" and not any(name.casefold() in title for title in titles):
                return name
        return ""

    for field, what in (("artist", "artist"), ("designer", "charter")):
        name = credited(field)
        if not name:
            continue
        theirs = {chart.title for chart in index.values() if str(getattr(chart, field, "") or "") == name}
        hits = search_titles(name, limit=20)
        mine = len(theirs & set(hits))
        if not mine:
            problems.append(f"searching the {what} {name!r} found none of the {len(theirs)} songs they are credited on")
        elif mine < min(len(theirs), len(hits)) // 2:
            problems.append(f"searching the {what} {name!r} returned {len(hits)} songs, only {mine} of them theirs")
    name = credited("artist")
    if name and "charters" not in (search_payload(None, name, limit=1) or [{}])[0]:
        problems.append("a search result on the site no longer says who charted the song")
    return problems


@check("a song still behind an unlock is never offered as something to go and play")
def _locked_songs():
    from rasmai.engine.analysis import build_chart_index
    from rasmai.scraping import dxdata

    problems = []
    # the flag has to survive the trip from dxrating, through the stored copy, into the index
    distilled = dxdata.distil({"songs": [{
        "title": "Locked Song", "isLocked": True,
        "sheets": [{"type": "dx", "difficulty": "master", "level": "13", "internalLevelValue": 13.0,
                    "noteCounts": {"tap": 400, "hold": 100, "slide": 80, "touch": 20, "break": 40, "total": 640}}],
    }, {
        "title": "Open Song", "isLocked": False,
        "sheets": [{"type": "dx", "difficulty": "master", "level": "13", "internalLevelValue": 13.0,
                    "noteCounts": {"tap": 400, "hold": 100, "slide": 80, "touch": 20, "break": 40, "total": 640}}],
    }], "versions": []})
    sheets = distilled.get("sheets") or {}
    locked_facts = [key for key, facts in sheets.items() if facts.get("k")]
    if len(locked_facts) != 1 or not locked_facts[0].startswith("lockedsong|"):
        problems.append(f"the locked flag did not survive being stored: {sheets}")

    # the index reads dxrating from the stored copy, so it is handed this one for the moment
    kept = dxdata.cached
    dxdata.cached = lambda: distilled
    try:
        index = build_chart_index({
            "locked song": {"title": "Locked Song", "artist": "x", "dx_lev_mas_i": "13.0", "dx_lev_mas": "13"},
            "open song": {"title": "Open Song", "artist": "x", "dx_lev_mas_i": "13.0", "dx_lev_mas": "13"},
        }, region="intl")
    finally:
        dxdata.cached = kept
    by_title = {chart.title: chart for chart in index.values()}
    if len(by_title) != 2:
        problems.append(f"the two test charts did not both reach the index: {sorted(by_title)}")
    if "Locked Song" in by_title and not by_title["Locked Song"].locked:
        problems.append("a chart dxrating calls locked did not reach the index as locked")
    if "Open Song" in by_title and by_title["Open Song"].locked:
        problems.append("a chart nobody called locked reached the index as locked")

    # and every place that offers a chart the player has not played has to honour it
    for module in ("rasmai/engine/analysis/picks/candidates.py", "rasmai/engine/analysis/unplayed.py",
                   "rasmai/engine/analysis/planning/build.py", "rasmai/bot/builders/charts/pick.py"):
        if "locked" not in (ROOT / module).read_text(encoding="utf-8"):
            problems.append(f"{module} offers unplayed charts without checking whether they are locked")
    return problems


@check("what the chart database says about how someone picks charts")
def _play_habits():
    from rasmai.engine.insights import habits as H
    from rasmai.scraping import dxdata

    class Chart:
        def __init__(self, title, released, notes=700, constant=13.0, difficulty="master"):
            self.title, self.released, self.notes = title, released, notes
            self.constant, self.difficulty, self.chart_type = constant, difficulty, "dx"

    class Index:
        def __init__(self, charts):
            self.charts = charts

        def get(self, key, level=None):
            return self.charts.get(key)

    problems = []
    key = ("old song", "dx", "master")
    index = Index({key: Chart("Old Song", "2020-01-01")})
    plays = [{"songName": "Old Song", "musicType": "dx", "difficulty": "master",
              "playedAt": "2026-01-01 12:00:00"} for _ in range(8)]
    age = H.chart_age(plays, index)
    if round(age.get("medianYears", 0)) != 6:
        problems.append(f"a chart released in 2020 played in 2026 should read about six years old: {age}")
    if age.get("freshShare") != 0.0:
        problems.append(f"none of those plays were on a chart under a year old: {age}")
    if H.chart_age(plays[:3], index):
        problems.append("three plays is not enough to say how someone picks charts")

    # the history is keyed by version name, and those do not sort into the order they came out in:
    # comparing against the wrong end of it reports the re-rate backwards
    stored = {"constants": {"resung|dx|master": {"UNiVERSE": 13.5, "maimaiでらっくす PLUS": 13.0}},
              "versions": [["maimaiでらっくす PLUS", "2020-01-23"], ["UNiVERSE", "2021-09-16"]]}
    kept = dxdata.cached
    dxdata.cached = lambda: stored

    class Song:
        name, chart_type, difficulty_type, accuracy = "Re-sung", "dx", "master", 100.5

    class Pool:
        def __init__(self, keys):
            self.in_pool = set(keys)

    class Best50:
        def __init__(self, keys):
            self.new_pool, self.old_pool = Pool(keys), Pool([])

    try:
        song_key = ("re-sung", "dx", "master")
        moved = H.rerate_effect([Song()], Index({song_key: Chart("Re-sung", "2020-01-23", constant=13.5)}),
                                Best50([song_key]))
        if moved.get("charts") != 1:
            problems.append(f"a re-rated chart in the best 50 should be counted: {moved}")
        if moved.get("rating", 0) <= 0:
            problems.append(f"a constant revised from 13.0 up to 13.5 should have added rating, not taken it: {moved}")
        # a chart nobody re-rated, and one that is re-rated but outside the pools, both count for nothing
        if H.rerate_effect([Song()], Index({song_key: Chart("Re-sung", "2020-01-23", constant=13.5)}), Best50([])):
            problems.append("a chart outside the best 50 changed nothing and should not be counted")
    finally:
        dxdata.cached = kept

    counts = {key: 4}
    struck = H.notes_struck(Index({key: Chart("Old Song", "2020-01-01", notes=700)}), counts)
    if struck.get("notes") != 2800:
        problems.append(f"four clears of a 700-note chart is 2800 notes: {struck}")
    if H.notes_struck(Index({key: Chart("Old Song", "2020-01-01", notes=700)}), {key: -1}):
        problems.append("a chart whose play count is unknown should not be counted as played")
    return problems


@check("a prediction never sits above a score the player has already proved")
def _no_free_improvement():
    from rasmai.engine.analysis import rating
    from rasmai.engine.analysis.profile.model import PlayProfile

    problems = []
    if rating.BEST_HEADROOM > 0.0:
        problems.append(f"the centre is allowed {rating.BEST_HEADROOM} sigmas above the player's own best; "
                        f"measured over real runs, assuming improvement without evidence costs accuracy")

    profile = PlayProfile()
    profile.sample_size = 200
    profile.intercept, profile.slope = 101.0, -0.3
    profile.consistency, profile.run_consistency = 0.8, 0.5
    key = ("a song", "dx", "master")
    curve = profile.expected_for(13.0, "master")

    # someone a little under their curve: the model may lean towards the curve, never past the best.
    # Further under than DROPPED_BEST_GAP is a different case, handled as an abandoned run.
    under = curve - 1.0
    low, _sigma = profile.chart_expectation(key, 13.0, under)
    if low > under + 1e-6:
        problems.append(f"predicted {low:.2f} on a chart whose best is {under:.2f}, above what they have proved")

    # and someone whose best is above their curve keeps it, rather than being dragged back down
    high_best = curve + 2.0
    high, _sigma = profile.chart_expectation(key, 13.0, high_best)
    if high > high_best + 1e-6:
        problems.append(f"predicted {high:.2f} above a proved {high_best:.2f}")
    if high < high_best - 1.5:
        problems.append(f"predicted {high:.2f} well under a proved {high_best:.2f}: a good chart should stay good")

    # a chart with a rising history is still allowed to be lifted, because that improvement is evidence
    profile.history = {key: [curve - 2.0, curve - 1.0, curve]}
    lifted, _sigma = profile.chart_expectation(key, 13.0, curve)
    if lifted <= curve:
        problems.append("a chart the player is measurably improving on should still be allowed to rise")
    return problems


@check("the first track of a credit is only called cold when the plays say so")
def _warm_up():
    import random
    from rasmai.engine.insights import habits as H

    class Chart:
        key = ("a song", "dx", "master")
        title, chart_type, difficulty = "A Song", "dx", "master"
        constant, notes, released, locked = 13.0, 700, "2020-01-01", False

    class Index:
        def get(self, key, level=None):
            return Chart() if key == Chart.key else None

    class Profile:
        def chart_expectation(self, key, constant, best):
            return 99.0, 0.8

    def plays(count, first_offset, seed):
        rng = random.Random(seed)
        out = []
        for i in range(count):
            track = 1 if i % 4 == 0 else (i % 4) + 1
            shift = first_offset if track == 1 else 0.0
            out.append({"chart_key": "a song|dx|master", "track": track,
                        "achievement": 99.0 + shift + rng.gauss(0, 0.4)})
        return out

    index, profile, bests = Index(), Profile(), {}
    problems = []

    # too few plays to ask the question at all, however large the gap looks
    if H.warm_up(plays(40, -1.0, 1), index, profile, bests):
        problems.append("40 plays is not enough to say anything about warming up")

    # plays with nothing in them: the answer has to be silence, not a small number dressed up
    quiet = H.warm_up(plays(400, 0.0, 2), index, profile, bests)
    if quiet:
        problems.append(f"plays with no warm-up effect in them still produced one: {quiet}")

    # and a real gap has to come through, the right way round
    cold = H.warm_up(plays(400, -1.2, 3), index, profile, bests)
    if not cold:
        problems.append("a first track a full point under the rest was not noticed")
    else:
        if not cold.get("colder"):
            problems.append(f"a worse first track should read as playing cold: {cold}")
        if cold.get("gap", 0) > -0.5:
            problems.append(f"the gap should be about a point: {cold}")
        if cold.get("p", 1) > H.WARM_UP_P:
            problems.append(f"a gap that was reported should have cleared the bar: {cold}")

    # the other way round too: someone who starts strong and tires
    warm = H.warm_up(plays(400, +1.2, 4), index, profile, bests)
    if warm and warm.get("colder"):
        problems.append(f"a better first track should not read as playing cold: {warm}")
    return problems


@check("a judgement page read once opens from storage, without asking maimai again")
def _stored_judgements():
    import rasmai.web.dashboard.scores as scores
    from rasmai.bot.state.cache import CachedAnalysis

    stored = {"achievement": 98.5, "fast": 3, "late": 9, "combo": 400, "max_combo": 700, "sync": 0, "max_sync": 0,
              "notes": {"tap": {"critical": 10, "perfect": 5, "great": 1, "good": 0, "miss": 0}}}
    asked = []

    class Analyzer:
        recent_songs = []      # the play has scrolled off the fifty maimai still lists

    kept = scores.judgement_for
    scores.judgement_for = lambda user_id, idx: dict(stored) if idx == "kept" else None
    cached = CachedAnalysis(user_id="1", region="intl", analyzer=Analyzer(), recommendations=[], value_charts=[])   # type: ignore[arg-type]
    problems = []
    try:
        import rasmai.bot.builders.history as history
        held = history.play_detail
        history.play_detail = lambda c, idx: asked.append(idx) or dict(stored)
        try:
            page = scores.play_payload(cached, "kept")
            if page is None:
                problems.append("a stored page did not open once the site stopped listing the play")
            elif not page.get("lost"):
                problems.append("a stored page opened without what each note type cost")
            if asked:
                problems.append(f"maimai was asked for a page already stored: {asked}")
            if scores.play_payload(cached, "never") is not None:
                problems.append("a play with nothing stored and nothing listed should not open")
        finally:
            history.play_detail = held
    finally:
        scores.judgement_for = kept
    return problems


@check("a measured trait names what a chart asks for, never what it happens to be short of")
def _bands():
    from rasmai.engine.analysis import ChartRef
    from rasmai.engine.insights.tags import chart_traits
    from rasmai.scraping.mai_notes import note_traits

    problems = []
    # a chart light in every note type asks nothing of the hands for any of them, so it is named for none
    if note_traits({"n": 1000, "t": 940, "h": 20, "s": 20, "u": 10, "b": 10}):
        problems.append(f"a chart light in every note type was still given traits: {note_traits({'n': 1000, 't': 940, 'h': 20, 's': 20, 'u': 10, 'b': 10})}")
    heavy = dict(note_traits({"n": 1000, "t": 700, "h": 40, "s": 200, "u": 30, "b": 30}))
    if heavy.get("slide") != "slide-heavy" or len(heavy) != 1:
        problems.append(f"a slide-heavy chart was read as {heavy}")
    # and a chart in the middle of the game's tempo and note count is in no band at all: a band holding
    # the bulk of the game sits on the player's own average and can never say anything
    middle = [trait for trait in chart_traits(ChartRef(title="middling", chart_type="dx", difficulty="master", constant=13.0,
                                                      level="13", notes=750, genre="", artist="", cover="", version=26, bpm=170.0))
              if trait[0] in ("tempo", "density")]
    if middle:
        problems.append(f"a middle-of-the-road chart landed in a tempo or density band: {middle}")
    return problems


@check("a chart in simai is read the way maimai counts it")
def _simai_parse():
    from rasmai.engine.simai import parse

    problems = []
    # one of each thing the notation can say, at 120 BPM where a {4} comma is half a second:
    # a tap, a hold of one beat, a slide off a star, a break, a touch, and two struck together
    chart = parse("(120){4}1,2h[4:1],3-5[8:1],4b,C,{8}6/7,E")
    counts = chart.counts()
    # the star of a slide is played as a tap, so 1, the star of 3-5, 6 and 7 are four taps
    want = {"tap": 4, "hold": 1, "slide": 1, "touch": 1, "break": 1}
    if counts != want:
        problems.append(f"the sampler chart read as {counts}, expected {want}")
    if len(chart.notes) != 8:
        problems.append(f"the sampler chart has 8 notes, read as {len(chart.notes)}")
    held = [n for n in chart.notes if n.kind == "hold"]
    if held and abs(held[0].duration - 0.5) > 1e-6:
        problems.append(f"a one-beat hold at 120 BPM lasts half a second, read as {held[0].duration}")
    together = [n for n in chart.notes if n.each > 1]
    if len(together) != 2:
        problems.append(f"6/7 is two notes struck together, read as {len(together)}")

    # a slide written through several corners is judged once, so it is one note and not one each
    chained = parse("(120){4}1-4-7[8:1],E").counts()
    if chained != {"tap": 1, "hold": 0, "slide": 1, "touch": 0, "break": 0}:
        problems.append(f"a chained slide read as {chained}, expected one star and one slide")

    # a break mark after the length belongs to the slide, not to the star that fired it
    broken = parse("(120){4}1-5[8:1]b,E").counts()
    if broken != {"tap": 1, "hold": 0, "slide": 0, "touch": 0, "break": 1}:
        problems.append(f"a break slide read as {broken}, expected a plain star and a break slide")

    # a length written as a wait then a travel, which one chart in the game actually uses
    waited = parse("(120){4}1-5[0.375##1.9821],E")
    travel = [n for n in waited.notes if n.kind == "slide"]
    if not travel or abs(travel[0].duration - 1.9821) > 1e-6:
        problems.append(f"a slide that waits before it moves should travel for 1.9821s, read as {travel}")
    return problems


@check("a chart is refused only when the reader could not follow it, and disagreement is recorded")
def _simai_trust():
    from rasmai.engine.simai import parse
    from rasmai.scraping import simai

    good = "(120){4}1,2h[4:1],3-5[8:1],4b,C,{8}6/7,E"
    agrees = {"t": 4, "h": 1, "s": 1, "u": 1, "b": 1, "n": 8, "l": 13.0}
    problems = []
    reading = simai.read_chart(good, agrees)
    if reading is None:
        problems.append("a chart the reader followed from end to end was refused")
    elif reading.get("off") != 0.0:
        problems.append(f"a reading that matches its source was recorded as {reading.get('off')!r} away from it")

    # the counts come from a wiki rather than from the file, so the two differ on a chart now and
    # then. That is worth recording and is not grounds for throwing the reading away.
    apart = simai.read_chart(good, {**agrees, "n": 10})
    if apart is None:
        problems.append("a reading was thrown away because its source counted the chart differently")
    elif abs(float(apart.get("off") or 0) + 0.2) > 1e-6:
        problems.append(f"eight notes against a published ten is -0.2, recorded as {apart.get('off')!r}")

    # what is refused: notation the reader could not follow at all
    if not parse("(120){4}1,~~~,2,E").skipped:
        problems.append("notation the reader does not know went unnoticed")
    if simai.read_chart("(120){4}1,~~~,2,E", agrees) is not None:
        problems.append("a chart holding notation the reader could not follow was used anyway")
    if simai.read_chart("", agrees) is not None:
        problems.append("an empty chart was read as though it held something")
    if parse(good).skipped:
        problems.append("a chart made only of ordinary notation was reported as unreadable")

    held = {"a": {"off": 0.001}, "b": {"off": 0.05}, "c": {"off": -0.3}, "d": {}}
    if simai.disputed(held) != 2:
        problems.append(f"two of those readings sit far from their source, counted {simai.disputed(held)}")

    # a served file sometimes carries the next difficulty after the one that was asked for. Read
    # straight through, the two count as one chart: a 954-note Master read as 1,549 that way.
    from rasmai.engine.simai.parse import sections
    both = "(120){4}1,2,3,4,E&inote_5=(120){4}1,2,E"
    if len(sections(both)) != 2:
        problems.append(f"a file holding two charts was read as {len(sections(both))}")
    if len(parse(both).notes) != 4:
        problems.append(f"reading a two-chart file straight through made {len(parse(both).notes)} notes of the first four")
    four = {"t": 4, "h": 0, "s": 0, "u": 0, "b": 0, "n": 4, "l": 13.0}
    two = {**four, "n": 2}
    for wanted, label in ((four, "four"), (two, "two")):
        picked = simai.read_chart(both, wanted)
        # a zero here is the answer, not a missing one, so it is read with a default rather than "or"
        if picked is None or abs(float(picked.get("off", 1.0))) > 1e-9:
            problems.append(f"the {label}-note chart in a two-chart file was not the one picked")
    return problems


@check("reading the charts themselves is off until its owner turns it on")
def _simai_beta():
    import pathlib
    import tempfile

    from rasmai.engine.analysis import ChartRef
    from rasmai.engine.insights.tags import chart_traits
    from rasmai.storage.db import connection as store
    from rasmai.web.dashboard.beta import FEATURES, beta_state, set_beta, wants

    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    problems = []
    user = "beta-check-user"
    if wants(user, "simai"):
        problems.append("a feature nobody switched on was reported as on")
    state = beta_state(user)
    if set(state["on"]) != set(FEATURES) or any(state["on"].values()):
        problems.append(f"a fresh account should have every beta off, got {state['on']}")
    if set_beta(user, {"simai": True})["on"].get("simai") is not True:
        problems.append("switching a beta on did not take")
    if not wants(user, "simai"):
        problems.append("a beta switched on was not seen as on")
    if set_beta(user, {"nonsense": True})["on"].get("nonsense") is not None:
        problems.append("a feature that does not exist was stored anyway")
    set_beta(user, {"simai": False})
    if wants(user, "simai"):
        problems.append("switching a beta off did not take")

    # and with it off, nothing measured from the notes reaches the model
    chart = ChartRef(title="anything", chart_type="dx", difficulty="master", constant=13.0, level="13",
                     notes=800, genre="", artist="", cover="", version=26, bpm=170.0)
    from rasmai.engine.simai import DEMANDS
    named = {demand[2] for demand in DEMANDS}
    if {label for _dimension, label in chart_traits(chart, False)} & named:
        problems.append("a trait read from the notes appeared for someone who never asked for it")

    # the numbers the progress bar is drawn from have to add up, or it shows a wrong time left
    from rasmai.scraping import simai
    from rasmai.web.dashboard.beta import _simai_status
    held_cached, held_pending, held_pace = simai.cached, simai._pending, simai.pace
    try:
        # sixty read, ten that could not be trusted, and nine hundred still to go at two a second
        rows = {f"c{n}|dx|master": ({"spins": 0.1, "lv": 13.0} if n < 60 else {}) for n in range(70)}
        simai.cached = lambda: (rows, {"spins": 0.01})
        simai._pending = lambda known: [None] * 900
        simai.pace = lambda: 2.0
        state = _simai_status()
        want = {"done": 70, "total": 970, "read": 60, "waiting": 900, "eta": 450, "ready": True}
        for field, value in want.items():
            if state.get(field) != value:
                problems.append(f"the progress bar would read {field}={state.get(field)!r}, expected {value!r}")
        if abs(float(state["percent"]) - 7.2) > 0.05:
            problems.append(f"70 of 970 charts is 7.2 per cent, shown as {state['percent']}")
        simai.pace = lambda: 0.0
        if _simai_status()["eta"] != 0:
            problems.append("a time left was given before the pace had been measured")
    finally:
        simai.cached, simai._pending, simai.pace = held_cached, held_pending, held_pace
    store.DATABASE_PATH = was
    store._database_ready = False
    return problems


@check("a chart crawl against a site that has stopped answering gives up instead of going round again")
def _simai_down():
    import pathlib
    import tempfile

    from rasmai.storage.db import connection as store
    from rasmai.scraping import simai

    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    asked = []

    def dead(chart_id):
        asked.append(chart_id)
        return None

    pending = [(f"song {n}|dx|master", f"id{n}", {"t": 1, "h": 0, "s": 0, "u": 0, "b": 0, "n": 1}) for n in range(50)]
    held_fetch, held_pending, held_pause = simai.fetch_chart, simai._pending, simai.PAUSE
    simai.fetch_chart, simai._pending, simai.PAUSE = dead, lambda known: pending, 0.0
    problems = []
    try:
        out = simai.refresh(40)
        if len(asked) > simai.MISSES:
            problems.append(f"a dead site was asked {len(asked)} times, expected to stop after {simai.MISSES}")
        if out:
            problems.append("a run that read nothing reported work done, so the caller would run it again")
    finally:
        simai.fetch_chart, simai._pending, simai.PAUSE = held_fetch, held_pending, held_pause
        store.DATABASE_PATH = was
        store._database_ready = False
    return problems


@check("a weakness that only the charts' own notes can see is found, and only when asked for")
def _simai_model():
    import random

    from rasmai.engine.analysis import ChartIndex, ChartRef, build_play_profile, calculate_rating
    from rasmai.scraping import simai
    from rasmai.storage.models import SongInfo

    # a hundred charts, a third of them walking you round the ring, and a player who drops a point on exactly those.
    # Nothing else marks those charts out, so a trait can only find this by reading the notes.
    measured, index, songs = {}, ChartIndex(), []
    random.seed(5)
    spun = 0
    for n in range(120):
        circles = 0.05 if n % 3 == 0 else 0.0
        spun += bool(circles)
        key = f"chart {n}|dx|master"
        measured[key] = {"circles": circles, "lv": 13.0}
        index.add(ChartRef(title=f"chart {n}", chart_type="dx", difficulty="master", constant=13.0,
                           level="13", notes=700, genre="", artist="", cover="", version=25, bpm=170.0))
        accuracy = round(99.2 - (1.0 if circles else 0.0) + random.uniform(-0.15, 0.15), 4)
        songs.append(SongInfo(name=f"chart {n}", chart_type="dx", difficulty_type="master", accuracy=accuracy,
                              is_new=False, level="13", difficulty=13.0, rating=calculate_rating(13.0, accuracy)))

    held = simai.cached
    simai.cached = lambda: (measured, {"circles": 0.01})
    problems = []
    try:
        off = build_play_profile(songs, [], index, 26, reading=False)
        if any(axis["label"] == "spinning round the ring" for axis in off.trait_axes):
            problems.append("a trait from the notes was measured for a player who never switched it on")
        on = build_play_profile(songs, [], index, 26, reading=True)
        found = next((a for a in on.trait_axes if a["label"] == "spinning round the ring"), None)
        if found is None:
            problems.append(f"the weakness planted on {spun} charts was not measured at all")
        elif found["offset"] > -0.3:
            problems.append(f"a point lost on every spin chart came out as {found['offset']:+.2f}, which is not it")
        elif not found["verified"]:
            problems.append(f"a weakness this plain should pass its own gate, got p={found['p']}")
    finally:
        simai.cached = held
    return problems


@check("a chart table kept in an older shape is re-read rather than trusted for good")
def _stale_manifest():
    import json
    import pathlib
    import tempfile

    from rasmai.scraping import mai_notes, simai
    from rasmai.storage.db import connection as store

    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    held_fetch = mai_notes.fetch
    problems = []
    try:
        from rasmai.storage.db import source_state_get, source_state_set
        fresh = {"a song|dx|master": {"n": 1, "t": 1, "h": 0, "s": 0, "u": 0, "b": 0, "c": "abc", "l": 13.0}}
        asked = []

        def answer(etag=""):
            # the site only sends a body when it is not asked conditionally, which is the whole point:
            # a stored copy in the wrong shape has to drop its tag or it will be told nothing changed
            asked.append(etag)
            return ("unchanged", None, etag) if etag else ("changed", dict(fresh), "tag-1")

        mai_notes.fetch = answer

        # what a bot running older code left behind: the right charts, without the fields added since
        stale = {key: {f: v for f, v in row.items() if f not in ("c", "l")} for key, row in fresh.items()}
        source_state_set(mai_notes.SOURCE, etag="tag-1",
                         payload=json.dumps(stale, ensure_ascii=False, separators=(",", ":")))
        mai_notes._forget()

        if simai._pending({}):
            problems.append("a chart with no id was queued for reading anyway")
        charts = mai_notes.refresh_charts()
        if not charts or not next(iter(charts.values())).get("c"):
            problems.append("a stored copy in the old shape was handed back instead of being read again")
        if asked and asked[0]:
            problems.append(f"the old copy was re-read conditionally ({asked[0]!r}), so the site would answer 304 and change nothing")
        held = json.loads(source_state_get(mai_notes.SOURCE)["payload"])
        if held.get("v") != mai_notes.FORMAT:
            problems.append(f"the re-read copy was stored without its shape, as {held.get('v')!r}")
        if not simai._pending({}):
            problems.append("nothing was queued for reading even after the chart table came back with ids")
    finally:
        mai_notes.fetch = held_fetch
        mai_notes._forget()
        store.DATABASE_PATH = was
        store._database_ready = False
    return problems


@check("a change to what is measured is answered from the charts already held, not another crawl")
def _simai_remeasure():
    import json
    import pathlib
    import tempfile

    from rasmai.engine.simai import features as measures
    from rasmai.scraping import mai_notes, simai
    from rasmai.storage.db import connection as store

    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    held_fetch, held_pause, held_version = simai.fetch_chart, simai.PAUSE, simai.VERSION
    problems = []
    try:
        from rasmai.storage.db import sheets_held, source_state_set
        sheet = "(120){4}1,2h[4:1],3-5[8:1],4b,C,{8}6/7,E"
        rows = {f"song {n}|dx|master": {"t": 4, "h": 1, "s": 1, "u": 1, "b": 1, "n": 8, "l": 13.0, "c": f"id{n}"}
                for n in range(12)}
        source_state_set(mai_notes.SOURCE, etag="x",
                         payload=json.dumps({"v": mai_notes.FORMAT, "rows": rows}, separators=(",", ":")))
        mai_notes._forget()
        simai.fetch_chart = lambda chart_id: sheet
        simai.PAUSE = 0.0
        simai.refresh(12)
        if sheets_held()["charts"] != 12:
            problems.append(f"the notation was not kept: {sheets_held()}")

        # the measures now mean something else, so every reading taken under the old ones is dropped
        simai.VERSION = measures.VERSION + 1
        simai._forget()
        if simai._stored():
            problems.append("readings taken under older measures were kept anyway")
        asked = []
        simai.fetch_chart = lambda chart_id: asked.append(chart_id)
        again = simai.remeasure()
        if asked:
            problems.append(f"the site was asked for {len(asked)} charts it had already given us")
        if again != 12:
            problems.append(f"{again} charts were measured again, expected 12")
        if sum(1 for row in simai._stored().values() if row) != 12:
            problems.append("the charts were measured again but the readings did not come back")
    finally:
        simai.fetch_chart, simai.PAUSE, simai.VERSION = held_fetch, held_pause, held_version
        simai._forget()
        mai_notes._forget()
        store.DATABASE_PATH = was
        store._database_ready = False
    return problems


@check("traits read from the charts are searchable, and only for whoever switched that on")
def _read_tags_searchable():
    from rasmai.engine import patterns
    from rasmai.engine.analysis import ChartIndex, ChartRef
    from rasmai.engine.insights import chart_tags
    from rasmai.scraping import simai

    index = ChartIndex()
    measured = {}
    for n in range(30):
        ref = ChartRef(title=f"chart {n}", chart_type="dx", difficulty="master", constant=13.0, level="13",
                       notes=700, genre="", artist="", cover="", version=25, bpm=170.0)
        index.add(ref)
        measured["|".join(ref.key)] = {"circles": 0.1 if n % 3 == 0 else 0.0, "lv": 13.0}

    held = simai.cached
    simai.cached = lambda: (measured, {"circles": 0.01})
    patterns._catalogue_memo.clear()
    problems = []
    try:
        spun = index.get(("chart 0", "dx", "master"))
        quiet = index.get(("chart 1", "dx", "master"))

        off = {tag["label"] for tag in chart_tags(spun, False)}
        on = {tag["label"] for tag in chart_tags(spun, True)}
        if "spinning round the ring" in off:
            problems.append("a trait read from the chart was shown to someone who never switched it on")
        if "spinning round the ring" not in on:
            problems.append("a chart that walks you round the ring was not tagged as one with the feature on")
        if "spinning round the ring" in {tag["label"] for tag in chart_tags(quiet, True)}:
            problems.append("a chart that stays put was tagged as walking you round the ring")
        if not any(tag.get("read") for tag in chart_tags(spun, True)):
            problems.append("a trait read from the chart was not marked as read rather than written by hand")

        # the catalogue, and searching it
        patterns._catalogue_memo.clear()
        if any(item["label"] == "spinning round the ring" for item in patterns.catalogue(index, False)):
            problems.append("a trait read from the charts was listed for someone who never switched it on")
        patterns._catalogue_memo.clear()
        if not any(item["label"] == "spinning round the ring" for item in patterns.catalogue(index, True)):
            problems.append("a trait read from the charts was missing from the list to search")
        patterns._catalogue_memo.clear()
        if patterns.resolve("spinning round", index, False) is not None:
            problems.append("searching found a trait the searcher had not switched on")
        patterns._catalogue_memo.clear()
        found = patterns.resolve("spinning round", index, True)
        if found != "spinning round the ring":
            problems.append(f"searching for the walk round the ring found {found!r}")
        else:
            charts = patterns.charts_with(index, found, reading=True)
            if len(charts) != 10:
                problems.append(f"ten of the thirty charts walk you round the ring, search returned {len(charts)}")
            if patterns.charts_with(index, found, reading=False):
                problems.append("charts came back for a trait the searcher had not switched on")
    finally:
        simai.cached = held
        patterns._catalogue_memo.clear()
    return problems


@check("not hunting critical breaks is not a weakness, but dropping breaks still is")
def _break_bonus():
    from rasmai.engine.judgements import judgement_profile, judgement_traits
    from rasmai.engine.losses import WEIGHTS, note_losses

    kept = {"critical": 1.0, "perfect": 0.5, "great": 0.4, "good": 0.3, "miss": 0.0}

    def play(great=0, good=0, miss=0, criticals=0.35):
        """One play, the same everywhere except on the breaks, scored the way maimai would."""
        notes = {}
        for kind, n in (("tap", 700), ("hold", 40), ("slide", 60), ("touch", 20)):
            g, b, m = round(n * 0.012), round(n * 0.002), round(n * 0.001)
            notes[kind] = {"critical": n - g - b - m, "perfect": 0, "great": g, "good": b, "miss": m}
        breaks = 30
        landed = breaks - great - good - miss
        crit = round(landed * criticals)
        notes["break"] = {"critical": crit, "perfect": landed - crit, "great": great, "good": good, "miss": miss}
        total = sum(WEIGHTS[k] * sum(v.values()) for k, v in notes.items())
        base = 100.0 / total
        lost = sum(row["good"] * 3 * base + row["miss"] * 5 * base if kind == "break"
                   else WEIGHTS[kind] * base * (row["great"] / 5 + row["good"] / 2 + row["miss"])
                   for kind, row in notes.items())
        lost += sum(count * (1 - kept[judged]) / breaks for judged, count in notes["break"].items())
        return {"notes": notes, "achievement": round(101.0 - lost, 4), "fast": 8, "late": 9}

    def breaks_of(rows):
        return next((t["offset"] for t in judgement_traits(rows) if t["label"] == "break notes"), None)

    problems = []
    # every break landed; they are simply perfect rather than critical, which is how the game is
    # played by anyone not chasing the bonus. This must not read as a weakness.
    ordinary = [play() for _ in range(40)]
    offset = breaks_of(ordinary)
    if offset is None:
        problems.append("breaks were not measured at all")
    elif offset < -0.2:
        problems.append(f"landing every break but not as a critical was called a weakness at {offset:+.2f}")
    if judgement_profile(ordinary)["weak"] == "break":
        problems.append("the panel named breaks the worst type for a player who did not drop one")

    # and with no critical at all, which is the same player and a lower score
    none_critical = [play(criticals=0.0) for _ in range(40)]
    offset = breaks_of(none_critical)
    if offset is not None and offset < -0.2:
        problems.append(f"never earning a critical break was called a weakness at {offset:+.2f}")
    profile = judgement_profile(none_critical)
    if profile["bonusPerPlay"] <= 0:
        problems.append("the bonus a critical earns was not reported as its own loss")
    if profile["bonus"] <= 0 or profile["bonusShare"] <= 0:
        problems.append("the bonus was measured at nothing when every break was a plain perfect")

    # dropping breaks is still a weakness, and has to be found
    dropped = [play(great=3, good=2, miss=1) for _ in range(40)]
    offset = breaks_of(dropped)
    if offset is None or offset > -0.4:
        problems.append(f"a player dropping breaks every play was measured at {offset}")
    if judgement_profile(dropped)["weak"] != "break":
        problems.append("the panel did not name breaks for a player dropping them every play")

    # and the bonus is only told apart when it is asked for
    counts = ordinary[0]["notes"]
    together = note_losses(counts, ordinary[0]["achievement"])
    apart = note_losses(counts, ordinary[0]["achievement"], bonus_apart=True)
    if "bonus" in together:
        problems.append("the bonus was split out without being asked for, which changes what callers see")
    if abs(sum(together.values()) - sum(apart.values())) > 1e-6:
        problems.append("splitting the bonus out changed how much the play cost in total")
    if apart.get("break", 0) > together.get("break", 0):
        problems.append("taking the bonus off the breaks made them cost more")
    return problems


@check("every trait belongs to a family, and a family follows the charts behind it")
def _families():
    from rasmai.engine.insights import family_axes, unclaimed
    from rasmai.engine.insights.families import FAMILY_MIN_CHARTS
    from rasmai.engine.judgements import KINDS
    from rasmai.engine.simai import DEMANDS
    from rasmai.scraping.mai_notes import PATTERN_ENGLISH, SHARE_BANDS, pattern_label

    # everything the model can currently name, from the places the names come from
    vocabulary = [{"dimension": "pattern", "label": pattern_label(tag)} for tag in PATTERN_ENGLISH]
    vocabulary += [{"dimension": dimension, "label": label} for _f, dimension, _hi, label in SHARE_BANDS]
    vocabulary += [{"dimension": dimension, "label": label} for _k, dimension, label, _fixed in DEMANDS]
    vocabulary += [{"dimension": "judgement", "label": f"{kind} notes"} for kind in KINDS]
    vocabulary += [{"dimension": "tempo", "label": "slow songs (under 130 BPM)"},
                   {"dimension": "tempo", "label": "very fast (over 210 BPM)"},
                   {"dimension": "density", "label": "light charts (under 620 notes)"},
                   {"dimension": "density", "label": "a lot of notes (890+)"}]
    problems = []
    orphans = unclaimed(vocabulary)
    if orphans:
        problems.append(f"no family takes {len(orphans)} of the traits the model can name: {orphans[:4]}")

    # a family follows the charts behind it, so a tag measured on a handful cannot swing it
    axes = [
        {"dimension": "pattern", "label": "乱打 (streams)", "offset": -1.0, "count": 10, "plays": 2, "verified": False},
        {"dimension": "density", "label": "a lot of notes (890+)", "offset": 0.0, "count": 90, "plays": 30,
         "verified": True},
    ]
    families = {f["key"]: f for f in family_axes(axes)}
    speed = families.get("speed")
    if speed is None:
        problems.append("a family with a hundred charts behind it was not drawn")
    else:
        want = round((-1.0 * 10 + 0.0 * 90) / 100, 2)
        if abs(speed["offset"] - want) > 1e-9:
            problems.append(f"ten charts saying -1.0 and ninety saying 0.0 is {want}, got {speed['offset']}")
        if speed["charts"] != 100 or speed["traits"] != 2:
            problems.append(f"the family should carry both traits and a hundred charts, got {speed['charts']}")
        if len(speed["inside"]) != 2:
            problems.append("a family did not carry the traits underneath it, so it cannot be opened up")
        # the confirmed trait sits at 0.0 and the family leans negative, so nothing confirms that lean
        if speed["verified"]:
            problems.append("a family was called confirmed when nothing under it confirms the way it leans")

    # too little behind it and it is not drawn at all
    thin = family_axes([{"dimension": "pattern", "label": "乱打 (streams)", "offset": -1.0,
                         "count": FAMILY_MIN_CHARTS - 1, "plays": 1, "verified": False}])
    if thin:
        problems.append(f"a family with {FAMILY_MIN_CHARTS - 1} charts behind it was drawn anyway")

    # what a chart is is never a skill, so it never reaches a family
    if family_axes([{"dimension": "genre", "label": "POPS＆アニメ", "offset": -1.0, "count": 200, "plays": 9}]):
        problems.append("a genre was rolled into a family, which is not a thing to practise")

    # what a note type costs is measured against the player's own rate, so the five of them sum to
    # zero: averaged into a family they say nothing at all, and they are counted in plays where the
    # rest are counted in charts. They belong in their own panel, not in a family.
    judged = [{"dimension": "judgement", "label": f"{kind} notes", "offset": off, "count": 50, "plays": 50}
              for kind, off in (("break", -0.86), ("tap", 0.26), ("hold", 0.27), ("slide", 0.27), ("touch", 0.05))]
    if abs(sum(t["offset"] for t in judged)) > 0.02:
        problems.append("these offsets no longer sum to zero, so the reasoning below needs revisiting")
    if family_axes(judged):
        problems.append("what a note type costs was rolled into a family, where its sign cannot survive")
    if unclaimed(judged):
        problems.append(f"note types were reported as having no family, when they are meant to have none: {unclaimed(judged)}")
    return problems


@check("a trait read from the charts can name charts to practise it on")
def _read_traits_practice():
    from rasmai.engine.analysis import ChartIndex, ChartRef, build_play_profile, calculate_rating
    from rasmai.engine.insights.traits import practice_for
    from rasmai.scraping import simai
    from rasmai.storage.models import SongInfo

    index, measured, songs = ChartIndex(), {}, []
    for n in range(40):
        ref = ChartRef(title=f"chart {n}", chart_type="dx", difficulty="master", constant=13.0, level="13",
                       notes=700, genre="", artist="", cover="", version=25, bpm=170.0)
        index.add(ref)
        measured["|".join(ref.key)] = {"circles": 0.1 if n % 2 == 0 else 0.0, "lv": 13.0}
        accuracy = 99.0 if n % 2 else 99.5
        songs.append(SongInfo(name=f"chart {n}", chart_type="dx", difficulty_type="master", accuracy=accuracy,
                              is_new=False, level="13", difficulty=13.0, rating=calculate_rating(13.0, accuracy)))
    held = simai.cached
    simai.cached = lambda: (measured, {"circles": 0.01})
    problems = []
    try:
        profile = build_play_profile(songs, [], index, 26, reading=True)
        axis = next((a for a in profile.trait_axes if a["label"] == "spinning round the ring"), None)
        if axis is None:
            problems.append("the trait was not measured, so there was nothing to practise")
        else:
            picks = practice_for(axis, index, profile, songs, limit=3)
            if not picks:
                problems.append("a trait read from the charts named no charts to practise it on")
            elif not all("spin" in "".join(str(v) for v in p.values()) or p["title"].startswith("chart") for p in picks):
                problems.append(f"the charts named do not carry the trait: {picks}")
        # a note type measured off the judgement pages is not a property of any chart, so it names none
        judged = {"dimension": "judgement", "label": "break notes", "offset": -1.0, "count": 30}
        if practice_for(judged, index, profile, songs):
            problems.append("charts were named for a trait that is about the hands, not about any chart")
    finally:
        simai.cached = held
    return problems


@check("the site tells a browser to refuse http for a year, and nothing it serves needs http")
def _hsts():
    import re

    config = (ROOT / "web" / "next.config.ts").read_text(encoding="utf-8")
    problems = []
    found = re.search(r'max-age=(\d+)([^"]*)', config)
    if not found:
        problems.append("the site does not tell a browser to stay on https at all")
        return problems
    months = int(found.group(1)) / (30 * 24 * 60 * 60)
    if not 11.5 <= months <= 12.5:
        problems.append(f"the browser is told to stay on https for {months:.1f} months, not twelve")
    if "includeSubDomains" not in found.group(2):
        problems.append("the subdomains are left out, so one of them could still be served over http")
    if "Strict-Transport-Security" not in config:
        problems.append("the max-age is written somewhere that is not the header that carries it")
    # a page that asks for anything over http breaks outright once the browser refuses http
    if "upgrade-insecure-requests" not in config:
        problems.append("anything still written as http would be blocked rather than fetched over https")
    # and none of it may be sent while the site itself is being served over http, or a browser
    # pins a development machine to https for a year
    if "secure ?" not in config:
        problems.append("the header is sent even when the site is not on https, which pins a dev box for a year")
    return problems


@check("the charts come out of one clone of the repository, and the site is only asked for the rest")
def _simai_bulk():
    import pathlib
    import tempfile
    import types

    from rasmai.scraping import mai_notes, simai_bulk
    from rasmai.storage.db import connection as store

    # one maidata file carries a whole song: every difficulty under its own &inote_N=
    song = """&title=Test Song[DX]
&wholebpm=120
&cabinet=DX

&inote_2=
(120){4}1,2,3,4,E

&inote_5=
(120){8}1,2,3,4,5,6,7,8,E
"""
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "genre" / "1_test_DX").mkdir(parents=True)
    (root / "genre" / "1_test_DX" / "maidata.txt").write_text(song, encoding="utf-8")
    was_checkout, simai_bulk.CHECKOUT = simai_bulk.CHECKOUT, root
    was_cache, simai_bulk.CACHE = simai_bulk.CACHE, pathlib.Path(tempfile.mkdtemp())
    was_charts, simai_bulk.CHARTS = simai_bulk.CHARTS, simai_bulk.CACHE / "charts.json.gz"
    was_stamp, simai_bulk.STAMP = simai_bulk.STAMP, simai_bulk.CACHE / "taken.json"
    was_update, simai_bulk.update = simai_bulk.update, lambda force=False: 0
    was_discard, simai_bulk.discard = simai_bulk.discard, lambda: None
    was_facts = mai_notes.cached_facts
    was_path, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    problems = []
    try:
        found = dict(simai_bulk.charts())
        if set(found) != {"test song|dx|basic", "test song|dx|master"}:
            problems.append(f"a song's difficulties were not split into charts the manifest could match: {list(found)}")
        if found and "8" not in found.get("test song|dx|master", ""):
            problems.append("the difficulties were read in the wrong order, so a chart carries another's notes")

        # the cache holds every chart the clone had, including ones the manifest does not name yet,
        # so a version that names them later needs no download
        simai_bulk._keep(found, "abc123")
        if set(simai_bulk.cached()) != set(found):
            problems.append("the cache on disk does not hold what the clone did")
        if int(simai_bulk._taken().get("charts") or 0) != len(found):
            problems.append("the cache does not say how much it holds, so an update cannot tell")
        big = {f"song {n}|dx|master": "(120){8}1,2,3,4,5,6,7,8," * 40 for n in range(200)}
        plain = sum(len(key.encode()) + len(body.encode()) for key, body in big.items())
        simai_bulk._keep(big, "abc123")
        packed = simai_bulk.CHARTS.stat().st_size
        if packed > plain / 4:
            problems.append(f"the cache is {packed} bytes for {plain} of notation, so it is barely packed")
        if set(simai_bulk.cached()) != set(big):
            problems.append("the cache did not come back the way it went in")
        simai_bulk._keep(found, "abc123")

        # only the charts the manifest lists are measured, because nothing else can check them
        facts = {"test song|dx|master": {"n": 8, "l": 13.0, "c": "abc"}}
        mai_notes.cached_facts = lambda: types.SimpleNamespace(
            exact=facts, get=lambda key: facts.get("|".join(key)))
        known = {}
        read = simai_bulk.load(known)
        if read != 1 or set(known) != {"test song|dx|master"}:
            problems.append(f"the cache measured {read} charts and held {list(known)}, expected only the listed one")
        if simai_bulk.load(known):
            problems.append("a chart already measured was measured out of the cache a second time")

        # the checkout itself is not kept: what is worth keeping is in the packed cache by then
        source = (ROOT / "rasmai" / "scraping" / "simai_bulk.py").read_text(encoding="utf-8")
        if "finally:" not in source or "discard()" not in source:
            problems.append("the clone is read without being deleted afterwards")

        # git writes its pack files read-only, and a delete that walks away from those leaves the
        # whole clone behind while reporting nothing
        import os as _os
        import stat as _stat
        pretend = pathlib.Path(tempfile.mkdtemp()) / "repo" / ".git" / "objects"
        pretend.mkdir(parents=True)
        locked = pretend / "pack"
        locked.write_bytes(b"x")
        _os.chmod(locked, _stat.S_IREAD)
        simai_bulk.discard, simai_bulk.CHECKOUT = was_discard, pretend.parent.parent
        try:
            simai_bulk.discard()
            if simai_bulk.CHECKOUT.exists():
                problems.append("a checkout with read-only files in it was left on disk")
        finally:
            simai_bulk.discard, simai_bulk.CHECKOUT = (lambda: None), root
            _os.chmod(locked, _stat.S_IWRITE) if locked.exists() else None

        # and what the clone did not have is still left for the site to be asked for
        facts["other song|dx|master"] = {"n": 8, "l": 13.0, "c": "def"}
        simai_bulk.load(known)
        if "other song|dx|master" in known:
            problems.append("a chart the clone does not hold was marked as read")
    finally:
        simai_bulk.CHECKOUT, simai_bulk.update = was_checkout, was_update
        simai_bulk.CACHE, simai_bulk.CHARTS, simai_bulk.STAMP = was_cache, was_charts, was_stamp
        simai_bulk.discard = was_discard
        mai_notes.cached_facts = was_facts
        store.DATABASE_PATH = was_path
        store._database_ready = False
    return problems


@check("a technique is found in the notes themselves: trills, jacks, streams, walks round the ring, delayed slides and fans")
def _techniques():
    from rasmai.engine.simai.parse import parse
    from rasmai.engine.simai.techniques import techniques

    def of(chart):
        return techniques(parse(chart).notes)

    problems = []
    # 1 2 1 2 1 2 1 2 at sixteenths: two places, swapped every note, which is a trill and not a jack
    trill = of("(180){16}1,2,1,2,1,2,1,2,E")
    if trill["trills"] <= 0:
        problems.append("an alternation between two buttons was not read as a trill")
    if trill["jacks"] > 0:
        problems.append("a trill was counted as a jack as well")

    # the same button over and over is a jack, and must not be read as a trill
    jack = of("(180){16}3,3,3,3,3,3,E")
    if jack["jacks"] <= 0:
        problems.append("the same button struck six times over was not read as a jack")
    if jack["trills"] > 0:
        problems.append("a jack was counted as a trill as well")

    # a long even run across the ring is a stream
    run = of("(180){16}1,2,3,4,5,6,7,8,1,2,3,4,E")
    if run["streams"] <= 0:
        problems.append("a long even run across the ring was not read as a stream")

    # pads walked in a row are a touch sweep; buttons are not
    sweep = of("(180){8}A1,A2,A3,A4,E")
    if sweep["touchSweeps"] <= 0:
        problems.append("touch pads walked in sequence were not read as a sweep")
    if of("(180){8}1,2,3,4,E")["touchSweeps"] > 0:
        problems.append("ring buttons were counted as a touch sweep")

    # slow, spread-out notes are none of these
    quiet = of("(90){1}1,2,1,2,E")
    if any(quiet.get(k, 0) for k in ("trills", "jacks", "streams", "touchSweeps")):
        problems.append(f"notes a second apart were read as a technique: {quiet}")

    # a slide picking up where the last ended is one stroke continued
    chain = of("(120){4}1-3[4:1],3-5[4:1],5-7[4:1],E")
    if chain["chainedSlides"] <= 0:
        problems.append("slides carrying on from one another were not read as chained")
    if of("(120){4}1-3[4:1],,,6-8[4:1],E")["chainedSlides"] > 0:
        problems.append("two unrelated slides were read as chained")

    # a run that never turns back is a stream going round the ring, not a trill
    circle = of("(180){8}1,2,3,4,5,6,7,8,E")
    if circle["circles"] <= 0:
        problems.append("notes stepping round the ring were not read as a walk round it")
    if circle["trills"] > 0:
        problems.append("a walk round the ring was counted as a trill")
    if of("(180){16}1,3,2,4,3,5,4,6,E")["circles"] > 0:
        problems.append("a trill that wanders was counted as a walk round the ring")
    if of("(180){8}1,4,7,2,5,8,E")["circles"] > 0:
        problems.append("notes thrown a third of the way round each time were read as walking it")

    # the two trills that are named apart from each other: on the spot, and across the machine
    if of("(180){16}1,2,1,2,1,2,1,2,E")["stationaryTrills"] <= 0:
        problems.append("a trill between two neighbours was not read as one on the spot")
    across = of("(180){16}1,5,1,5,1,5,1,5,E")
    if across["scatterTrills"] <= 0:
        problems.append("a trill between opposite sides was not read as one across the screen")
    if across["stationaryTrills"] > 0:
        problems.append("a trill across the screen was counted as one on the spot as well")

    # one hand pinned to a button while the other moves about
    axis = of("(180){16}1,3,1,4,1,5,1,6,E")
    if axis["axisTrills"] <= 0:
        problems.append("a trill against a held button was not read as one")
    if of("(180){16}1,2,1,2,1,2,1,2,E")["axisTrills"] > 0:
        problems.append("a trill between two buttons was read as one against a held button")

    # a star struck, notes played over the top of it, and only then the slide setting off
    if of("(120){4}1-5[2##1.5],2,3,4,E")["delayedSlides"] <= 0:
        problems.append("a slide held back while other notes were played was not read as delayed")
    if of("(120){4}1-5[4:1],,,,E")["delayedSlides"] > 0:
        problems.append("a slide with nothing played over it was read as delayed")

    # the fan slide is written as one letter and is counted as itself, not as a spin
    if of("(120){4}1w5[4:1],E")["wifiSlides"] <= 0:
        problems.append("the fan slide was not read as one")
    if of("(120){4}1-5[4:1],E")["wifiSlides"] > 0:
        problems.append("a straight slide was read as a fan")

    # a trill while a slide from earlier is still travelling is one hand on its own
    over = of("(120){4}1-5[1:1],{16}3,4,3,4,3,4,3,4,E")
    if over["trillsOverSlides"] <= 0:
        problems.append("a trill played while a slide was still travelling was not read as one")
    if of("(120){16}3,4,3,4,3,4,3,4,E")["trillsOverSlides"] > 0:
        problems.append("a trill with both hands free was read as one played over a slide")

    # two looping slides on screen at once is where the arms cross; one after the other is not
    if of("(120){4}1p5[1:2],2q6[1:2],E")["crossedLoops"] <= 0:
        problems.append("two looping slides overlapping were not read as crossed")
    if of("(120){1}1p5[4:1],,,,2q6[4:1],E")["crossedLoops"] > 0:
        problems.append("two loops one after the other were read as crossed")
    if of("(120){4}1-5[1:2],2-6[1:2],E")["crossedLoops"] > 0:
        problems.append("two straight slides were read as loops")

    # and two slides travelling at once at very different speeds
    if of("(120){4}1-5[1:4],2-6[8:1],E")["mixedSpeedSlides"] <= 0:
        problems.append("two slides travelling at once at different speeds were not read as one")
    if of("(120){4}1-5[1:4],2-6[1:4],E")["mixedSpeedSlides"] > 0:
        problems.append("two slides travelling at the same speed were read as mismatched")

    # a technique is a share of the chart, so it cannot exceed it
    for key, value in trill.items():
        if not 0.0 <= value <= 1.0:
            problems.append(f"{key} came out at {value}, which is not a share of anything")
    return problems


@check("a trait only a tenth of charts have is still named, rather than falling off the bottom of a quartile")
def _rare_demand():
    from rasmai.engine.simai.features import CUT, DEMANDS, HARD, thresholds, traits

    # a hundred charts, ten of which have the thing: the quartile of that is zero, and a measure
    # judged against a level of zero is never named at all. That is what the fixed bar is for.
    problems = []
    rare = [(key, label, fixed) for key, _d, label, fixed in DEMANDS if fixed]
    for key, label, fixed in rare:
        rows = [{key: fixed if n < 10 else 0.0, "lv": 13.0} for n in range(100)]
        named = [name for _, name in traits(rows[0], thresholds(rows))]
        if label not in named:
            problems.append(f"{key} has a bar of its own and still went unnamed on a chart carrying it: {named}")
    if not any(key == "scatterTrills" for key, _, _f in rare):
        problems.append("scatter trills are on a tenth of charts, so a quartile of them is zero: they need a bar of their own")

    # and a measure most charts do have is left to the quartile, which must still refuse the bottom
    common = [{"quickSlides": n / 100, "lv": 13.0} for n in range(100)]
    levels = thresholds(common)
    if "fast slides" not in [name for _, name in traits(common[-1], levels)]:
        problems.append("the chart highest of all on a measure was not named for it")
    if "fast slides" in [name for _, name in traits(common[0], levels)]:
        problems.append("the chart lowest of all on a measure was named for it anyway")
    cut = thresholds([{"peak": float(n), "lv": 13.0} for n in range(100)]).get("peak") or 0.0
    if not 70 <= cut <= 80:
        problems.append(f"the top quarter of a hundred evenly spread charts starts at {cut}, not near {CUT * 100:.0f}")
    if HARD < 10:
        problems.append("the quartile is being taken over charts easier than the model is meant for")
    return problems


@check("a chart read from the notes is found even when maimai spaces its title differently")
def _simai_loose_title():
    from rasmai.scraping import simai

    # maimai writes a title with its own spacing and width; the sites that catalogue it do not.
    # Matching those exactly reached 62% of what a player has played, the looser match 95%.
    rows = {"o.n.e.　-in the name of love-|dx|master": {"trills": 0.9, "lv": 13.0}}
    levels = {"trills": 0.1}
    held = simai.cached
    simai.cached = lambda: (rows, levels)
    simai._loose = (None, {})
    problems = []
    try:
        if not simai.chart_traits(("o.n.e.　-in the name of love-", "dx", "master")):
            problems.append("a chart was not found under the very title it is stored as")
        if not simai.chart_traits(("O.N.E. -in the name of love-", "dx", "master")):
            problems.append("a chart was not found when the title was spaced the way maimai spaces it")
        if simai.chart_traits(("something else entirely", "dx", "master")):
            problems.append("a chart that is not held was matched to one that is")
        if simai.chart_traits(("o.n.e.　-in the name of love-", "std", "master")):
            problems.append("the loose match ignored the chart type, so a standard chart took a DX reading")
        if simai.chart_traits(("o.n.e.　-in the name of love-", "dx", "expert")):
            problems.append("the loose match ignored the difficulty, so one chart took another's reading")
    finally:
        simai.cached = held
        simai._loose = (None, {})
    return problems


@check("nothing is shown that cannot be confirmed: not a lean on too few charts, not a family of one")
def _only_what_can_graduate():
    from rasmai.engine.insights.families import FAMILY_MIN_CHARTS, FAMILY_MIN_TRAITS, family_axes
    from rasmai.engine.insights.traits import TRAIT_CONFIRM_CHARTS, leaning

    def axis(label, offset, count, **rest):
        return {"dimension": "pattern", "label": label, "offset": offset, "count": count,
                "plays": 2, "verified": False, "leaning": True, **rest}

    problems = []
    # eight charts is enough to measure a trait, twelve to confirm one. A lean in between can never
    # graduate however much the player plays, so it is not told to them as a weakness.
    thin = axis("fast slides", -0.84, TRAIT_CONFIRM_CHARTS - 1)
    thick = axis("trills", -0.84, TRAIT_CONFIRM_CHARTS)
    shown = [a["label"] for a in leaning([thin, thick])]
    if "fast slides" in shown:
        problems.append(f"a lean on {thin['count']} charts was shown, and it can never be confirmed")
    if "trills" not in shown:
        problems.append("a lean on enough charts to be confirmed one day was not shown")

    # and a family averaging one trait is that trait wearing a family's name, drawn the same size as
    # a family averaging thirteen
    lone = [{"dimension": "pattern", "label": "spinning round the ring", "offset": 0.49,
             "count": FAMILY_MIN_CHARTS * 2, "plays": 9, "verified": False, "leaning": False}]
    if family_axes(lone):
        problems.append("a family was drawn from a single trait")
    pair = lone + [{"dimension": "rotation", "label": "速い回転 (fast rotations)", "offset": -0.2,
                    "count": FAMILY_MIN_CHARTS, "plays": 4, "verified": False, "leaning": False}]
    drawn = family_axes(pair)
    if not any(f["key"] == "rotation" for f in drawn):
        problems.append(f"a family of {FAMILY_MIN_TRAITS} traits over {FAMILY_MIN_CHARTS * 3} charts was not drawn")

    # a family still needs the charts as well as the traits
    small = [dict(a, count=4) for a in pair]
    if family_axes(small):
        problems.append("a family with almost no charts behind it was drawn because it had two traits")
    return problems


@check("the one account can update either chart database by hand, and nobody else can")
def _manual_updates():
    import json as _json

    from rasmai.web.dashboard import admin, routes

    class Answer:
        def __init__(self):
            self.code, self.body = 0, {}

        def _send_json(self, code, body):
            self.code, self.body = code, body

    problems = []
    held_admin, held_route = admin.is_admin, routes.start_update
    asked = []
    routes.start_update = lambda source: asked.append(source) or {"ok": True, "running": True}
    try:
        routes.is_admin = lambda user_id: user_id == "1"
        answer = Answer()
        routes.handle_post(answer, "/internal/me/admin/update", {"id": "1"}, {"source": "simai"})
        if answer.code != 202 or asked != ["simai"]:
            problems.append(f"the one account could not start an update: {answer.code} {answer.body}, asked {asked}")

        asked.clear()
        answer = Answer()
        routes.handle_post(answer, "/internal/me/admin/update", {"id": "2"}, {"source": "simai"})
        if answer.code != 404 or asked:
            problems.append(f"someone else started an update: {answer.code} {answer.body}, asked {asked}")
        if answer.body.get("error") != "not_found":
            problems.append("a refused update says it was refused, which tells the caller the page is there")
    finally:
        routes.start_update = held_route
        routes.is_admin = held_admin

    # only the two databases there are, and one at a time
    if admin.start_update("nonsense").get("ok"):
        problems.append("a database nobody has was updated")
    for source in admin.SOURCES:
        admin._updates[source] = {"running": True}
        if admin.start_update(source).get("ok"):
            problems.append(f"a second {source} update started while the first was still running")
        admin._updates.pop(source, None)

    # and the site is allowed to ask for it
    proxy = (ROOT / "web" / "app" / "api" / "me" / "[...rest]" / "route.ts").read_text(encoding="utf-8")
    if "admin/update" not in proxy:
        problems.append("the site cannot reach the update route, so the buttons do nothing")
    if not _json.dumps(admin.update_state()).startswith("{"):
        problems.append("the developer page cannot be told how the last update went")
    return problems


@check("a measured trait is named after the technique, not after the kind of chart that carries it")
def _trait_wording():
    from rasmai.engine.simai.features import DEMANDS
    from rasmai.scraping.mai_notes import PATTERN_ENGLISH, SHARE_BANDS

    problems = []
    # "charts with trills" is how the model groups them; "trills" is the thing the player does, and
    # the tab is about the player
    for _key, _dimension, label, _fixed in DEMANDS:
        if label.startswith("charts "):
            problems.append(f"{label!r} names a kind of chart rather than what it asks of the hands")
    for _field, _kind, _high, label in SHARE_BANDS:
        if label.endswith(" charts"):
            problems.append(f"{label!r} names a kind of chart rather than what it asks of the hands")

    # the editors' トリル is shown as "trills" and so is the measure taken off the notation, so a row
    # has to say which it is or the two read as one thing said twice
    measured = {label for _k, _d, label, _f in DEMANDS}
    shared = measured & set(PATTERN_ENGLISH.values())
    site = (ROOT / "web" / "components" / "dash" / "Traits.tsx").read_text(encoding="utf-8")
    if shared and "t.read" not in site:
        problems.append(f"{sorted(shared)} are worded the same as a community tag and nothing says which is which")
    if shared and '"read"' not in (ROOT / "rasmai" / "web" / "dashboard" / "picks.py").read_text(encoding="utf-8"):
        problems.append("the site is never told which traits were read from the notes")
    return problems


@check("a chart is only offered abroad when both sources agree it left Japan, and the page says where it is")
def _region_gate():
    from rasmai.engine.analysis.charts import ChartIndex, ChartRef
    from rasmai.web.dashboard.lookup import _regions

    def chart(**over):
        base = dict(title="LOSTPHANTASIA", chart_type="dx", difficulty="master", constant=12.9, level="12+",
                    notes=700, genre="", artist="", cover="", version=24)
        base.update(over)
        return ChartRef(**base)

    problems = []
    index = ChartIndex("intl")
    index.current_version = 26
    # the case it was found on: dxrating had it on every cabinet, the chart database had it as Japan
    # only, and dxrating's word alone put it in front of a player who could not play it
    if index.playable(chart(intl=True, intl_known=True, listed_intl=False)):
        problems.append("a chart the database says never left Japan was offered to a player abroad")
    if not index.playable(chart(intl=True, intl_known=True, listed_intl=True)):
        problems.append("a chart both sources say is abroad was withheld")
    # the one place the database's own flag is known to lag: the version the player is on
    if not index.playable(chart(intl=True, intl_known=True, listed_intl=False, version=26)):
        problems.append("a chart of the player's own version was withheld on a flag known to lag there")
    if index.playable(chart(intl=False, intl_known=True, listed_intl=True)):
        problems.append("a chart dxrating says is Japan only was offered to a player abroad")

    # and nothing is withheld from a player on the cabinet the database tracks
    japan = ChartIndex("jp")
    japan.current_version = 27
    if not japan.playable(chart(intl=False, intl_known=True, listed_intl=False)):
        problems.append("a Japanese player was refused a Japanese chart")

    # the lookup spans every region, so it has to say which ones have each chart
    if _regions(chart(intl=True, listed_intl=True, regions="jic")) != ["jp", "intl", "cn"]:
        problems.append("a chart on every cabinet was not said to be")
    if "intl" in _regions(chart(intl=True, listed_intl=False, regions="jic")):
        problems.append("a chart only one source calls international was shown as international")
    if _regions(chart(intl=False, listed_intl=False, regions="jc")) != ["jp", "cn"]:
        problems.append("a Japan and China chart was not said to be one")
    return problems


@check("the curve never says a harder chart should go better, nor an easier one worse")
def _curve_runs_one_way():
    from rasmai.engine.analysis import ChartIndex, ChartRef, build_play_profile, calculate_rating
    from rasmai.storage.models import SongInfo

    # a player with a dense band of good scores and two lonely ones far outside it, which is what
    # bends the fit: the kernel reaches for whatever bucket is nearest and can turn the curve round
    index, played = ChartIndex(), []
    rows = [(12.0, 99.5)] * 40 + [(12.5, 99.0)] * 20 + [(4.0, 80.0), (15.0, 84.0), (14.6, 70.0)]
    for n, (constant, accuracy) in enumerate(rows):
        title = f"chart {n}"
        index.add(ChartRef(title=title, chart_type="dx", difficulty="master", constant=constant,
                           level="13", notes=700, genre="", artist="", cover="", version=25, bpm=0.0))
        played.append(SongInfo(name=title, chart_type="dx", difficulty_type="master", accuracy=accuracy,
                               is_new=False, level="13", difficulty=constant,
                               rating=calculate_rating(constant, accuracy)))
    profile = build_play_profile(played, [], index, 26)

    problems = []
    points = profile.curve_points()
    if not points:
        problems.append("the curve came out empty for a player with sixty scores")
    rises = [(a, b) for a, b in zip(points, points[1:]) if b["e"] > a["e"] + 1e-6]
    if rises:
        first = rises[0]
        problems.append(f"the curve rises as charts get harder, at {first[0]['c']} -> {first[1]['c']} "
                        f"({first[0]['e']} -> {first[1]['e']}), on {len(rises)} points")
    # and the same rule the other way: a chart easier than where the evidence is may not be worse
    if profile.expected_accuracy(6.0) < profile.expected_accuracy(12.0) - 1e-6:
        problems.append("an easier chart was expected to go worse than a harder one")
    # where the player actually plays, the fit is left alone
    if abs(profile.expected_accuracy(12.0) - profile._raw_expectation(12.0)) > 0.05:
        problems.append("the flattening moved the curve where the player's own scores are densest")
    return problems


@check("a song is found by the names people type for it, not only by its own title")
def _search_aliases():
    import pathlib
    import tempfile

    from rasmai.scraping import aliases
    from rasmai.storage.db import connection as store

    was, store.DATABASE_PATH = store.DATABASE_PATH, pathlib.Path(tempfile.mkdtemp()) / "t.sqlite3"
    store._database_ready = False
    problems = []
    try:
        # the file's own shape: [title, artist, [spellings]]
        table = aliases.distil({"entries": [["+♂", "someone", ["+boy", "plus male"]],
                                            ["ケロ⑨destiny", "Silver Forest", ["kero destiny"]],
                                            ["no aliases", "x", []],
                                            ["broken"]]})
        if len(table) != 2:
            problems.append(f"the alias file read as {len(table)} songs, expected the two that have any")
        if table.get("+♂") != ["+boy", "plus male"]:
            problems.append(f"a song's other names were not kept under its folded title: {table}")

        # nothing is searched by until it has been stored, and a bad answer leaves what is held alone
        if aliases.aliases_for("+♂"):
            problems.append("aliases were served from an empty database")
        from rasmai.storage.db import source_state_set
        import json as _json
        source_state_set(aliases.SOURCE, payload=_json.dumps(table))
        aliases._memo = (0.0, None)
        if aliases.aliases_for("+♂") != ["+boy", "plus male"]:
            problems.append("a stored alias did not come back for its song")
        if aliases.aliases_for("a song nobody wrote"):
            problems.append("a song with no aliases was given some")

        # the search table has to take them, or storing them changes nothing anyone can see
        source = (ROOT / "rasmai" / "bot" / "builders" / "charts" / "index.py").read_text(encoding="utf-8")
        if "party_aliases.aliases_for" not in source:
            problems.append("the aliases are stored but nothing searches by them")
    finally:
        store.DATABASE_PATH = was
        store._database_ready = False
        aliases._memo = (0.0, None)
    return problems


def main() -> None:
    """Run every check and exit non-zero if any of them complained."""
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nEverything passed.")


if __name__ == "__main__":
    main()
