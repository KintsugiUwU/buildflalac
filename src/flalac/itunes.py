"""Keeps the iTunes (or Music) library in step with the copy on the drive, from the Mac app.

The decisions are the ones the Mac script gets from the server (macsync.MacSync): add new songs,
remove deleted ones, re-point renamed ones, refresh retagged ones (re-add those with a new
cover), and merge play counts with
Jellyfin. Here they run on the Mac itself and are applied through AppleScript, in batches.
iTunes is preferred when installed (for example iTunes 11.4 through Retroactive), so the
library on the drive stays in the format every Mac of the group can open.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .db import Database
from .jellyfin import Jellyfin
from .macsync import MacSync, MacTrack, Request, nfc

ADD_BATCH = 100
# A re-added song (new cover) counts as refreshed: to the person it is the same song, updated
COUNTED = {
    "remove": "removed",
    "move": "moved",
    "refresh": "refreshed",
    "readd": "refreshed",
    "plays": "plays",
}

READ = """on run argv
	set out to {}
	tell application "APP"
		with timeout of 900 seconds
			set lp to library playlist 1
			if (count of file tracks of lp) is 0 then return ""
			set pids to persistent ID of every file track of lp
			set counts to played count of every file track of lp
			set locs to location of every file track of lp
		end timeout
	end tell
	repeat with i from 1 to count of pids
		set p to ""
		try
			set p to POSIX path of (item i of locs)
		end try
		set end of out to (item i of pids) & tab & (item i of counts) & tab & p
	end repeat
	set AppleScript's text item delimiters to linefeed
	return out as text
end run
"""

APPLY = """on aliasOf(p)
	return (POSIX file p) as alias
end aliasOf

on run argv
	set txt to read (POSIX file (item 1 of argv)) as «class utf8»
	set failed to 0
	set AppleScript's text item delimiters to tab
	tell application "APP"
		with timeout of 1800 seconds
			set lp to library playlist 1
			repeat with ln in paragraphs of txt
				set parts to text items of (contents of ln)
				if (count of parts) > 1 then
					set k to item 1 of parts
					try
						set t to (first file track of lp whose persistent ID is (item 2 of parts))
						if k is "remove" then
							delete t
						else if k is "move" then
							set location of t to (POSIX file (item 3 of parts))
						else if k is "refresh" then
							refresh t
						else if k is "plays" then
							set played count of t to ((item 3 of parts) as integer)
						else if k is "readd" then
							-- new cover: Music keeps its cached one unless the song is re-added
							set f to my aliasOf(item 3 of parts)
							delete t
							set t to add f to lp
							set played count of t to ((item 4 of parts) as integer)
						end if
					on error
						set failed to failed + 1
					end try
				end if
			end repeat
		end timeout
	end tell
	return failed
end run
"""

ADD = """on run argv
	set txt to read (POSIX file (item 1 of argv)) as «class utf8»
	set files_ to {}
	set failed to 0
	repeat with p in paragraphs of txt
		if (length of p) > 0 then
			try
				set end of files_ to ((POSIX file (contents of p)) as alias)
			on error
				set failed to failed + 1
			end try
		end if
	end repeat
	tell application "APP"
		with timeout of 1800 seconds
			if files_ is not {} then add files_ to library playlist 1
		end timeout
	end tell
	return failed
end run
"""


class LibraryError(RuntimeError):
    pass


def app_name() -> str:
    """iTunes when it is installed (Mac OS X, or Retroactive on newer macOS), else Music."""
    if (
        Path("/Applications/iTunes.app").is_dir()
        or not Path("/System/Applications/Music.app").is_dir()
    ):
        return "iTunes"
    return "Music"


def _run(script: str, app: str, payload: str | None = None) -> str:
    with tempfile.TemporaryDirectory(prefix="flalac-") as folder:
        source = Path(folder) / "script.applescript"
        source.write_text(script.replace('"APP"', f'"{app}"'), encoding="utf-8")
        args = ["osascript", str(source)]
        if payload is not None:
            data = Path(folder) / "payload.txt"
            data.write_text(payload, encoding="utf-8")
            args.append(str(data))
        result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise LibraryError(f"{app}: {result.stderr.strip()}")
    return result.stdout.strip()


def read_library(app: str) -> list[MacTrack]:
    tracks = []
    for line in _run(READ, app).splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            plays = int(parts[1]) if parts[1].isdigit() else 0
            tracks.append(MacTrack(parts[0], plays, nfc("\t".join(parts[2:]))))
    return tracks


@dataclass
class LibraryResult:
    added: int = 0
    removed: int = 0
    moved: int = 0
    refreshed: int = 0
    plays: int = 0
    failed: int = 0
    notes: list[str] | None = None

    def text(self) -> str:
        line = (
            f"Library: {self.added} added, {self.removed} removed, {self.moved} re-pointed, "
            f"{self.refreshed} refreshed, {self.plays} play counts set."
        )
        if self.failed:
            line += f"\n{self.failed} library changes failed; they are tried again next time."
        return "\n".join([line, *(self.notes or [])])


def sync_library(
    settings: Settings,
    db: Database,
    library: str,
    progress: Callable[[str], None] = lambda message: None,
    app: str | None = None,
) -> LibraryResult:
    """Bring the open iTunes/Music library in step with the copy in settings.target.
    `library` names the play count memory (one per library, not per Mac)."""
    app = app or app_name()
    syncer = MacSync(settings, db, Jellyfin.from_settings(settings))
    result = LibraryResult(notes=[])
    for _ in range(2):  # songs added in the first round get their play counts in the second
        tracks = read_library(app)
        actions = syncer.sync(Request(library, nfc(str(settings.target)), tracks))
        adds = [a.split("\t", 1)[1] for a in actions if a.startswith("add\t")]
        changes = [a for a in actions if a.split("\t", 1)[0] in COUNTED]
        result.notes = [a.split("\t", 1)[1] for a in actions if a.startswith("info\t")]
        for action in changes:
            field = COUNTED[action.split("\t", 1)[0]]
            setattr(result, field, getattr(result, field) + 1)
        if changes:
            result.failed += int(_run(APPLY, app, "\n".join(changes)) or 0)
        for start in range(0, len(adds), ADD_BATCH):
            batch = adds[start : start + ADD_BATCH]
            result.failed += int(_run(ADD, app, "\n".join(batch)) or 0)
            result.added += len(batch)
            progress(f"{min(start + ADD_BATCH, len(adds))} of {len(adds)} added to {app}")
        if not adds:
            break
    return result
