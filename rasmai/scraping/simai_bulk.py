from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, Tuple
import gzip
import json
import logging
import os
import re
import shutil
import stat
import subprocess

logger = logging.getLogger(__name__)

# Reading the charts one file at a time from maiノーツ takes about an hour, a second a chart, and
# starts over for every chart the site has since added. Neskol's repository holds the same charts
# converted to simai in one place, so it is taken the way the chart database is taken: one shallow
# clone, kept as a cache, with the site left to cover whatever the clone does not have.
#
# Checked before it was trusted: of the charts in the clone that maiノーツ also publishes a note
# count for, every one agrees exactly.
REPO = "https://github.com/Neskol/Maichart-Converts.git"
CACHE = Path(os.getenv("MAIMAI_SIMAI_CACHE", "simai_cache"))
CHECKOUT = CACHE / "repo"

# the repository is looked at again once the cache is this old; the charts do not change once
# published, so this is only ever picking up what a new game version added
FRESH = timedelta(days=int(os.getenv("MAIMAI_SIMAI_REFRESH_DAYS", "7")))

# What is kept is the notation and nothing else: no git history, no hashes, no per-song folders.
# A clone is ten megabytes, half of it .git, and the same charts packed are under three. So the
# clone is read into one packed file and then deleted.
#
# The cache is what the database is filled from, so a database wiped, or a measure that changes
# meaning, costs a read of this file rather than another download. It holds the charts the manifest
# does not list as well, which the database cannot: when a new version names them, they are here
# already.
CHARTS = CACHE / "charts.json.gz"
STAMP = CACHE / "taken.json"

# a maidata file holds every difficulty of one song, each under its own &inote_N=
DIFFICULTIES = {"2": "basic", "3": "advanced", "4": "expert", "5": "master", "6": "remaster"}

_SECTION = re.compile(r"&inote_([1-6])=(.*?)(?=\n&|\Z)", re.S)


def _said(text: str, field: str) -> str:
    """One &field= line from a maidata header."""
    found = re.search(rf"&{field}=(.*)", text)
    return found.group(1).strip() if found else ""


def _taken() -> Dict[str, object]:
    """What the cache holds and where it came from; empty when there is no cache."""
    try:
        held = json.loads(STAMP.read_text(encoding="utf-8"))
        return held if isinstance(held, dict) else {}
    except (OSError, ValueError):
        return {}


def _fresh(taken: Dict[str, object]) -> bool:
    """Whether the repository was looked at recently enough to leave alone."""
    try:
        return datetime.now() - datetime.fromisoformat(str(taken.get("at"))) < FRESH
    except (TypeError, ValueError):
        return False


def _head() -> str:
    """The commit the repository is on, without fetching any of it."""
    try:
        done = subprocess.run(["git", "ls-remote", REPO, "HEAD"], check=True, capture_output=True,
                              timeout=60, text=True)
        return done.stdout.split()[0] if done.stdout.split() else ""
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError, IndexError):
        return ""


def _here() -> str:
    """The commit the checkout is on."""
    try:
        done = subprocess.run(["git", "-C", str(CHECKOUT), "rev-parse", "HEAD"], check=True,
                              capture_output=True, timeout=60, text=True)
        return done.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _git(*args: str) -> bool:
    try:
        subprocess.run(["git", *args], check=True, capture_output=True, timeout=600)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError) as error:
        # a clone that half landed is still worth reading: Windows refuses some of the paths in this
        # repository, and the files that did arrive are perfectly good
        logger.info("simai bulk: git %s did not finish cleanly: %s", args[0], error)
        return False


def _unlock(func, path, _problem) -> None:
    """Take the read-only bit off and try again: git leaves its pack files that way."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def discard() -> None:
    """Delete the checkout, once what is worth keeping out of it has been kept.

    git writes its pack files read-only, and a plain delete walks away from those without saying so,
    which left the whole clone on disk doing nothing.
    """
    if not CHECKOUT.exists():
        return
    try:
        shutil.rmtree(CHECKOUT, onexc=_unlock)          # onerror before 3.12
    except TypeError:
        shutil.rmtree(CHECKOUT, onerror=_unlock)
    except OSError as error:
        logger.info("simai bulk: could not delete the clone: %s", error)
    if CHECKOUT.exists():
        logger.info("simai bulk: the clone is still on disk at %s", CHECKOUT)


def charts() -> Iterator[Tuple[str, str]]:
    """Every chart in the checkout as ``(key, simai)``, keyed the way the manifest keys them.

    A maidata file carries one song and all of its difficulties, so one file becomes up to five
    charts. The title is the game's own, with the ``[DX]`` the converter appends taken back off.

    :rtype: Iterator[Tuple[str, str]]
    """
    for path in CHECKOUT.rglob("maidata.txt"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = re.sub(r"\[DX\]$", "", _said(text, "title")).strip()
        if not title:
            continue
        kind = "dx" if _said(text, "cabinet").upper() == "DX" else "std"
        for number, body in _SECTION.findall(text):
            difficulty = DIFFICULTIES.get(number)
            if difficulty and body.strip():
                yield f"{title.casefold()}|{kind}|{difficulty}", body


def cached() -> Dict[str, str]:
    """Every chart held on disk, as ``{key: simai}``; empty when there is no cache yet.

    :rtype: Dict[str, str]
    """
    try:
        with gzip.open(CHARTS, "rt", encoding="utf-8") as file:
            held = json.load(file)
        return held if isinstance(held, dict) else {}
    except (OSError, ValueError):
        return {}


def _mark(sha: str, held: int) -> None:
    """Record the commit the cache was built from, how much it holds, and when it was last checked."""
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(json.dumps({"sha": sha, "charts": held,
                                     "at": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    except OSError:
        pass


def _keep(found: Dict[str, str], sha: str) -> None:
    """Write the charts to disk packed, replacing the cache only once the new one is whole."""
    CACHE.mkdir(parents=True, exist_ok=True)
    spare = CHARTS.with_name(CHARTS.name + ".new")
    with gzip.open(spare, "wt", encoding="utf-8", compresslevel=9) as file:
        json.dump(found, file, ensure_ascii=False, separators=(",", ":"))
    spare.replace(CHARTS)
    _mark(sha, len(found))


def update(force: bool = False) -> int:
    """Fetch the repository if it has moved, and keep what it holds; the cache stands if it has not.

    The check is the cheap part: which commit the repository is on is a request of about a kilobyte,
    and while it matches the one the cache was built from there is nothing to download. A week
    between checks, and most of those weeks cost that kilobyte and nothing else.

    :param force: Take a fresh copy even when the cache is current.
    :type force: bool
    :returns: How many charts are in the cache afterwards.
    :rtype: int
    """
    taken = _taken()
    have = int(taken.get("charts") or 0)
    if have and not force and _fresh(taken):
        return have
    head = _head()
    if have and not force and head and head == taken.get("sha"):
        _mark(head, have)                  # looked at today, still the same commit: nothing to fetch
        logger.info("simai bulk: the chart repository has not moved, keeping the %d charts on disk", have)
        return have
    CACHE.mkdir(parents=True, exist_ok=True)
    discard()
    _git("clone", "--depth=1", REPO, str(CHECKOUT))
    try:
        found = dict(charts())
        if not found:
            logger.info("simai bulk: nothing came out of the chart repository, keeping what is on disk")
            return have
        _keep(found, _here() or head)
        logger.info("simai bulk: %d charts kept on disk, %d KB packed, from %s",
                    len(found), CHARTS.stat().st_size // 1024, (_taken().get("sha") or "")[:8])
        return len(found)
    finally:
        discard()


def load(known: Dict[str, object]) -> int:
    """Measure every chart the cache holds that has not been read yet, and keep the notation.

    :param known: Readings already held, keyed by chart; added to in place.
    :type known: Dict[str, object]
    :returns: How many charts were measured out of the cache.
    :rtype: int
    """
    from rasmai.scraping import mai_notes, simai
    from rasmai.storage.db import sheet_put

    update()
    facts = mai_notes.cached_facts()
    read = 0
    for key, body in cached().items():
        if key in known:
            continue
        title, kind, difficulty = key.split("|", 2)
        # the same match the chart table uses: the converter writes a title the way the game does,
        # which is not always the way the catalogue does
        row = facts.get((title, kind, difficulty))
        if row is None:
            continue                     # a chart the manifest does not list: nothing to check it against
        measured = simai.read_chart(body, row)
        if measured is None:
            continue                     # leave it pending, so the site still gets its turn
        sheet_put(key, str(row.get("c") or ""), body)
        known[key] = measured
        read += 1
    if read:
        logger.info("simai bulk: measured %d charts from the copy on disk, without asking the site", read)
    return read
