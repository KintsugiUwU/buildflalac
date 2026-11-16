"""Keeps each Mac's Music / iTunes library in step with the mirror, and its play counts in step
with Jellyfin.

The Mac runs a small AppleScript (static/flalac-mac.applescript) that sends one line per file
track and applies the answer, so every decision is made and tested here.

Request (UTF-8 text, tab-separated):
    mac   <name>
    root  <the mirror folder as this Mac sees it>
    track <persistent ID> <play count> <POSIX path, empty when the file is missing>
Answer, one action per line:
    add <path> | remove <id> | move <id> <path> | refresh <id> | plays <id> <count> | info <text>

Play counts follow the iOpenPod Jellyfin rule: a memory per Mac and track keeps the agreed
total and the count last seen on each side; the new total is the agreed one plus new plays on
either side. The first time a track is paired the larger count wins, and decreases are never
passed on. The memory is saved before Jellyfin is updated; a failed update is remembered with
Jellyfin's old count, so it is retried. A play can be missed after an interruption, never
counted twice.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass

from .config import Settings
from .db import Database, MacMemory, Track
from .jellyfin import Jellyfin, JellyfinError


@dataclass(frozen=True, slots=True)
class MacTrack:
    pid: str
    plays: int
    path: str


@dataclass(frozen=True, slots=True)
class Request:
    mac: str
    root: str
    tracks: list[MacTrack]


class RequestError(ValueError):
    pass


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def parse_request(text: str) -> Request:
    mac, root, tracks = "", "", []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        parts = line.split("\t")
        if parts[0] == "mac" and len(parts) > 1:
            mac = parts[1].strip()
        elif parts[0] == "root" and len(parts) > 1:
            root = nfc(parts[1].strip()).rstrip("/")
        elif parts[0] == "track" and len(parts) >= 4:
            try:
                plays = int(parts[2] or 0)
            except ValueError:
                plays = 0
            tracks.append(MacTrack(parts[1], plays, nfc("\t".join(parts[3:]))))
    if not mac or not root:
        raise RequestError("the request needs a 'mac' and a 'root' line")
    return Request(mac, root, tracks)


class MacSync:
    def __init__(self, settings: Settings, db: Database, jellyfin: Jellyfin | None) -> None:
        self.s = settings
        self.db = db
        self.jellyfin = jellyfin

    def sync(self, request: Request) -> list[str]:
        root = request.root
        mirrored: dict[str, Track] = {}
        by_identity: dict[str, Track] = {}
        for track in self.db.tracks().values():
            # Every song that has a copy, also one whose last retag or re-encode failed: its
            # copy is still there and playable. Leaving it out would remove it from the
            # library, and adding it back later loses its playlists, rating and date added.
            if track.target_rel:
                mirrored[nfc(track.target_rel)] = track
                by_identity[track.identity] = track
        memory = self.db.mac_memory(request.mac)
        last_sync = self.db.mac_last_sync(request.mac)
        jelly, info = {}, []
        if self.jellyfin is not None:
            try:
                jelly = self.jellyfin.play_counts()
            except JellyfinError as error:
                info.append(f"Jellyfin unreachable, play counts not synced: {error}")
                jelly = {}

        actions: list[str] = []
        seen: set[str] = set()
        new_memory: dict[str, MacMemory] = {}
        jelly_updates: list[tuple[str, str, int, int]] = []  # pid, item id, old, new
        for mac_track in request.tracks:
            inside = mac_track.path.startswith(root + "/")
            if mac_track.path and not inside:
                continue  # not a mirrored song; leave the rest of the library alone
            rel = mac_track.path[len(root) + 1 :] if inside else ""
            track = mirrored.get(rel)
            remembered = memory.get(mac_track.pid)
            if track is None:
                moved = by_identity.get(remembered.identity) if remembered else None
                if moved is not None and nfc(moved.target_rel or "") not in seen:
                    track, rel = moved, nfc(moved.target_rel or "")
                    actions.append(f"move\t{mac_track.pid}\t{root}/{rel}")
                elif inside or remembered:
                    actions.append(f"remove\t{mac_track.pid}")
                    continue
                else:
                    continue  # a missing file flalac never knew about
            if rel in seen:
                actions.append(f"remove\t{mac_track.pid}")  # a duplicate entry
                continue
            seen.add(rel)
            # `changed` is when the copy's tags or audio last changed; older rows only have
            # `updated`, which also moves when nothing in the file did
            if last_sync and (track.changed or track.updated) > last_sync:
                actions.append(f"refresh\t{mac_track.pid}")
            item = jelly.get(nfc(track.rel))
            if remembered and remembered.identity != track.identity:
                remembered = None
            if item is None:
                if remembered:
                    new_memory[mac_track.pid] = remembered
                continue
            music = mac_track.plays
            if remembered is None:
                agreed = max(music, item.plays)
            else:
                agreed = (
                    remembered.agreed
                    + max(0, music - remembered.last_music)
                    + max(0, item.plays - remembered.last_jelly)
                )
            if music != agreed:
                actions.append(f"plays\t{mac_track.pid}\t{agreed}")
            if item.plays != agreed:
                jelly_updates.append((mac_track.pid, item.id, item.plays, agreed))
            new_memory[mac_track.pid] = MacMemory(track.identity, agreed, agreed, agreed)

        for rel in sorted(set(mirrored) - seen):
            actions.append(f"add\t{root}/{rel}")

        self.db.save_mac_sync(request.mac, new_memory, time.time())
        failed = 0
        for pid, item_id, old, new in jelly_updates:
            try:
                assert self.jellyfin is not None
                self.jellyfin.set_play_count(item_id, new)
            except JellyfinError:
                failed += 1
                kept = new_memory[pid]
                new_memory[pid] = MacMemory(kept.identity, kept.agreed, kept.last_music, old)
        if failed:
            self.db.save_mac_sync(request.mac, new_memory, time.time())
            info.append(f"{failed} Jellyfin play counts could not be saved; retried next time")
        if jelly_updates:
            info.append(f"{len(jelly_updates) - failed} play counts updated in Jellyfin")
        self.db.event(
            "mac-sync",
            None,
            f"{request.mac}: {len(request.tracks)} tracks, {len(actions)} changes, "
            f"{len(jelly_updates) - failed} Jellyfin updates",
        )
        return actions + [f"info\t{text}" for text in info]
