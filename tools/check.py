from pathlib import Path
import ast
import importlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []

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
             "slow songs (up to 120 BPM)": "slow songs (up to 120 BPM)",
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


def main() -> None:
    """Run every check and exit non-zero if any of them complained."""
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nEverything passed.")


if __name__ == "__main__":
    main()
