from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WEB = ROOT / "web"
DATA = ROOT / "data"


def _bin(name: str) -> Path:
    """The path to a program inside the virtual environment.

    :param name: The program's name, without any extension.
    :type name: str
    :returns: The full path, with the extension this platform uses.
    :rtype: Path
    """
    folder = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return VENV / folder / f"{name}{suffix}"


def _run(command, cwd=None, check=True, env=None):
    """Run a command and show it first, so a failure is easy to repeat by hand.

    :param command: The command and its arguments.
    :type command: list
    :param cwd: The directory to run in, or ``None`` for the project root.
    :type cwd: Optional[Path]
    :param check: Whether a non-zero exit should stop the script.
    :type check: bool
    :param env: Extra environment variables to add to the child's own.
    :type env: Optional[dict]
    :returns: The finished process.
    :rtype: subprocess.CompletedProcess
    """
    printable = " ".join(str(part) for part in command)
    print(f"  $ {printable}")
    merged = {**os.environ, **(env or {})}
    return subprocess.run([str(part) for part in command], cwd=str(cwd or ROOT), check=check, env=merged)


def _npm() -> str:
    """The npm executable, which is a batch file on Windows.

    :returns: The name to invoke npm by.
    :rtype: str
    """
    found = shutil.which("npm") or shutil.which("npm.cmd")
    if not found:
        sys.exit("npm was not found. Install Node 20 or newer and try again.")
    return found


def setup(args) -> None:
    """Create the virtual environment, install both halves and write a starter .env.

    Safe to run again: everything it does is skipped when it is already in place.

    :param args: The parsed command line.
    :type args: argparse.Namespace
    """
    if not VENV.exists():
        print("Creating .venv")
        venv.EnvBuilder(with_pip=True).create(VENV)
    print("Installing Python dependencies")
    _run([_bin("python"), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    # pyflakes is what the sweep uses to catch undefined names; it stays out of requirements.txt
    # so the production image does not carry a linter
    _run([_bin("python"), "-m", "pip", "install", "--quiet", "-r", "requirements.txt", "pyflakes"])
    if not args.no_browser:
        print("Installing the headless browser the images are drawn with")
        _run([_bin("playwright"), "install", "chromium"], check=False)

    env_file = ROOT / ".env"
    if not env_file.exists():
        sample = (ROOT / ".env.example").read_text(encoding="utf-8")
        sample = sample.replace("MAIMAI_PUBLIC_URL=", "MAIMAI_PUBLIC_URL=http://localhost:3000")
        env_file.write_text(sample + "\nMAIMAI_DEBUG=true\nMAIMAI_DEBUG_EXPORT_JSON=true\n", encoding="utf-8")
        print("Wrote .env from .env.example. Put your DISCORD_TOKEN in it before running the bot.")

    DATA.mkdir(exist_ok=True)
    print("Installing website dependencies")
    _run([_npm(), "install", "--no-audit", "--no-fund"], cwd=WEB)
    print("\nReady. `python dev.py run` starts the bot and the site together.")


def run(args) -> None:
    """Start the bot and the website together and stop both on Ctrl+C.

    The site runs Next in dev mode, so a saved file reloads in the browser; the bot is
    restarted by hand, which `python dev.py bot` alone makes quicker.

    :param args: The parsed command line.
    :type args: argparse.Namespace
    """
    if not VENV.exists():
        sys.exit("No .venv yet. Run `python dev.py setup` first.")
    processes = []
    try:
        if not args.web_only:
            print("Starting the bot")
            processes.append(subprocess.Popen([str(_bin("python")), "-m", "rasmai"], cwd=str(ROOT)))
        if not args.bot_only:
            print("Starting the website on http://localhost:3000")
            processes.append(subprocess.Popen([_npm(), "run", "dev"], cwd=str(WEB),
                                              env={**os.environ, "MAIMAI_PUBLIC_URL": "http://localhost:3000"}))
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\nStopping")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()


def bot(args) -> None:
    """Run the bot on its own, for when only Python changed.

    :param args: The parsed command line.
    :type args: argparse.Namespace
    """
    _run([_bin("python"), "-m", "rasmai"], check=False)


def check(args) -> None:
    """Run the verification sweep and type-check the website.

    The same sweep CI runs on a push, so a failure here is a failure there.

    :param args: The parsed command line.
    :type args: argparse.Namespace
    """
    _run([_bin("python"), ROOT / "tools" / "check.py"])
    print("Type-checking the website")
    _run([_npm(), "run", "typecheck"], cwd=WEB)
    print("\nAll good.")


def sample(args) -> None:
    """Run one exported account through the model without touching maimai DX NET.

    Point it at a file from `/export` or at a debug export and it prints the profile, the
    picks and the traits, which is the quickest way to see whether a model change helped.

    :param args: The parsed command line.
    :type args: argparse.Namespace
    """
    script = ROOT / "tools" / "replay.py"
    if not script.exists():
        sys.exit("tools/replay.py is missing.")
    _run([_bin("python"), script, args.export], check=False)


def main() -> None:
    """Read the command line and run the chosen step."""
    parser = argparse.ArgumentParser(description="Set up and run Rasmai for development.")
    sub = parser.add_subparsers(dest="command", required=True)

    ready = sub.add_parser("setup", help="create .venv, install everything, write .env")
    ready.add_argument("--no-browser", action="store_true", help="skip the Playwright download")
    ready.set_defaults(func=setup)

    both = sub.add_parser("run", help="start the bot and the website together")
    both.add_argument("--bot-only", action="store_true")
    both.add_argument("--web-only", action="store_true")
    both.set_defaults(func=run)

    sub.add_parser("bot", help="run the bot on its own").set_defaults(func=bot)
    sub.add_parser("check", help="compile the Python and type-check the website").set_defaults(func=check)

    replay = sub.add_parser("sample", help="run an exported account through the model")
    replay.add_argument("export", help="a JSON file from /export or a debug export")
    replay.set_defaults(func=sample)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
