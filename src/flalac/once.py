"""One pass of the mirror, then exit: for a computer that keeps the copy on an external drive.

The state (database, lyrics cache, no-lyrics.txt) lives in the config folder, which can sit on
the same drive as the copy, so the drive carries everything it needs from one Mac to another.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .config import Settings
from .db import Database
from .sync import Engine, Plan, song_name


class OnceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Summary:
    encoded: int
    retagged: int
    moved: int
    deleted: int
    errors: int
    unsettled: int
    held_deletes: int  # deletions not confirmed; nothing was deleted
    seconds: float
    # Song by song: {"kind": converted|retagged|renamed|removed|failed, "song", "detail"?}
    songs: list[dict[str, str]] = field(default_factory=list)

    def text(self) -> str:
        parts = [
            f"{self.encoded} converted",
            f"{self.retagged} retagged",
            f"{self.moved} renamed",
            f"{self.deleted} removed",
        ]
        lines = [", ".join(parts) + f" in {self.seconds / 60:.0f} min."]
        if self.errors:
            lines.append(f"{self.errors} songs failed; see the log.")
        if self.unsettled:
            lines.append(f"{self.unsettled} songs were still being written; next run.")
        if self.held_deletes:
            lines.append(f"{self.held_deletes} removals waiting for your confirmation.")
        return "\n".join(lines)


def check(settings: Settings) -> None:
    """Everything a pass needs, with messages a person can act on."""
    if shutil.which("ffmpeg") is None:
        raise OnceError("ffmpeg was not found")
    if not settings.source.is_dir():
        raise OnceError(f"The FLAC folder {settings.source} is not reachable. Connect the share.")
    for label, folder in (("copy", settings.target), ("state", settings.config)):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise OnceError(
                f"The {label} folder {folder} can't be created ({error.strerror}). "
                "Connect the drive."
            ) from error


def run(
    settings: Settings,
    progress: Callable[[int, int, str], None] = lambda done, total, current: None,
    confirm_deletes: Callable[[int], bool] = lambda count: False,
    every: float = 30.0,
) -> Summary:
    """One full pass. `progress` is called every `every` seconds while songs are converted;
    `confirm_deletes(count)` decides whether an unusually large removal goes ahead."""
    check(settings)
    started = time.monotonic()
    db = Database(settings.config / "flalac.db")
    try:
        engine = Engine(settings, db)
        engine.remove_stale_temp_files()
        plan = _pass(engine, progress, every)
        songs = list(engine.done)
        held = len(engine._held) if plan.held_deletes else 0
        if held and confirm_deletes(held):
            engine.confirm_deletes(held)  # exactly these; more vanishing meanwhile are held
            _pass(engine, progress, every)
            songs += engine.done
            held = 0
        # Failed now (new songs have no row to mark) or still failing from an earlier run
        failed = {x["song"]: x for x in songs if x["kind"] == "failed"}
        for t in sorted(db.tracks().values(), key=lambda t: t.rel):
            if t.status == "error" and song_name(t.rel) not in failed:
                failed[song_name(t.rel)] = {
                    "kind": "failed",
                    "song": song_name(t.rel),
                    "detail": t.error or "",
                }
        songs = [x for x in songs if x["kind"] != "failed"] + list(failed.values())

        def count(kind: str) -> int:
            return sum(1 for song in songs if song["kind"] == kind)

        if settings.dry_run:  # nothing was done: say what would be
            return Summary(
                len(plan.encode),
                len(plan.retag),
                len(plan.moves),
                len(plan.deletes),
                count("failed"),
                plan.unsettled,
                held,
                time.monotonic() - started,
            )

        return Summary(
            count("converted"),
            count("retagged"),
            count("renamed"),
            count("removed"),
            count("failed"),
            plan.unsettled,
            held,
            time.monotonic() - started,
            songs,
        )
    finally:
        db.close()


def _pass(engine: Engine, progress: Callable[[int, int, str], None], every: float) -> Plan:
    result: dict[str, Plan | None] = {}
    worker = threading.Thread(target=lambda: result.update(plan=engine.run_pass()))
    worker.start()
    while worker.is_alive():
        worker.join(every)
        if worker.is_alive() and engine.status.get("total"):
            status = engine.status
            progress(int(status["done"]), int(status["total"]), str(status.get("current", "")))
    plan = result.get("plan")
    if plan is None:
        raise OnceError(str(engine.status.get("current") or "the pass could not run"))
    return plan
