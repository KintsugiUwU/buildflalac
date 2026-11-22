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
    lyrics_retry INTEGER NOT NULL DEFAULT 0,    -- LRCLIB was unreachable; ask again later
    changed REAL NOT NULL DEFAULT 0,            -- when the copy's audio or tags last changed
    lyrics_stat TEXT,                           -- change stamp and size of the lyrics file
    art_hash TEXT,                              -- hash of the cover in the copy (NULL: not known)
    art_changed REAL NOT NULL DEFAULT 0         -- when the copy's cover last changed
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
CREATE TABLE IF NOT EXISTS macs (name TEXT PRIMARY KEY, last_sync REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mac_tracks (   -- play count memory per Mac library and track
    mac TEXT NOT NULL,
    pid TEXT NOT NULL,             -- the track's persistent ID in that library
    identity TEXT NOT NULL,        -- audio identity of the mirrored song
    agreed INTEGER NOT NULL,       -- the total both sides agreed on
    last_music INTEGER NOT NULL,   -- the Mac's count when last synced
    last_jelly INTEGER NOT NULL,   -- Jellyfin's count when last synced
    PRIMARY KEY (mac, pid)
);
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
    changed: float = 0.0  # 0 in rows from before this column: `updated` stands in
    lyrics_stat: str | None = None  # the lyrics file as last seen, to spot edits without reading
    art_hash: str | None = None  # None in rows from before this column: the first write sets it
    art_changed: float = 0.0  # when the cover changed; the Mac library then re-adds the song


@dataclass(frozen=True, slots=True)
class MacMemory:
    identity: str
    agreed: int
    last_music: int
    last_jelly: int  # UNPAIRED: the track was not in Jellyfin; the first pairing takes the larger


UNPAIRED = -1

# Columns added after the first release, with their SQL definition.
MIGRATIONS = {
    "lyrics_retry": "INTEGER NOT NULL DEFAULT 0",
    "changed": "REAL NOT NULL DEFAULT 0",
    "lyrics_stat": "TEXT",
    "art_hash": "TEXT",
    "art_changed": "REAL NOT NULL DEFAULT 0",
}


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

    def set_lyrics_stat(self, rel: str, stat: str | None) -> None:
        with self._lock:
            self._conn.execute("UPDATE tracks SET lyrics_stat=? WHERE rel=?", (stat, rel))

    def rename(self, old: str, new: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tracks SET rel=? WHERE rel=?", (new, old))

    # lyrics cache ------------------------------------------------------
    def cached_lyrics(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT text FROM lyrics_cache WHERE key=?", (key,)).fetchone()
        return row["text"] if row else None

    def cached_lyrics_time(self, key: str) -> float:
        """When this answer was fetched (0 when it isn't cached)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT fetched FROM lyrics_cache WHERE key=?", (key,)
            ).fetchone()
        return float(row["fetched"]) if row else 0.0

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

    # Macs --------------------------------------------------------------
    def mac_memory(self, mac: str) -> dict[str, MacMemory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT pid, identity, agreed, last_music, last_jelly FROM mac_tracks WHERE mac=?",
                (mac,),
            ).fetchall()
        return {r["pid"]: MacMemory(r[1], r[2], r[3], r[4]) for r in rows}

    def macs(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT m.name, m.last_sync, count(t.pid) AS tracks FROM macs m"
                " LEFT JOIN mac_tracks t ON t.mac = m.name GROUP BY m.name ORDER BY m.name"
            ).fetchall()

    def mac_last_sync(self, mac: str) -> float:
        with self._lock:
            row = self._conn.execute("SELECT last_sync FROM macs WHERE name=?", (mac,)).fetchone()
        return float(row["last_sync"]) if row else 0.0

    def save_mac_sync(self, mac: str, memory: dict[str, MacMemory], when: float) -> None:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                self._conn.execute("DELETE FROM mac_tracks WHERE mac=?", (mac,))
                self._conn.executemany(
                    "INSERT INTO mac_tracks VALUES (?,?,?,?,?,?)",
                    [
                        (mac, pid, m.identity, m.agreed, m.last_music, m.last_jelly)
                        for pid, m in memory.items()
                    ],
                )
                self._conn.execute("INSERT OR REPLACE INTO macs VALUES (?,?)", (mac, when))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

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
