"""The command-line engine behind the flalac Mac app: one JSON object per line on stdout.

    flalac-engine sync --source FLAC --target ALAC [--state DIR] --library itunes|music|none
                       [--jellyfin-url URL --jellyfin-user USER] [--lyrics lrclib|off]
                       [--lyrics-style plain|synced] [--max-bit-depth 16|24|0]
                       [--max-sample-rate 44100|48000|0] [--jellyfin-music-path PATH]
                       [--confirm-deletes]
    flalac-engine test-jellyfin --jellyfin-url URL --jellyfin-user USER
    flalac-engine version

The Jellyfin API key comes from the environment (FLALAC_JELLYFIN_KEY), never the command line.
Messages: stage, progress, held-deletes, summary, jellyfin, version, error (then exit 1).
stderr is free-form log text.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import os
import signal
import sys
import traceback
from pathlib import Path

from . import __version__
from .config import Settings
from .db import Database
from .itunes import LibraryError, sync_library
from .jellyfin import Jellyfin, JellyfinError
from .once import OnceError, Summary, run

KEY_ENV = "FLALAC_JELLYFIN_KEY"


def emit(kind: str, **fields: object) -> None:
    print(json.dumps({"type": kind, **fields}, ensure_ascii=False), flush=True)


def log(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flalac-engine")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("--source", type=Path, required=True)
    sync.add_argument("--target", type=Path, required=True)
    sync.add_argument("--state", type=Path)
    sync.add_argument("--library", choices=("itunes", "music", "none"), default="none")
    sync.add_argument("--lyrics", choices=("lrclib", "off"), default="lrclib")
    sync.add_argument("--lyrics-style", choices=("plain", "synced"), default="plain")
    sync.add_argument("--max-bit-depth", type=int, choices=(16, 24, 0), default=16)
    sync.add_argument("--max-sample-rate", type=int, choices=(44100, 48000, 0), default=44100)
    # Alone: confirm whatever is held. With a number: only if exactly that many are deleted
    # (the count the person saw); otherwise they are held again.
    sync.add_argument("--confirm-deletes", nargs="?", type=int, const=-1, default=None)
    for command in (sync, commands.add_parser("test-jellyfin")):
        command.add_argument("--jellyfin-url", default="")
        command.add_argument("--jellyfin-user", default="")
        command.add_argument("--jellyfin-music-path", default="/Media/Music/FLAC")
    commands.add_parser("version")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    key = os.environ.get(KEY_ENV, "") if args.jellyfin_url and args.jellyfin_user else ""
    return dataclasses.replace(
        Settings(),
        source=args.source,
        target=args.target,
        config=args.state or args.target.parent / ".flalac",
        workers=os.cpu_count() or 2,
        lyrics=args.lyrics,
        lyrics_style=args.lyrics_style,
        lyrics_files=False,
        max_bit_depth=args.max_bit_depth,
        max_sample_rate=args.max_sample_rate,
        jellyfin_url=args.jellyfin_url,
        jellyfin_user=args.jellyfin_user,
        jellyfin_api_key=key,
        jellyfin_music_path=args.jellyfin_music_path,
    )


def _sync(args: argparse.Namespace) -> int:
    settings = _settings(args)
    emit("stage", stage="checking")  # scanning the FLAC folder until songs start converting
    converting = False

    def progress(done: int, total: int, current: str) -> None:
        nonlocal converting
        if not converting:
            converting = True
            emit("stage", stage="converting")
        emit("progress", stage="converting", done=done, total=total, current=current)

    def confirm(count: int) -> bool:
        return args.confirm_deletes is not None and args.confirm_deletes in (-1, count)

    try:
        summary = run(settings, progress, confirm, every=1.0)
    except OnceError as error:
        emit("error", message=str(error))
        return 1
    log(summary.text())
    if summary.held_deletes:
        emit("held-deletes", count=summary.held_deletes)
    library = None
    notes: list[str] = []
    if args.library != "none":
        app = "iTunes" if args.library == "itunes" else "Music"
        emit("stage", stage="library")
        db = Database(settings.config / "flalac.db")
        try:
            result = sync_library(
                settings,
                db,
                f"{app} library: {settings.target}",
                lambda message: emit("progress", stage="library", message=message),
                app,
            )
        except LibraryError as error:
            # The songs were converted all the same; report that before the failure
            _emit_summary(summary, None, [])
            emit("error", message=f"The {app} library could not be updated: {error}")
            return 1
        finally:
            db.close()
        log(result.text())
        notes = list(result.notes or [])
        library = {
            "app": app,
            "added": result.added,
            "removed": result.removed,
            "moved": result.moved,
            "refreshed": result.refreshed,
            "plays": result.plays,
            "failed": result.failed,
        }
    if args.library != "none" and not settings.jellyfin_api_key:
        notes.append("Play counts: Jellyfin is not set up.")
    emit("stage", stage="done")
    _emit_summary(summary, library, notes)
    return 0


def _emit_summary(summary: Summary, library: dict | None, notes: list[str]) -> None:
    emit(
        "summary",
        converted=summary.encoded,
        retagged=summary.retagged,
        renamed=summary.moved,
        removed=summary.deleted,
        errors=summary.errors,
        unsettled=summary.unsettled,
        held_deletes=summary.held_deletes,
        seconds=round(summary.seconds, 1),
        library=library,
        notes=notes,
    )


def _test_jellyfin(args: argparse.Namespace) -> int:
    key = os.environ.get(KEY_ENV, "")
    if not (args.jellyfin_url and args.jellyfin_user and key):
        emit("error", message="Jellyfin needs an address, a user and an API key.")
        return 1
    client = Jellyfin(args.jellyfin_url, key, args.jellyfin_user, args.jellyfin_music_path)
    try:
        counts = client.play_counts()
    except JellyfinError as error:
        emit("error", message=f"Jellyfin: {error}")
        return 1
    emit("jellyfin", ok=True, songs=len(counts), plays=sum(i.plays for i in counts.values()))
    return 0


def _stop_with_children() -> None:
    """Cancel in the app sends SIGTERM: stop the conversions in flight (ffmpeg) too. The engine
    runs in its own process group, so it can signal exactly itself and its children. Files
    left half-written are temp files, removed at the start of the next sync."""
    with contextlib.suppress(OSError):
        os.setpgrp()

    def stop(signum: int, frame: object) -> None:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.killpg(os.getpgrp(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, stop)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "version":
        emit("version", version=__version__)
        return 0
    if args.command == "test-jellyfin":
        return _test_jellyfin(args)
    if argv is None:  # the real program, not a test calling main() directly
        _stop_with_children()
    try:
        return _sync(args)
    except Exception as error:
        # Never a bare traceback: the app shows `error` messages (an unplugged drive, a
        # database that can't be opened); the details go to stderr, which it logs
        log(traceback.format_exc())
        emit("error", message=f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
