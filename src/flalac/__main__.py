"""Start the mirror and the web UI: `flalac` or `python -m flalac`.

`flalac once --source FLAC --target ALAC [--config STATE]` runs one pass and exits.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import sys
from pathlib import Path

import uvicorn

from . import __version__
from .config import Settings, SettingsError
from .db import Database
from .runner import Runner
from .sync import Engine
from .web import create_app


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        settings = Settings.from_env()
    except SettingsError as error:
        print(f"flalac: {error}", file=sys.stderr)
        return 2
    if argv[:1] == ["once"]:
        return _once(settings, argv[1:])
    if shutil.which("ffmpeg") is None:
        print("flalac: ffmpeg is not installed or not on PATH", file=sys.stderr)
        return 2
    for label, path in (("SOURCE_DIR", settings.source), ("TARGET_DIR", settings.target)):
        if not path.is_dir():
            print(f"flalac: {label} {path} is not a folder; mount it first", file=sys.stderr)
            return 2
    db = Database(settings.config / "flalac.db")
    engine = Engine(settings, db)
    runner = Runner(engine)
    db.event(
        "started",
        None,
        f"flalac {__version__}, target {settings.target_format}, "
        f"lyrics {settings.lyrics}{', dry run' if settings.dry_run else ''}",
    )
    runner.start()
    try:
        uvicorn.run(
            create_app(engine, runner),
            host=settings.host,
            port=settings.port,
            log_level="warning",
            proxy_headers=True,
        )
    finally:
        runner.stop()
        db.close()
    return 0


def _once(settings: Settings, argv: list[str]) -> int:
    from .once import OnceError, run

    parser = argparse.ArgumentParser(prog="flalac once", description="One pass, then exit.")
    parser.add_argument("--source", type=Path, required=True, help="the FLAC folder")
    parser.add_argument("--target", type=Path, required=True, help="where the copy goes")
    parser.add_argument("--config", type=Path, help="state folder (default: TARGET/../.flalac)")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--yes", action="store_true", help="confirm large removals")
    args = parser.parse_args(argv)
    settings = dataclasses.replace(
        settings,
        source=args.source,
        target=args.target,
        config=args.config or args.target.parent / ".flalac",
        workers=args.workers,
    )

    def progress(done: int, total: int, current: str) -> None:
        print(f"{done}/{total} {current}", flush=True)

    try:
        summary = run(settings, progress, lambda count: args.yes)
    except OnceError as error:
        print(f"flalac: {error}", file=sys.stderr)
        return 1
    print(summary.text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
