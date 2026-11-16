"""Audio conversion with ffmpeg, verified before the result replaces anything."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .media import AudioFacts, pcm_md5


class EncodeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Plan:
    args: list[str]
    lossless: bool  # True when decoded audio must be bit-identical to the source
    bits: int
    rate: int


def _target_rate(rate: int, limit: int) -> int:
    """Anything above MAX_SAMPLE_RATE is resampled to exactly that rate."""
    return rate if not limit or rate <= limit else limit


def plan(audio: AudioFacts, settings: Settings) -> Plan:
    bits = min(audio.bits, settings.max_bit_depth) if settings.max_bit_depth else audio.bits
    rate = _target_rate(audio.sample_rate, settings.max_sample_rate)
    filters = []
    if rate != audio.sample_rate or bits != audio.bits:
        out_fmt = "s16" if bits <= 16 else "s32"
        filters.append(f"aresample={rate}:osf={out_fmt}:dither_method=triangular")
    args = ["-af", ",".join(filters)] if filters else []
    if settings.target_format == "alac":
        args += ["-c:a", "alac", "-sample_fmt", "s16p" if bits <= 16 else "s32p", "-f", "ipod"]
    elif settings.target_format == "flac":
        args += [
            "-c:a",
            "flac",
            "-compression_level",
            "8",
            "-sample_fmt",
            "s16" if bits <= 16 else "s32",
            "-f",
            "flac",
        ]
    else:
        args += ["-c:a", "aac", "-b:a", f"{settings.aac_bitrate}k", "-f", "ipod"]
    lossless = settings.target_format != "aac" and not filters
    return Plan(args, lossless, bits, rate)


TEMP_MARK = ".flalac-tmp"


def temp_path(destination: Path) -> Path:
    """Hidden sibling that keeps the real extension, so taggers recognise the format."""
    return destination.with_name(f".{destination.stem}{TEMP_MARK}{destination.suffix}")


def encode(source: Path, destination: Path, audio: AudioFacts, settings: Settings) -> Plan:
    """Encode to a hidden temp file next to the destination and verify it.

    Returns with the temp file in place; the caller writes tags and then calls `publish`.
    """
    job = plan(audio, settings)
    tmp = temp_path(destination)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-vn",
        *job.args,
        str(tmp),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise EncodeError(result.stderr.strip()[-400:] or "ffmpeg failed")
    try:
        verify(source, tmp, audio, job)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return job


def verify(source: Path, encoded: Path, audio: AudioFacts, job: Plan) -> None:
    if job.lossless:
        # Decoding the output for its checksum is the whole check: a file that does not
        # decode cleanly cannot give the source's checksum.
        try:
            decoded = pcm_md5(encoded, job.bits)
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or "").strip()[:200]
            raise EncodeError(f"output does not decode cleanly: {detail}") from error
        if expected_md5(source, audio) != decoded:
            raise EncodeError("decoded audio differs from the source")
        return
    check = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(encoded), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0 or check.stderr.strip():
        raise EncodeError(f"output does not decode cleanly: {check.stderr.strip()[:200]}")


def expected_md5(source: Path, audio: AudioFacts) -> str:
    """MD5 of the source's decoded audio. A 16-bit FLAC carries exactly that checksum in its
    header (STREAMINFO), so the source is not read a second time, which halves the reading
    over a network share; anything else is decoded."""
    if audio.kind == "flac" and audio.bits == 16 and audio.stream_md5:
        return audio.stream_md5
    return pcm_md5(source, audio.bits)


def publish(tmp: Path, destination: Path) -> None:
    os.replace(tmp, destination)
