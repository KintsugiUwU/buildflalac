"""Runs passes: at start, after file changes have settled, and on a regular rescan."""

from __future__ import annotations

import threading

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .sync import Engine

# Only real changes. Reads produce "opened" / "closed_no_write" events on Linux; reacting to
# those would make every pass (which reads the files) trigger the next one.
CHANGES = frozenset({"created", "modified", "deleted", "moved", "closed"})


class _Changes(FileSystemEventHandler):
    def __init__(self, wake: threading.Event) -> None:
        self._wake = wake

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type not in CHANGES:
            return
        paths = [str(event.src_path), str(getattr(event, "dest_path", "") or "")]
        if any(p and not p.rsplit("/", 1)[-1].startswith(".") for p in paths):
            self._wake.set()


class Runner:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.watching = False
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="flalac-runner", daemon=True)
        self._observer: Observer | None = None

    def start(self) -> None:
        try:
            observer = Observer()
            observer.schedule(_Changes(self._wake), str(self.engine.s.source), recursive=True)
            observer.start()
            self._observer, self.watching = observer, True
        except Exception as error:  # e.g. inotify limits; the regular rescan still works
            self.engine.db.event("watch-unavailable", None, str(error)[:200])
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._observer:
            self._observer.stop()
        self._thread.join(timeout=30)

    def trigger(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        settings = self.engine.s
        removed = self.engine.remove_stale_temp_files()
        if removed:
            self.engine.db.event("cleanup", None, f"removed {removed} unfinished temp files")
        while not self._stop.is_set():
            plan = self.engine.run_pass()
            timeout = settings.rescan_minutes * 60 or None
            if plan is not None and plan.unsettled:
                timeout = settings.settle_seconds + 1
            elif plan is None and self.engine.status["phase"] == "paused":
                timeout = 60  # source missing: check again soon
            self._wake.wait(timeout)
            # Wait for a quiet moment so a tagger can finish writing a whole album.
            while not self._stop.is_set() and self._wake.is_set():
                self._wake.clear()
                self._stop.wait(settings.settle_seconds)
