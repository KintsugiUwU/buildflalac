"""flalac as a Mac app that lives on the music drive, next to the copy it keeps.

    <drive>/flalac.app     this app
    <drive>/ALAC/          the ALAC copy
    <drive>/.flalac/       state: flalac.db, settings.json, no-lyrics.txt

Double-click it: it converts what changed in the FLAC folder (usually on a NAS share) onto the
drive, brings the iTunes (or Music) library in step with it, syncs play counts with Jellyfin
when set up, then says what it did. The drive carries everything, so any Mac can use the copy.

Jellyfin: "jellyfin_url" and "jellyfin_user" in settings.json; the API key is kept in this
Mac's Keychain (service "flalac-jellyfin"), never on the drive.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import Settings
from .db import Database
from .itunes import LibraryError, app_name, sync_library
from .once import OnceError, run

DEFAULT_SOURCE = "/Volumes/HelixNAS/NVME/Music/FLAC"
SETTINGS_FILE = "settings.json"
KEYCHAIN_SERVICE = "flalac-jellyfin"


def ask_and_store_key(user: str) -> str:
    """Asks for the Jellyfin API key once (hidden typing) and keeps it in the Keychain."""
    try:
        key = _osascript(
            f"text returned of (display dialog {_quote(f'Jellyfin API key for {user}:')} "
            'default answer "" with hidden answer with title "flalac")'
        )
    except RuntimeError:
        return ""
    if key:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                user,
                "-l",
                "flalac Jellyfin API key",
                "-w",
                key,
            ],
            capture_output=True,
        )
    return key


def keychain_key(user: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", user, "-w"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def drive_root() -> Path:
    """The folder holding flalac.app (the drive), or FLALAC_DRIVE when run from source."""
    if os.environ.get("FLALAC_DRIVE"):
        return Path(os.environ["FLALAC_DRIVE"])
    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        if parent.suffix == ".app":
            return parent.parent
    return Path.cwd()


def _osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dialog(message: str, buttons: tuple[str, ...] = ("OK",), stop: bool = False) -> str:
    """Show a dialog; returns the button pressed ('' when cancelled)."""
    names = "{" + ", ".join(_quote(b) for b in buttons) + "}"
    icon = " with icon stop" if stop else ""
    script = (
        f"display dialog {_quote(message)} buttons {names} default button {len(buttons)}"
        f' with title "flalac"{icon}'
    )
    try:
        return _osascript(script).removeprefix("button returned:")
    except RuntimeError:
        return ""


def notify(message: str) -> None:
    with contextlib.suppress(RuntimeError):
        _osascript(f'display notification {_quote(message)} with title "flalac"')


def choose_folder(prompt: str) -> Path | None:
    try:
        return Path(_osascript(f"POSIX path of (choose folder with prompt {_quote(prompt)})"))
    except RuntimeError:
        return None


def load_settings(drive: Path) -> Settings | None:
    """The drive's settings; asks for the FLAC folder the first time."""
    state = drive / ".flalac"
    path = state / SETTINGS_FILE
    stored = json.loads(path.read_text()) if path.is_file() else {}
    if not stored.get("source"):
        source = Path(DEFAULT_SOURCE)
        if not source.is_dir():
            dialog("Choose the FLAC folder flalac should copy from (for example on the NAS share).")
            source = choose_folder("Choose the FLAC folder:")
            if source is None:
                return None
        stored["source"] = str(source).rstrip("/")
        state.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stored, indent=2) + "\n")
    return dataclasses.replace(
        Settings(),
        source=Path(stored["source"]),
        target=drive / "ALAC",
        config=state,
        workers=int(stored.get("workers", os.cpu_count() or 2)),
        lyrics=str(stored.get("lyrics", "lrclib")),
        lyrics_style=str(stored.get("lyrics_style", "plain")),
        lyrics_files=False,
        max_bit_depth=int(stored.get("max_bit_depth", 16)),
        max_sample_rate=int(stored.get("max_sample_rate", 44100)),
        jellyfin_url=str(stored.get("jellyfin_url", "")),
        jellyfin_user=str(stored.get("jellyfin_user", "")),
        jellyfin_api_key=(
            keychain_key(str(stored["jellyfin_user"]))
            or ask_and_store_key(str(stored["jellyfin_user"]))
        )
        if stored.get("jellyfin_url") and stored.get("jellyfin_user")
        else "",
        jellyfin_music_path=str(stored.get("jellyfin_music_path", "/Media/Music/FLAC")),
    )


def main() -> int:
    drive = drive_root()
    if not str(drive).startswith("/Volumes/"):
        dialog(
            f"Put flalac.app on the music drive, next to its ALAC folder.\nIt is in {drive}.",
            stop=True,
        )
        return 1
    settings = load_settings(drive)
    if settings is None:
        return 1

    def progress(done: int, total: int, current: str) -> None:
        notify(f"{done} of {total} converted")

    def confirm(count: int) -> bool:
        answer = dialog(
            f"{count} songs are gone from the FLAC folder. Remove them from the drive too?",
            ("Keep", "Remove"),
        )
        return answer == "Remove"

    notify(f"flalac {__version__}: looking for changes in {settings.source.name}")
    try:
        summary = run(settings, progress, confirm, every=60.0)
    except OnceError as error:
        dialog(str(error), stop=True)
        return 1
    app = app_name()
    notify(f"Bringing the {app} library in step")
    db = Database(settings.config / "flalac.db")
    try:
        library = sync_library(settings, db, f"{app} library on {drive.name}", notify, app)
    except LibraryError as error:
        dialog(f"{summary.text()}\n\nThe {app} library could not be updated:\n{error}", stop=True)
        return 1
    finally:
        db.close()
    jellyfin = "" if settings.jellyfin_api_key else "\nPlay counts: Jellyfin is not set up."
    dialog(f"{summary.text()}\n\n{library.text()}{jellyfin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
