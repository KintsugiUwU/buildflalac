"""Entry point of flalac.app: put the bundled ffmpeg first on PATH, then start flalac.

flalac runs `ffmpeg` by name, so prepending the bundle's `bin` folder to PATH makes it use the
ffmpeg inside the app, never one from Homebrew or anywhere else. The app starts
`flalac.macapp:main`; builds made before that module existed (and any build started with
FLALAC_SMOKE_TEST=1) run the bundle self-test in `smoke_entry.py` instead.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def bundle_dir() -> Path | None:
    """The folder PyInstaller unpacked the app into (Contents/Frameworks), None from source."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(getattr(sys, "_MEIPASS"))  # noqa: B009 (set only in a frozen app)


def use_bundled_ffmpeg() -> Path | None:
    """Prepend the bundle's ffmpeg folder to PATH; returns that folder (None from source)."""
    bundle = bundle_dir()
    if bundle is None:
        return None
    bin_dir = bundle / "bin"
    path = os.environ.get("PATH") or os.defpath
    os.environ["PATH"] = os.pathsep.join([str(bin_dir), path])
    return bin_dir


def main() -> int:
    use_bundled_ffmpeg()
    if (
        os.environ.get("FLALAC_SMOKE_TEST") == "1"
        or importlib.util.find_spec("flalac.macapp") is None
    ):
        from smoke_entry import smoke

        return smoke()
    from flalac.macapp import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
