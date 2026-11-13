"""One pass of the mirror, then exit: for a computer that keeps the copy on an external drive.

The state (database, lyrics cache, no-lyrics.txt) lives in the config folder, which can sit on
the same drive as the copy, so the drive carries everything it needs from one Mac to another.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .config import Settings
from .db import Database
from .sync import Engine, Plan


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
        held = len(engine._held) if plan.held_deletes else 0
        if held and confirm_deletes(held):
            engine.confirm_deletes(held)  # exactly these; more vanishing meanwhile are held
            again = _pass(engine, progress, every)
            plan.deletes.extend(again.deletes)
            held = 0
        errors = sum(1 for t in db.tracks().values() if t.status == "error")
        return Summary(
            len(plan.encode),
            len(plan.retag),
            len(plan.moves),
            len(plan.deletes),
            errors,
            plan.unsettled,
            held,
            time.monotonic() - started,
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
