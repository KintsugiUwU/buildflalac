"""Start the mirror and the web UI: `flalac` or `python -m flalac`."""

from __future__ import annotations

import shutil
import sys

import uvicorn

from . import __version__
from .config import Settings, SettingsError
from .db import Database
from .runner import Runner
from .sync import Engine
from .web import create_app


def main() -> int:
    try:
        settings = Settings.from_env()
    except SettingsError as error:
        print(f"flalac: {error}", file=sys.stderr)
        return 2
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


if __name__ == "__main__":
    sys.exit(main())
