"""Settings read from environment variables."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

FORMATS = ("alac", "flac", "aac")
LYRICS_MODES = ("lrclib", "sidecar", "off")
LYRICS_STYLES = ("plain", "synced")


class SettingsError(ValueError):
    pass


def _int(env: Mapping[str, str], key: str, default: int, minimum: int = 0) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise SettingsError(f"{key} must be a whole number, got {raw!r}") from error
    if value < minimum:
        raise SettingsError(f"{key} must be at least {minimum}, got {value}")
    return value


def _choice(env: Mapping[str, str], key: str, default: str, choices: tuple[str, ...]) -> str:
    value = env.get(key, default).strip().lower() or default
    if value not in choices:
        raise SettingsError(f"{key} must be one of {', '.join(choices)}, got {value!r}")
    return value


def _flag(env: Mapping[str, str], key: str) -> bool:
    return env.get(key, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class Settings:
    source: Path = Path("/source")
    target: Path = Path("/target")
    config: Path = Path("/config")
    target_format: str = "alac"
    aac_bitrate: int = 256
    max_bit_depth: int = 16  # 0 keeps the source bit depth
    max_sample_rate: int = 48000  # 0 keeps the source sample rate
    workers: int = 2
    rescan_minutes: int = 30
    settle_seconds: int = 10
    lyrics: str = "lrclib"
    lyrics_style: str = "plain"
    delete_guard_percent: int = 5
    auth_token: str = ""
    dry_run: bool = False
    host: str = "0.0.0.0"
    port: int = 8090

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        return cls(
            source=Path(env.get("SOURCE_DIR", "/source")),
            target=Path(env.get("TARGET_DIR", "/target")),
            config=Path(env.get("CONFIG_DIR", "/config")),
            target_format=_choice(env, "TARGET_FORMAT", "alac", FORMATS),
            aac_bitrate=_int(env, "AAC_BITRATE", 256, 64),
            max_bit_depth=_int(env, "MAX_BIT_DEPTH", 16),
            max_sample_rate=_int(env, "MAX_SAMPLE_RATE", 48000),
            workers=_int(env, "WORKERS", max(1, min(4, (os.cpu_count() or 2) // 2)), 1),
            rescan_minutes=_int(env, "RESCAN_MINUTES", 30),
            settle_seconds=_int(env, "SETTLE_SECONDS", 10),
            lyrics=_choice(env, "LYRICS", "lrclib", LYRICS_MODES),
            lyrics_style=_choice(env, "LYRICS_STYLE", "plain", LYRICS_STYLES),
            delete_guard_percent=_int(env, "DELETE_GUARD_PERCENT", 5),
            auth_token=env.get("AUTH_TOKEN", "").strip(),
            dry_run=_flag(env, "DRY_RUN"),
            host=env.get("HOST", "0.0.0.0"),
            port=_int(env, "PORT", 8090, 1),
        )

    @property
    def extension(self) -> str:
        return ".flac" if self.target_format == "flac" else ".m4a"

    @property
    def output_key(self) -> str:
        """Changes whenever settings that affect the encoded audio change."""
        raw = f"{self.target_format}|{self.aac_bitrate}|{self.max_bit_depth}|{self.max_sample_rate}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]
