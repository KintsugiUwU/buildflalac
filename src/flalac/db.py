"""SQLite state: what was mirrored, from which source, with which lyrics."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    rel TEXT PRIMARY KEY,          -- source path relative to the source root
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    identity TEXT NOT NULL,        -- audio identity, survives renames and tag edits
    tag_hash TEXT NOT NULL,
    target_rel TEXT,               -- mirrored file relative to the target root
    output_key TEXT,               -- encoding settings used for the target
    lyrics_source TEXT,
    lyrics_hash TEXT,              -- hash of the lyrics last written to the .txt
    lyrics_locked INTEGER NOT NULL DEFAULT 0,   -- user edited the .txt; never overwrite
    status TEXT NOT NULL,          -- synced | error
    error TEXT,
    updated REAL NOT NULL,
    lyrics_retry INTEGER NOT NULL DEFAULT 0     -- LRCLIB was unreachable; ask again later
);
CREATE INDEX IF NOT EXISTS tracks_identity ON tracks(identity);
CREATE TABLE IF NOT EXISTS lyrics_cache (
    key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    fetched REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    rel TEXT,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


@dataclass(slots=True)
class Track:
    rel: str
    size: int
    mtime: float
    identity: str
    tag_hash: str
    target_rel: str | None
    output_key: str | None
    lyrics_source: str | None
    lyrics_hash: str | None
    lyrics_locked: int
    status: str
    error: str | None
    updated: float
    lyrics_retry: int = 0


# Columns added after the first release, with their SQL definition.
MIGRATIONS = {"lyrics_retry": "INTEGER NOT NULL DEFAULT 0"}


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA)
            have = {row["name"] for row in self._conn.execute("PRAGMA table_info(tracks)")}
            for column, definition in MIGRATIONS.items():
                if column not in have:
                    self._conn.execute(f"ALTER TABLE tracks ADD COLUMN {column} {definition}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # tracks ------------------------------------------------------------
    def tracks(self) -> dict[str, Track]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM tracks").fetchall()
        return {row["rel"]: Track(**dict(row)) for row in rows}

    def get(self, rel: str) -> Track | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tracks WHERE rel=?", (rel,)).fetchone()
        return Track(**dict(row)) if row else None

    def save(self, track: Track) -> None:
        track.updated = time.time()
        fields = Track.__slots__
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO tracks ({','.join(fields)}) "
                f"VALUES ({','.join('?' * len(fields))})",
                tuple(getattr(track, f) for f in fields),
            )

    def owns_target(self, target_rel: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM tracks WHERE target_rel=? LIMIT 1", (target_rel,)
            ).fetchone()
        return row is not None

    def delete(self, rel: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM tracks WHERE rel=?", (rel,))

    def rename(self, old: str, new: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tracks SET rel=? WHERE rel=?", (new, old))

    # lyrics cache ------------------------------------------------------
    def cached_lyrics(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT text FROM lyrics_cache WHERE key=?", (key,)).fetchone()
        return row["text"] if row else None

    def cache_lyrics(self, key: str, text: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO lyrics_cache VALUES (?,?,?)", (key, text, time.time())
            )

    def ask_lrclib_again(self) -> int:
        """Forget LRCLIB answers without lyrics and mark songs whose lyrics did not come from
        LRCLIB, so the next pass asks again. Used once when the matching rules change."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM lyrics_cache WHERE json_valid(text)"
                " AND coalesce(json_extract(text, '$.plain'), '') = ''"
                " AND NOT coalesce(json_extract(text, '$.instrumental'), 0)"
            )
            return self._conn.execute(
                "UPDATE tracks SET lyrics_retry=1, updated=0 WHERE lyrics_locked=0"
                " AND lyrics_source IN ('lrc', 'txt', 'tag', 'none')"
            ).rowcount

    def ask_lyrics_again(self, rels: set[str]) -> None:
        """Choose the lyrics of these songs again on the next pass."""
        with self._lock:
            for rel in rels:
                self._conn.execute(
                    "UPDATE tracks SET lyrics_retry=1, updated=0 WHERE rel=?", (rel,)
                )

    # events ------------------------------------------------------------
    def event(self, kind: str, rel: str | None = None, detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts, kind, rel, detail) VALUES (?,?,?,?)",
                (time.time(), kind, rel, detail),
            )
            self._conn.execute("DELETE FROM events WHERE id < (SELECT MAX(id) - 5000 FROM events)")

    def events(self, limit: int = 200) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()

    # meta --------------------------------------------------------------
    def meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
