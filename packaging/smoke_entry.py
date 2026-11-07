"""Self-test of the macOS bundle: flalac imports and the bundled ffmpeg turns FLAC into ALAC.

It is the app's entry while src/flalac/macapp.py does not exist, and runs in any build when
the app is started with FLALAC_SMOKE_TEST=1:

    env -i PATH=/usr/bin:/bin FLALAC_SMOKE_TEST=1 packaging/dist/flalac.app/Contents/MacOS/flalac
"""

from __future__ import annotations

import importlib
import math
import pkgutil
import platform
import shutil
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

from launcher import bundle_dir, use_bundled_ffmpeg

import flalac
from flalac.media import pcm_md5

RATE = 44100


def ffmpeg(*args: str) -> subprocess.CompletedProcess[str]:
    """Run `ffmpeg` by name, the way flalac does."""
    command = ["ffmpeg", "-nostdin", "-hide_banner", *args]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip()[-400:]}")
    return result


def tone(path: Path) -> None:
    """One second of a 440 Hz sine, 16-bit stereo, as raw little-endian PCM."""
    samples = array("h")
    for n in range(RATE):
        value = round(12000 * math.sin(2 * math.pi * 440 * n / RATE))
        samples.extend((value, value))
    if sys.byteorder != "little":
        samples.byteswap()
    path.write_bytes(samples.tobytes())


def smoke() -> int:
    try:
        print(f"flalac {flalac.__version__}, Python {platform.python_version()}")
        names = [m.name for m in pkgutil.iter_modules(flalac.__path__, "flalac.")]
        for name in names:
            importlib.import_module(name)
        print(f"imported {len(names)} flalac modules: {', '.join(sorted(names))}")

        found = shutil.which("ffmpeg")
        print(f"ffmpeg on PATH: {found}")
        bundle = bundle_dir()
        if found is None:
            raise RuntimeError("no ffmpeg on PATH")
        if bundle is not None and not Path(found).resolve().is_relative_to(bundle.resolve()):
            raise RuntimeError(f"ffmpeg {found} is not the one inside the app ({bundle})")
        print(ffmpeg("-version").stdout.splitlines()[0])
        encoders = [line for line in ffmpeg("-encoders").stdout.splitlines() if "alac" in line]
        print("encoders | grep alac:", *encoders, sep="\n  ")
        if not any(line.split()[1:2] == ["alac"] for line in encoders):
            raise RuntimeError("ffmpeg has no native alac encoder")

        with tempfile.TemporaryDirectory(prefix="flalac-smoke-") as tmp:
            raw, flac, alac = Path(tmp, "tone.raw"), Path(tmp, "tone.flac"), Path(tmp, "tone.m4a")
            tone(raw)
            ffmpeg("-f", "s16le", "-ar", str(RATE), "-ac", "2", "-i", str(raw), str(flac))
            # The same arguments flalac's encode.plan() uses for a 16-bit ALAC target.
            ffmpeg(
                "-i", str(flac), "-map", "0:a:0", "-vn",
                "-c:a", "alac", "-sample_fmt", "s16p", "-f", "ipod", str(alac),
            )  # fmt: skip
            probe = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(alac)],
                capture_output=True,
                text=True,
            ).stderr
            stream = next((line.strip() for line in probe.splitlines() if "Audio:" in line), "")
            print(f"FLAC {flac.stat().st_size} bytes -> ALAC {alac.stat().st_size} bytes: {stream}")
            if "Audio: alac" not in stream:
                raise RuntimeError("the output is not ALAC")
            source_md5, alac_md5 = pcm_md5(flac, 16), pcm_md5(alac, 16)
            print(f"decoded PCM MD5 (flalac.media.pcm_md5): FLAC {source_md5}, ALAC {alac_md5}")
            if source_md5 != alac_md5:
                raise RuntimeError("the ALAC copy does not decode to the same audio")
    except Exception as error:
        print(f"SMOKE TEST FAILED: {error}", file=sys.stderr)
        return 1
    print("SMOKE TEST OK: bit-identical FLAC -> ALAC with the bundled ffmpeg")
    return 0


if __name__ == "__main__":
    use_bundled_ffmpeg()
    sys.exit(smoke())
