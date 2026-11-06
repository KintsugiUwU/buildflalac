"""Shared fixtures: real audio files generated with ffmpeg, tagged with mutagen."""

from __future__ import annotations

import struct
import subprocess
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest
from mutagen.flac import FLAC, Picture

from flalac.config import Settings
from flalac.db import Database
from flalac.lyrics import LrclibUnavailable
from flalac.sync import Engine


def tiny_png(color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\0" + bytes(color) * 4 for _ in range(4))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def make_flac(
    path: Path,
    *,
    seconds: float = 2.0,
    rate: int = 44100,
    bits: int = 16,
    freq: int = 440,
    tags: dict[str, str | list[str]] | None = None,
    picture: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (
        ["-sample_fmt", "s16"]
        if bits == 16
        else ["-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
    )
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={seconds}:sample_rate={rate}",
            "-ac",
            "2",
            *fmt,
            "-c:a",
            "flac",
            str(path),
        ],
        check=True,
    )
    flac = FLAC(path)
    for key, value in (tags or {}).items():
        flac[key] = value
    if picture:
        pic = Picture()
        pic.data, pic.mime, pic.type = tiny_png(), "image/png", 3
        flac.add_picture(pic)
    flac.save()
    return path


def default_tags(title: str, track: int = 1) -> dict[str, str | list[str]]:
    return {
        "TITLE": title,
        "ARTIST": "Pola & Bryson × Emily Makis",
        "ALBUM": "Test Album",
        "ALBUMARTIST": "Pola & Bryson",
        "ARTISTS": ["Pola & Bryson", "Emily Makis"],
        "ALBUMARTISTS": ["Pola & Bryson"],
        "DATE": "2024-05-17",
        "GENRE": "Drum & Bass",
        "TRACKNUMBER": str(track),
        "TRACKTOTAL": "10",
        "TOTALTRACKS": "10",
        "DISCNUMBER": "1",
        "DISCTOTAL": "1",
        "MUSICBRAINZ_TRACKID": f"00000000-0000-0000-0000-00000000000{track}",
        "ACOUSTID_FINGERPRINT": "AQADtJKiKFPSMDhRHw1VH3",
    }


class FakeLrclib:
    def __init__(self, results: dict[tuple[str, str], list[dict]] | None = None) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, str]] = []

    down = False

    def search(self, title: str, artist: str) -> list[dict]:
        self.calls.append((title, artist))
        if self.down:
            raise LrclibUnavailable("HTTP 503")
        return self.results.get((title, artist), [])


@pytest.fixture
def workspace(tmp_path: Path):
    source, target, config = tmp_path / "source", tmp_path / "target", tmp_path / "config"
    source.mkdir()
    target.mkdir()
    return source, target, config


@pytest.fixture
def make_engine(workspace) -> Callable[..., Engine]:
    source, target, config = workspace
    engines: list[Engine] = []

    def build(client: FakeLrclib | None = None, **overrides) -> Engine:
        options = {"source": source, "target": target, "config": config}
        options |= {"settle_seconds": 0, "workers": 2, **overrides}
        settings = Settings(**options)
        engine = Engine(settings, Database(config / "flalac.db"), client or FakeLrclib())
        engines.append(engine)
        return engine

    yield build
    for engine in engines:
        engine.db.close()
