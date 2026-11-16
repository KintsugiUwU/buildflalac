"""Work out what changed in the source and bring the target in line with it.

Safety rules:
- the source is only ever read;
- files are processed only after they have stopped changing (settle time);
- nothing is deleted when the source looks missing, and a pass that would delete more than
  DELETE_GUARD_PERCENT of the library is held until someone confirms it;
- files in the target that flalac did not create are never overwritten or deleted;
- a .txt edited by hand next to a target file is never overwritten.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
import unicodedata
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import encode, lyrics, media
from .config import Settings
from .db import Database, Track

SOURCE_SUFFIXES = (".flac", ".m4a")
NO_LYRICS_FILE = "no-lyrics.txt"
SCAN_LOOKUPS = 16  # file lookups in flight at once while scanning (network round trips overlap)
LRCLIB_RULES = "2"  # bump when lyrics.lookup() finds more, so earlier misses are asked again
LYRICS_RETRY_SECONDS = 3600  # ask LRCLIB again at most once an hour after it was unreachable
LRCLIB_PAUSE_SECONDS = 600  # after a failure, skip LRCLIB this long
LRCLIB_MISS_SECONDS = 30 * 86400  # LRCLIB had nothing: ask again after this long (it grows)
LRCLIB_MISS_SPREAD = (
    7 * 86400
)  # ...plus up to this, fixed per song, so they don't all come due at once


@dataclass(frozen=True, slots=True)
class SourceFile:
    rel: str
    path: Path
    size: int
    mtime: float
    side_mtime: float  # newest mtime of the .lrc/.txt next to it (0 when none)


@dataclass(slots=True)
class Plan:
    encode: list[SourceFile] = field(default_factory=list)
    retag: list[SourceFile] = field(default_factory=list)
    moves: list[tuple[str, SourceFile]] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    unsettled: int = 0
    held_deletes: bool = False

    @property
    def empty(self) -> bool:
        return not (self.encode or self.retag or self.moves or self.deletes)


class SourceMissingError(RuntimeError):
    pass


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def nfc(text: str) -> str:
    """Paths compare in one Unicode form: macOS and Linux spell accented names differently."""
    return unicodedata.normalize("NFC", text)


class Engine:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        client: lyrics.LrclibClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.s = settings
        self.db = db
        self.client = client if client is not None else lyrics.LrclibClient()
        self.clock = clock
        files = "on" if settings.lyrics_files else "off"
        if db.meta("lyrics_files", "on") != files:
            if not settings.lyrics_files:
                self._remove_lyrics_files()
            db.set_meta("lyrics_files", files)  # switched back on: missing files are rewritten
        if settings.lyrics == "lrclib" and db.meta("lrclib_rules") != LRCLIB_RULES:
            # Matching improved since these songs were looked up; ask LRCLIB again for them
            db.ask_lrclib_again()
            db.set_meta("lrclib_rules", LRCLIB_RULES)
        self.lock = threading.Lock()  # one pass at a time
        self.status: dict = {
            "phase": "idle",
            "done": 0,
            "total": 0,
            "current": "",
            "held_deletes": 0,
            "last_pass": None,
        }
        self._held: list[str] = []
        self._confirm_deletes = False
        self._confirm_count: int | None = None
        self._skipped: set[str] = set()
        self._lrclib_paused_until = 0.0

    # ---------------------------------------------------------------- lyrics style
    @property
    def lyrics_style(self) -> str:
        """The style chosen in the web UI, else LYRICS_STYLE from the environment."""
        chosen = self.db.meta("lyrics_style")
        return chosen if chosen in lyrics.STYLES else self.s.lyrics_style

    def set_lyrics_style(self, style: str) -> None:
        if style not in lyrics.STYLES:
            raise ValueError(f"unknown lyrics style {style!r}")
        self.db.set_meta("lyrics_style", style)

    def _sidecar(self, target_rel: str | None, source: str | None) -> Path:
        """The lyrics file flalac keeps next to a target: .lrc for synced, else .txt."""
        suffix = ".lrc" if source in lyrics.SYNCED_SOURCES else ".txt"
        return (self.s.target / (target_rel or "")).with_suffix(suffix)

    def _sidecars(self, target_rel: str | None) -> list[Path]:
        """The lyrics files (.lrc, .txt) that exist next to a target."""
        if not target_rel:
            return []
        base = self.s.target / target_rel
        return [p for p in (base.with_suffix(".lrc"), base.with_suffix(".txt")) if p.is_file()]

    def _edited_file(
        self, target_rel: str | None, source: str | None, unlike: str | None = None
    ) -> Path | None:
        """The lyrics file of a locked song: the kind last recorded, else the other. With
        `unlike` (the hash flalac wrote), a file that differs from it comes first: that is the
        one the user just added or changed."""
        if not target_rel:
            return None
        side = self._sidecar(target_rel, source)
        other = side.with_suffix(".txt" if side.suffix == ".lrc" else ".lrc")
        files = [p for p in (side, other) if p.is_file()]
        if unlike is not None:
            files.sort(key=lambda p: self._file_hash(p) == unlike)
        return files[0] if files else None

    @staticmethod
    def _file_hash(path: Path) -> str:
        return text_hash(path.read_text(encoding="utf-8", errors="replace").strip())

    def remove_stale_temp_files(self) -> int:
        """Temp files left by a crash or power cut; only flalac's own, never anything else."""
        removed = 0
        if self.s.target.is_dir():
            for path in self.s.target.rglob(f".*{encode.TEMP_MARK}*"):
                if path.is_file():
                    path.unlink()
                    removed += 1
        return removed

    # ---------------------------------------------------------------- scanning
    def _walk(self) -> dict[str, SourceFile]:
        root = self.s.source
        if not root.is_dir():
            raise SourceMissingError(f"source folder {root} is missing")
        if self.s.target.resolve().is_relative_to(root.resolve()):
            raise SourceMissingError(f"target folder {self.s.target} is inside the source")

        def unreadable(error: OSError) -> None:
            # A folder that can't be listed (network hiccup, permissions) must not make its
            # songs look deleted, so the whole pass stops instead.
            raise SourceMissingError(f"cannot read {error.filename}: {error.strerror}")

        paths: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root, onerror=unreadable):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            paths += [
                Path(dirpath) / name
                for name in filenames
                if not name.startswith(".") and name.lower().endswith(SOURCE_SUFFIXES)
            ]
        # Each lookup is a network round trip on a share; they overlap well, so run many at once.
        with ThreadPoolExecutor(max_workers=SCAN_LOOKUPS) as pool:
            entries = pool.map(self._source_file, paths)
        return {sf.rel: sf for sf in entries if sf is not None}

    def _source_file(self, path: Path) -> SourceFile | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        side = 0.0
        # Lyrics files next to the source matter only in sidecar mode; skipping the two lookups
        # per song keeps scans of a network share short.
        for suffix in (".lrc", ".txt") if self.s.lyrics != "lrclib" else ():
            with contextlib.suppress(FileNotFoundError):
                side = max(side, path.with_suffix(suffix).stat().st_mtime)
        rel = path.relative_to(self.s.source).as_posix()
        return SourceFile(rel, path, stat.st_size, stat.st_mtime, side)

    def target_rel(self, rel: str) -> str:
        return Path(rel).with_suffix(self.s.extension).as_posix()

    def scan(self) -> Plan:
        files = self._walk()
        known = self.db.tracks()
        if known and not files:
            raise SourceMissingError("source folder is empty while the mirror is not")
        plan = Plan()
        now = self.clock()
        restyle = self.db.meta("applied_lyrics_style", self.lyrics_style) != self.lyrics_style
        fresh: list[SourceFile] = []
        for rel, sf in files.items():
            if now - max(sf.mtime, sf.side_mtime) < self.s.settle_seconds:
                plan.unsettled += 1
                continue
            track = known.get(rel)
            if track is None:
                fresh.append(sf)
            elif (
                track.status != "synced"
                or track.output_key != self.s.output_key
                or not self._target_ok(track)
            ):
                plan.encode.append(sf)
            elif (sf.size, sf.mtime) != (track.size, track.mtime):
                try:
                    same_audio = self._identity(sf) == track.identity
                except Exception:
                    same_audio = False  # unreadable now; the encode step records the error
                (plan.retag if same_audio else plan.encode).append(sf)
            elif (
                restyle
                or self._lyrics_dirty(sf, track)
                or (track.lyrics_retry and now - track.updated > LYRICS_RETRY_SECONDS)
                or self._ask_lrclib_again(track, now)
            ):
                plan.retag.append(sf)
        gone = {rel: t for rel, t in known.items() if rel not in files}
        by_identity: dict[str, list[str]] = {}
        for rel, t in gone.items():
            by_identity.setdefault(t.identity, []).append(rel)
        with ThreadPoolExecutor(max_workers=SCAN_LOOKUPS) as pool:  # header reads, in parallel
            identities = list(pool.map(self._identity_or_error, fresh))
        for sf, identity in zip(fresh, identities, strict=True):
            if isinstance(identity, Exception):
                if sf.rel not in self._skipped:  # e.g. an AAC .m4a: not a lossless source
                    self._skipped.add(sf.rel)
                    self.db.event("skipped", sf.rel, str(identity)[:200])
                continue
            if by_identity.get(identity):
                old = by_identity[identity].pop()
                plan.moves.append((old, sf))
            else:
                plan.encode.append(sf)
        moved = {old for old, _ in plan.moves}
        deletes = [rel for rel in gone if rel not in moved]
        limit = max(3, len(known) * self.s.delete_guard_percent / 100)
        confirmed = self._confirm_deletes and self._confirm_count in (None, len(deletes))
        if len(deletes) > limit and not confirmed:
            plan.held_deletes = True
            self._held = deletes
        else:
            plan.deletes = deletes
        return plan

    def _identity_or_error(self, sf: SourceFile) -> str | Exception:
        try:
            return self._identity(sf)
        except Exception as error:
            return error

    def _identity(self, sf: SourceFile) -> str:
        audio = media.facts(sf.path)
        if audio is None:
            raise ValueError("not a supported lossless file")
        return media.audio_identity(sf.path, audio)

    def _target_ok(self, track: Track) -> bool:
        return bool(track.target_rel) and (self.s.target / track.target_rel).is_file()

    def _ask_lrclib_again(self, track: Track, now: float) -> bool:
        """LRCLIB had no lyrics a long time ago; it may have them by now."""
        return (
            self.s.lyrics == "lrclib"
            and track.lyrics_source == "none"
            and not track.lyrics_locked
            and now - track.updated > LRCLIB_MISS_SECONDS + self._spread(track.rel)
            and nfc(track.rel) not in self._no_lyrics()
        )

    @staticmethod
    def _spread(rel: str) -> int:
        return zlib.crc32(rel.encode()) % LRCLIB_MISS_SPREAD

    def _lyrics_dirty(self, sf: SourceFile, track: Track) -> bool:
        """Sidecars changed next to the source, or someone edited, added or removed a lyrics
        file next to the target."""
        if not self.s.lyrics_files:
            return sf.side_mtime > track.updated
        kept = self._edited_file(track.target_rel, track.lyrics_source)
        # A locked song is its one edited file; otherwise every lyrics file there counts
        sides = [kept] if track.lyrics_locked else self._sidecars(track.target_rel)
        if kept is None:
            if track.lyrics_hash and not track.lyrics_locked:
                return True  # our lyrics file disappeared; write it again
            sides = []
        for side in sides:
            # The file flalac recorded, with the same change stamp and size, still holds what
            # was recorded: no need to read every lyrics file on every scan. Nothing here
            # compares a file's time with the clock, so a file copied in with an old date
            # (Finder, cp -p) is noticed like any other.
            stat = self._stat_key(side)
            if side == kept and stat == track.lyrics_stat:
                continue
            if self._file_hash(side) != track.lyrics_hash:
                return True
            if side == kept:
                self.db.set_lyrics_stat(track.rel, stat)  # same text; remember how it looks
        return sf.side_mtime > track.updated

    @staticmethod
    def _stat_key(path: Path) -> str:
        stat = path.stat()
        return f"{stat.st_ctime_ns}:{stat.st_size}"

    def _lyrics_stat(self, target_rel: str, source: str | None) -> str | None:
        """How the song's lyrics file looks now, for `Track.lyrics_stat`."""
        kept = self._edited_file(target_rel, source) if self.s.lyrics_files else None
        return self._stat_key(kept) if kept is not None else None

    # ---------------------------------------------------------------- applying
    def run_pass(self, log: Callable[[str], None] = lambda _: None) -> Plan | None:
        if not self.lock.acquire(blocking=False):
            return None
        try:
            self.status.update(phase="scanning", current="")
            try:
                self._apply_no_lyrics_changes()
                plan = self.scan()
                self.status["held_deletes"] = len(self._held) if plan.held_deletes else 0
                if plan.held_deletes:
                    self.db.event(
                        "deletes-held", None, f"{len(self._held)} deletions wait for confirmation"
                    )
                if self.s.dry_run:
                    self._report_dry_run(plan)
                elif not plan.empty:
                    self._apply(plan)
            except SourceMissingError as error:
                self.db.event("source-missing", None, str(error))
                self.status.update(phase="paused", current=str(error))
                return None
            except Exception as error:
                # Anything else (a permission error, a share that went away mid-scan) pauses this
                # pass too: the caller tries again later instead of stopping for good.
                message = f"pass failed: {type(error).__name__}: {error}"[:500]
                self.db.event("error", None, message)
                self.status.update(phase="paused", current=message)
                return None
            if not self.s.dry_run:
                self.db.set_meta("applied_lyrics_style", self.lyrics_style)
            self._confirm_deletes, self._confirm_count = False, None
            self.status.update(phase="idle", current="", last_pass=self.clock())
            return plan
        finally:
            self.lock.release()

    def confirm_deletes(self, count: int | None = None) -> None:
        """Let the held deletions go ahead on the next pass. With `count`, only if that pass
        would delete exactly that many songs (the number the person saw); otherwise they are
        held again."""
        self._confirm_deletes = True
        self._confirm_count = count

    def _report_dry_run(self, plan: Plan) -> None:
        for sf in plan.encode:
            self.db.event("would-encode", sf.rel)
        for sf in plan.retag:
            self.db.event("would-retag", sf.rel)
        for old, sf in plan.moves:
            self.db.event("would-move", sf.rel, f"from {old}")
        for rel in plan.deletes:
            self.db.event("would-delete", rel)

    def _apply(self, plan: Plan) -> None:
        jobs = [(self._encode, sf) for sf in plan.encode] + [(self._retag, sf) for sf in plan.retag]
        self.status.update(
            phase="working", done=0, total=len(jobs) + len(plan.moves) + len(plan.deletes)
        )
        for old, sf in plan.moves:
            self._guarded(self._move, old, sf)
        for rel in plan.deletes:
            self._guarded(self._delete, rel)
        with ThreadPoolExecutor(max_workers=self.s.workers) as pool:
            for future in [pool.submit(self._guarded, fn, sf) for fn, sf in jobs]:
                future.result()

    def _guarded(self, fn, *args) -> None:
        rel = args[-1].rel if isinstance(args[-1], SourceFile) else args[-1]
        self.status["current"] = rel
        try:
            fn(*args)
        except Exception as error:  # one bad file must not stop the pass
            message = f"{type(error).__name__}: {error}"[:500]
            self.db.event("error", rel, message)
            track = self.db.get(rel)
            if track is not None:
                track.status, track.error = "error", message
                self.db.save(track)
        finally:
            self.status["done"] += 1

    def _lyrics_for(
        self,
        sf: SourceFile,
        tags: media.Tags,
        seconds: float,
        target_rel: str,
        locked: bool,
        track: Track | None,
    ) -> lyrics.Lyrics:
        if nfc(sf.rel) in self._no_lyrics():
            return lyrics.Lyrics("", "none")
        if locked:
            source, written = (track.lyrics_source, track.lyrics_hash) if track else (None, None)
            newly = not (track and track.lyrics_locked)
            side = self._edited_file(target_rel, source, written if newly else None)
            if side is not None:
                text = side.read_text(encoding="utf-8", errors="replace").strip()
                return lyrics.Lyrics(text, "edited-synced" if side.suffix == ".lrc" else "edited")
        return lyrics.choose(sf.path, tags, seconds, self.s.lyrics, self.lyrics_style, self._online)

    def _no_lyrics(self) -> set[str]:
        """Songs that never get lyrics (an instrumental version LRCLIB has words for), one
        source path per line in CONFIG_DIR/no-lyrics.txt, as shown in the web UI."""
        path = self.s.config / NO_LYRICS_FILE
        if not path.is_file():
            return set()
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {nfc(line.strip()) for line in lines if line.strip() and not line.startswith("#")}

    def _apply_no_lyrics_changes(self) -> None:
        """Songs added to or removed from no-lyrics.txt get their lyrics chosen again."""
        now = self._no_lyrics()
        before = set(filter(None, self.db.meta("no_lyrics").split("\n")))
        if now != before:
            changed = now ^ before
            # The database keeps paths as the file system spells them
            self.db.ask_lyrics_again({rel for rel in self.db.tracks() if nfc(rel) in changed})
            self.db.set_meta("no_lyrics", "\n".join(sorted(now)))

    def _online(self, title: str, artist: str, seconds: float) -> lyrics.Answer | None:
        """LRCLIB's answer, cached; None (and nothing cached) when LRCLIB can't be reached."""
        key = f"{lyrics._norm(artist)}|{lyrics._norm(title)}|{round(seconds)}"
        cached = self.db.cached_lyrics(key)
        if cached is not None and cached.startswith("{"):
            data = json.loads(cached)
            answer = (
                lyrics.Answer(data["plain"], data["synced"], bool(data["instrumental"]))
                if "plain" in data  # entries from before synced support are asked again
                else None
            )
            fetched = self.db.cached_lyrics_time(key)
            if answer and (answer.found or self.clock() - fetched < LRCLIB_MISS_SECONDS):
                return answer
        if self.clock() < self._lrclib_paused_until:
            return None  # LRCLIB failed recently; don't make every song wait for it
        try:
            answer = lyrics.lookup(self.client.search(title, artist), title, artist, seconds)
            main = lyrics.main_artist(artist)
            if not answer.found and main and lyrics._norm(main) != lyrics._norm(artist):
                # LRCLIB's search is picky about full credits ("X feat. Y"); the same
                # recording is often listed under another credit. lookup() still requires the
                # same title, a shared artist and a length within 2 seconds.
                answer = lyrics.lookup(self.client.search(title, main), title, artist, seconds)
        except lyrics.LrclibUnavailable as error:
            self._lrclib_paused_until = self.clock() + LRCLIB_PAUSE_SECONDS
            self.db.event(
                "lyrics-later",
                None,
                f"LRCLIB unavailable ({error}); local lyrics for now, asking again later",
            )
            return None
        data = {"plain": answer.plain, "synced": answer.synced, "instrumental": answer.instrumental}
        self.db.cache_lyrics(key, json.dumps(data))
        return answer

    def _write_sidecar(
        self, target_rel: str, chosen: lyrics.Lyrics, locked: bool, written: str | None
    ) -> str | None:
        """Write the lyrics file next to the target (.txt or .lrc) and drop the other kind.
        `written` is the hash of what flalac wrote last time: only a file still holding exactly
        that is flalac's to remove; anything else next to the target is the user's."""

        def remove_ours(path: Path) -> None:
            if written and path.is_file() and self._file_hash(path) == written:
                path.unlink()

        if not self.s.lyrics_files:
            return text_hash(chosen.text.strip()) if chosen.text else None
        if locked:
            # The user's file stays as it is; a stale one flalac wrote of the other kind goes.
            edited = self._edited_file(target_rel, chosen.source)
            for side in self._sidecars(target_rel):
                if side != edited:
                    remove_ours(side)
            return text_hash(chosen.text.strip())
        side = self._sidecar(target_rel, chosen.source)
        remove_ours(side.with_suffix(".txt" if side.suffix == ".lrc" else ".lrc"))
        if chosen.text:
            tmp = encode.temp_path(side)
            tmp.write_text(chosen.text + "\n", encoding="utf-8")
            os.replace(tmp, side)
            return text_hash(chosen.text.strip())
        remove_ours(side)
        return None

    def _remove_lyrics_files(self) -> None:
        """LYRICS_FILES=off: delete the lyrics files flalac wrote next to the targets. Files the
        user edited (locked) stay, and so do files whose text is not what flalac wrote."""
        removed = 0
        for track in self.db.tracks().values():
            if track.lyrics_locked or not track.target_rel or not track.lyrics_hash:
                continue
            side = self._sidecar(track.target_rel, track.lyrics_source)
            if side.is_file():
                text = side.read_text(encoding="utf-8", errors="replace").strip()
                if text_hash(text) == track.lyrics_hash:
                    side.unlink()
                    removed += 1
        self.db.event("lyrics-files-removed", None, f"{removed} lyrics files removed")

    def _detect_edit(self, track: Track | None, target_rel: str) -> bool:
        """True when the lyrics file next to the target is the user's: flalac's file changed
        by hand, or a file the user added (also where flalac found no lyrics)."""
        if track and track.lyrics_locked:
            return True
        if not self.s.lyrics_files:
            return False
        written = track.lyrics_hash if track else None
        return any(self._file_hash(side) != written for side in self._sidecars(target_rel))

    def _encode(self, sf: SourceFile) -> None:
        audio = media.facts(sf.path)
        if audio is None:
            raise ValueError("not a supported lossless file (FLAC or ALAC)")
        previous = self.db.get(sf.rel)
        target_rel = self.target_rel(sf.rel)
        target = self.s.target / target_rel
        if target.exists() and not self.db.owns_target(target_rel):
            raise FileExistsError(f"{target_rel} already exists and was not made by flalac")
        identity = media.audio_identity(sf.path, audio)
        tags = media.read_tags(sf.path)
        locked = self._detect_edit(previous, target_rel)
        chosen = self._lyrics_for(sf, tags, audio.seconds, target_rel, locked, previous)
        self.status["current"] = sf.rel
        tmp = encode.temp_path(target)
        try:
            encode.encode(sf.path, target, audio, self.s)
            media.write_tags(tmp, tags, chosen.text)
            encode.publish(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        if previous and previous.target_rel and previous.target_rel != target_rel:
            # Output format changed. The lyrics files next to it are the same ones the new
            # target uses (same name, other extension), so they stay.
            self._remove_target(previous.target_rel, keep_lyrics=True)
        written = previous.lyrics_hash if previous else None
        lyrics_hash = self._write_sidecar(target_rel, chosen, locked, written)
        self.db.save(
            Track(
                sf.rel,
                sf.size,
                sf.mtime,
                identity,
                tags.fingerprint(),
                target_rel,
                self.s.output_key,
                chosen.source,
                lyrics_hash,
                int(locked),
                "synced",
                None,
                0,
                int(chosen.retry),
                time.time(),
                self._lyrics_stat(target_rel, chosen.source),
            )
        )
        self.db.event("encoded", sf.rel, chosen.source)

    def _retag(self, sf: SourceFile) -> None:
        track = self.db.get(sf.rel)
        audio = media.facts(sf.path)
        if track is None or audio is None or not track.target_rel:
            return self._encode(sf)
        target = self.s.target / track.target_rel
        tags = media.read_tags(sf.path)
        locked = self._detect_edit(track, track.target_rel)
        chosen = self._lyrics_for(sf, tags, audio.seconds, track.target_rel, locked, track)
        fingerprint = tags.fingerprint()
        embedded = text_hash(chosen.text.strip()) if chosen.text else None
        # A retag that finds the same tags and lyrics (LRCLIB asked again and still has nothing,
        # a tag flalac does not copy was edited) leaves the copy alone: no rewrite for backups
        # to pick up, nothing for iTunes to refresh.
        same = (
            track.status == "synced"
            and (fingerprint, embedded) == (track.tag_hash, track.lyrics_hash)
            and target.is_file()
        )
        if not same:
            media.write_tags(target, tags, chosen.text)
            track.changed = time.time()
        track.lyrics_hash = self._write_sidecar(track.target_rel, chosen, locked, track.lyrics_hash)
        track.lyrics_locked = int(locked)
        track.size, track.mtime, track.tag_hash = sf.size, sf.mtime, fingerprint
        track.lyrics_source, track.status, track.error = chosen.source, "synced", None
        track.lyrics_retry = int(chosen.retry)
        track.lyrics_stat = self._lyrics_stat(track.target_rel, chosen.source)
        self.db.save(track)
        self.db.event("retagged" if not same else "checked", sf.rel, chosen.source)

    def _move(self, old: str, sf: SourceFile) -> None:
        track = self.db.get(old)
        if track is None:
            return self._encode(sf)
        new_rel = self.target_rel(sf.rel)
        if track.target_rel and track.target_rel != new_rel:
            src = self.s.target / track.target_rel
            dst = self.s.target / new_rel
            if dst.exists():
                raise FileExistsError(f"cannot move to {new_rel}: it already exists")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                os.replace(src, dst)
            for suffix in (".txt", ".lrc"):
                side = src.with_suffix(suffix)
                if side.is_file():
                    os.replace(side, dst.with_suffix(suffix))
            self._prune(src.parent)
        changed = (sf.size, sf.mtime) != (track.size, track.mtime) or sf.side_mtime > track.updated
        self.db.rename(old, sf.rel)
        track = self.db.get(sf.rel)
        track.target_rel = new_rel
        track.lyrics_stat = self._lyrics_stat(new_rel, track.lyrics_source)  # renamed with it
        self.db.save(track)
        self.db.event("moved", sf.rel, f"from {old}")
        if changed:
            self._retag(sf)

    def _delete(self, rel: str) -> None:
        track = self.db.get(rel)
        if track and track.target_rel:
            self._remove_target(track.target_rel)
        self.db.delete(rel)
        self.db.event("deleted", rel)

    def _remove_target(self, target_rel: str, keep_lyrics: bool = False) -> None:
        target = self.s.target / target_rel
        target.unlink(missing_ok=True)
        if not keep_lyrics:
            target.with_suffix(".txt").unlink(missing_ok=True)
            target.with_suffix(".lrc").unlink(missing_ok=True)
        self._prune(target.parent)

    def _prune(self, folder: Path) -> None:
        """Remove folders emptied by a move or delete, never the target root."""
        root = self.s.target.resolve()
        folder = folder.resolve()
        while folder != root and root in folder.parents:
            try:
                folder.rmdir()
            except OSError:
                return
            folder = folder.parent
