"""Lyrics for the target files, plain or synced, from LRCLIB or local files.

LYRICS=lrclib (the default) asks LRCLIB only: plain style takes its plain lyrics as they are,
synced style its synced lyrics, falling back to plain. Files next to the source are never read.
LYRICS=sidecar uses only your own files instead: a timed .lrc for synced style, else your .txt,
else the .lrc without its timestamps, else lyrics already in the tags.

LRCLIB rules followed here (https://lrclib.net/docs): an identifying User-Agent, one request
at a time with a 200-500 ms pause, honour 429 Retry-After with jitter, and only accept
synced lyrics whose duration is within 2 seconds of the song. Plain lyrics don't depend on
timing, so an entry with the same title and artist but another length (an edit, a remaster)
is still used when nothing closer exists.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import USER_AGENT
from .media import Tags

TIMESTAMP = re.compile(r"\[(\d+):(\d+)(?:[.:](\d+))?\]")
LRC_HEADER = re.compile(r"^\[(ar|ti|al|au|by|offset|length|re|ve|#)\s*:.*\]\s*$", re.I)
WORD_TIMING = re.compile(r"<\d+:\d+(?:[.:]\d+)?>")
DURATION_TOLERANCE = 2.0
STYLES = ("plain", "synced")
SYNCED_SOURCES = frozenset({"lrc-synced", "lrclib-synced", "edited-synced"})


@dataclass(frozen=True, slots=True)
class Lyrics:
    text: str
    source: str  # txt, lrclib, lrc, tag, lrc-synced, lrclib-synced, instrumental, none
    retry: bool = False  # LRCLIB was unreachable; ask again on a later pass

    @property
    def synced(self) -> bool:
        return self.source in SYNCED_SOURCES


# ---------------------------------------------------------------- text


def _tidy(lines: list[str]) -> str:
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def lrc_to_text(raw: str) -> str:
    """Timed LRC to plain lyrics in time order, without adding any breaks of its own.
    Empty timed lines (instrumental gaps) become one blank line; untimed text passes through.
    """
    raw = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    timed: list[tuple[float, int, str]] = []
    plain: list[str] = []
    for order, line in enumerate(raw.split("\n")):
        if LRC_HEADER.match(line.strip()):
            continue
        stamps = list(TIMESTAMP.finditer(line))
        text = WORD_TIMING.sub("", TIMESTAMP.sub("", line)).strip()
        if stamps:
            for m in stamps:
                frac = m.group(3) or "0"
                seconds = int(m.group(1)) * 60 + int(m.group(2)) + int(frac) / 10 ** len(frac)
                timed.append((seconds, order, text))
        else:
            plain.append(text)
    if timed:
        timed.sort()
        return _tidy([text for _, _, text in timed])
    return _tidy(plain)


def clean_lrc(raw: str) -> str:
    """Synced lyrics kept as LRC: normalised line endings, no BOM, no trailing spaces."""
    lines = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def has_timestamps(text: str) -> bool:
    return bool(TIMESTAMP.search(text or ""))


def clean_plain(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return _tidy(["" if line.strip() in ("", "♪") else line.rstrip() for line in lines])


def blocks(text: str) -> int:
    return len([b for b in text.split("\n\n") if b.strip()]) if text else 0


# ---------------------------------------------------------------- LRCLIB


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("‐", "-"), ("–", "-")):
        value = value.replace(a, b)
    value = re.sub(r"\s*[\(\[](feat\.?|ft\.?|with)\b[^\)\]]*[\)\]]", "", value)
    value = value.replace("'", "")  # Livin' / Livin, It's / Its
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def _artists(*names: str) -> set[str]:
    found = set()
    for name in names:
        parts = re.split(
            r"\s*(?:,|&|\+|;|/|\bfeat\.?|\bft\.?|\bx\b|×|\band\b|\bwith\b)\s*",
            (name or "").casefold(),
        )
        # "The Mama's and the Papa's" and "The Mamas And Papas" are the same artists
        found |= {re.sub(r"^the ", "", _norm(p)) for p in parts if _norm(p)}
    return found


def main_artist(artist: str) -> str:
    """The first credited artist: 'Flume feat. Kai' -> 'Flume', 'A & B' -> 'A'."""
    separators = r"\s*(?:,|&|\+|;|/|\bfeat\.?|\bft\.?|\bx\b|×|\bwith\b)\s*"
    first = re.split(separators, artist or "", maxsplit=1)[0]
    return first.strip()


class LrclibUnavailable(RuntimeError):
    pass


class LrclibClient:
    def __init__(
        self,
        base: str = "https://lrclib.net",
        opener: Callable | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base = base
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._lock = threading.Lock()  # one request at a time across all workers
        self._last = 0.0

    def search(self, title: str, artist: str) -> list[dict]:
        """Matching entries, [] when LRCLIB has none; raises LrclibUnavailable when LRCLIB
        could not be reached, so the caller can try again later instead of caching "nothing".
        """
        query = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
        return self._get(f"/api/search?{query}")

    def _get(self, path: str) -> list[dict]:
        with self._lock:
            for attempt in range(5):
                wait = 0.2 + random.random() * 0.3 - (time.monotonic() - self._last)
                if wait > 0:
                    self._sleep(wait)
                request = urllib.request.Request(
                    self._base + path, headers={"User-Agent": USER_AGENT}
                )
                try:
                    with self._open(request, timeout=30) as response:
                        self._last = time.monotonic()
                        return json.load(response) or []
                except urllib.error.HTTPError as error:
                    self._last = time.monotonic()
                    if error.code == 404:
                        return []
                    if error.code in (429, 500, 502, 503, 504):
                        retry = float(error.headers.get("Retry-After") or 2**attempt)
                        self._sleep(retry * (1 + random.random() * 0.3))
                        continue
                    raise LrclibUnavailable(f"HTTP {error.code}") from error
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    self._last = time.monotonic()
                    self._sleep(2**attempt)
            raise LrclibUnavailable("no answer after 5 attempts")


@dataclass(frozen=True, slots=True)
class Answer:
    plain: str = ""
    synced: str = ""
    instrumental: bool = False

    @property
    def found(self) -> bool:
        return bool(self.plain or self.synced or self.instrumental)


TITLE_SUFFIX = re.compile(r"\s*(?:[\(\[][^\)\]]*[\)\]]|\s-\s.*)$")


def lookup(results: list[dict], title: str, artist: str, seconds: float) -> Answer:
    """LRCLIB's lyrics for this song, from entries with a shared artist, best match first:
    the same title within 2 s, the same title at another length (closest first), then a title
    that only adds a suffix ("Footloose (Footloose)") within 2 s. Among equally good entries the
    plain text with the most verse breaks wins. Synced lyrics need the length within 2 s."""
    wanted_title, wanted_artists = _norm(title), _artists(artist)
    ranked: list[tuple[tuple[int, int, float], dict]] = []
    instrumental = False
    for entry in results:
        if not (wanted_artists & _artists(entry.get("artistName", ""))):
            continue
        name = entry.get("trackName", "")
        off = abs((entry.get("duration") or 0) - seconds)
        close = off <= DURATION_TOLERANCE
        if _norm(name) == wanted_title:
            rank = (0, 0, 0.0) if close else (1, 0, off)
        elif close and _norm(TITLE_SUFFIX.sub("", name)) == wanted_title:
            rank = (2, 0, 0.0)
        else:
            continue
        if entry.get("instrumental"):
            instrumental = True
            continue
        ranked.append((rank, entry))
    plain, synced, best = "", "", None
    for rank, entry in sorted(ranked, key=lambda item: item[0]):
        text = clean_plain(entry.get("plainLyrics") or "")
        timed = clean_lrc(entry.get("syncedLyrics") or "") if rank[0] != 1 else ""
        if text and (best is None or (rank == best[0] and blocks(text) > best[1])):
            plain, best = text, (rank, blocks(text))
            synced = timed or synced
        elif timed and not synced:
            synced = timed
    return Answer(plain, synced, instrumental and not (plain or synced))


# ---------------------------------------------------------------- choosing


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def choose(
    source: Path,
    tags: Tags,
    seconds: float,
    mode: str,
    style: str = "plain",
    online: Callable[[str, str, float], Answer | None] | None = None,
) -> Lyrics:
    """`online` returns None when LRCLIB could not be reached; the result then asks for a retry."""
    if mode == "off":
        return Lyrics("", "none")
    if mode != "lrclib":
        return _from_files(source, tags, style)
    answer, retry = Answer(), False
    title, artist = tags.first("title"), tags.first("artist")
    if online is not None and title and artist:
        found = online(title, artist, seconds)
        answer, retry = (found, False) if found is not None else (Answer(), True)
    if style == "synced" and answer.synced:
        return Lyrics(answer.synced, "lrclib-synced")
    if answer.plain:
        return Lyrics(answer.plain, "lrclib")
    if answer.instrumental:
        return Lyrics("", "instrumental")
    return Lyrics("", "none", retry)


def _from_files(source: Path, tags: Tags, style: str) -> Lyrics:
    """LYRICS=sidecar: only the lyrics files next to the source, then the tags."""
    txt, lrc = _read(source.with_suffix(".txt")), _read(source.with_suffix(".lrc"))
    if style == "synced" and has_timestamps(lrc):
        return Lyrics(clean_lrc(lrc), "lrc-synced")
    if txt.strip():
        return Lyrics(lrc_to_text(txt), "txt")
    if lrc.strip():
        return Lyrics(lrc_to_text(lrc), "lrc")
    for key in ("unsyncedlyrics", "lyrics"):
        if tags.first(key):
            return Lyrics(lrc_to_text(tags.first(key)), "tag")
    return Lyrics("", "none")
