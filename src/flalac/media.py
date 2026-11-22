"""Reading audio facts and tags from source files, and writing tags to targets.

Tags are kept in one neutral shape: lowercase Vorbis comment names mapped to lists of
strings, plus a list of pictures. FLAC files use that shape natively; MP4 (ALAC/AAC) files
are translated to and from it with the atom names iTunes and Picard use.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

# Tags that never travel to the target or never count as a change.
SKIPPED = frozenset({"acoustid_fingerprint", "encoder", "encoded_by", "encoder_settings"})
LYRICS_KEYS = ("unsyncedlyrics", "lyrics")

MP4_TEXT = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "album": "\xa9alb",
    "albumartist": "aART",
    "date": "\xa9day",
    "genre": "\xa9gen",
    "composer": "\xa9wrt",
    "comment": "\xa9cmt",
    "grouping": "\xa9grp",
    "titlesort": "sonm",
    "artistsort": "soar",
    "albumsort": "soal",
    "albumartistsort": "soaa",
    "composersort": "soco",
    "copyright": "cprt",
}
# Freeform names as Picard writes them in MP4 files.
MP4_FREEFORM = {
    "musicbrainz_trackid": "MusicBrainz Track Id",
    "musicbrainz_releasetrackid": "MusicBrainz Release Track Id",
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "musicbrainz_workid": "MusicBrainz Work Id",
    "releasetype": "MusicBrainz Album Type",
    "releasestatus": "MusicBrainz Album Status",
    "releasecountry": "MusicBrainz Album Release Country",
    "artists": "ARTISTS",
    "albumartists": "ALBUMARTISTS",
    "originaldate": "ORIGINALDATE",
    "originalyear": "ORIGINAL YEAR",
    "replaygain_track_gain": "replaygain_track_gain",
    "replaygain_track_peak": "replaygain_track_peak",
    "replaygain_album_gain": "replaygain_album_gain",
    "replaygain_album_peak": "replaygain_album_peak",
}
NUMBERS = {"tracknumber": "tracktotal", "discnumber": "disctotal"}
TOTAL_ALIASES = {"totaltracks": "tracktotal", "totaldiscs": "disctotal"}
HANDLED = set(MP4_TEXT) | {
    "tracknumber",
    "tracktotal",
    "discnumber",
    "disctotal",
    "compilation",
    *LYRICS_KEYS,
    *TOTAL_ALIASES,
}


@dataclass(slots=True)
class Art:
    data: bytes
    mime: str
    kind: int = 3  # front cover


@dataclass(slots=True)
class Tags:
    values: dict[str, list[str]] = field(default_factory=dict)
    pictures: list[Art] = field(default_factory=list)

    def first(self, key: str) -> str:
        found = self.values.get(key) or [""]
        return found[0]

    def fingerprint(self) -> str:
        """Stable hash of everything that should reach the target (lyrics excluded)."""
        digest = hashlib.sha1()
        for key in sorted(self.values):
            if key in SKIPPED or key in LYRICS_KEYS:
                continue
            digest.update(key.encode() + b"\0" + "\x1f".join(self.values[key]).encode() + b"\0")
        for art in self.pictures:
            digest.update(hashlib.sha1(art.data).digest())
        return digest.hexdigest()

    def art_hash(self) -> str:
        """Stable hash of the cover art alone ('' without any)."""
        if not self.pictures:
            return ""
        digest = hashlib.sha1()
        for art in self.pictures:
            digest.update(hashlib.sha1(art.data).digest())
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class AudioFacts:
    kind: str  # "flac" or "alac" (anything else is not a source)
    sample_rate: int
    bits: int
    channels: int
    seconds: float
    stream_md5: str  # FLAC STREAMINFO MD5, "" when absent


def _flac_streaminfo(path: Path) -> AudioFacts | None:
    """The STREAMINFO block every FLAC starts with, read directly: identifying a song needs these
    42 bytes, not the whole header with its cover art, which is much slower over a share."""
    with path.open("rb") as stream:
        head = stream.read(42)
    if len(head) < 42 or head[:4] != b"fLaC" or head[4] & 0x7F != 0:
        return None  # e.g. an ID3 tag in front; the full reader handles it
    block = head[8:42]
    rate = (block[10] << 12) | (block[11] << 4) | (block[12] >> 4)
    channels = ((block[12] >> 1) & 0x07) + 1
    bits = (((block[12] & 0x01) << 4) | (block[13] >> 4)) + 1
    samples = ((block[13] & 0x0F) << 32) | int.from_bytes(block[14:18], "big")
    if not rate or not samples:
        return None
    md5 = block[18:34].hex() if any(block[18:34]) else ""
    return AudioFacts("flac", rate, bits, channels, samples / rate, md5)


def facts(path: Path) -> AudioFacts | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".flac":
            fast = _flac_streaminfo(path)
            if fast is not None:
                return fast
            info = FLAC(path).info
            md5 = f"{info.md5_signature:032x}" if info.md5_signature else ""
            return AudioFacts(
                "flac", info.sample_rate, info.bits_per_sample, info.channels, info.length, md5
            )
        if suffix in (".m4a", ".mp4"):
            info = MP4(path).info
            if info.codec != "alac":
                return None
            return AudioFacts(
                "alac", info.sample_rate, info.bits_per_sample, info.channels, info.length, ""
            )
    except Exception:
        return None
    return None


def pcm_md5(path: Path, bits: int) -> str:
    """MD5 of the decoded audio, independent of container and tags."""
    codec = "pcm_s16le" if bits <= 16 else "pcm_s32le"
    out = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c:a",
            codec,
            "-f",
            "md5",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return out.removeprefix("MD5=")


def audio_identity(path: Path, audio: AudioFacts) -> str:
    """Identifies the recording itself; survives renames and tag edits."""
    if audio.stream_md5:
        return f"flac:{audio.stream_md5}"
    return f"pcm:{pcm_md5(path, audio.bits)}"


# ---------------------------------------------------------------- reading


def read_tags(path: Path) -> Tags:
    if path.suffix.lower() == ".flac":
        return _read_flac(path)
    return _read_mp4(path)


def _read_flac(path: Path) -> Tags:
    flac = FLAC(path)
    values: dict[str, list[str]] = {}
    for key in flac.tags.keys() if flac.tags else []:
        name = key.lower()
        name = TOTAL_ALIASES.get(name, name)
        if name in values and key.lower() in TOTAL_ALIASES:
            continue  # TRACKTOTAL and TOTALTRACKS carry the same number
        values[name] = [v for v in flac.tags[key] if v != ""]
    pictures = sorted(flac.pictures, key=lambda p: p.type != 3)
    return Tags(values, [Art(p.data, p.mime or "image/jpeg", p.type) for p in pictures])


def _read_mp4(path: Path) -> Tags:
    mp4 = MP4(path)
    tags = mp4.tags or {}
    values: dict[str, list[str]] = {}
    for name, atom in MP4_TEXT.items():
        if atom in tags:
            values[name] = [str(v) for v in tags[atom]]
    for name, total, atom in (
        ("tracknumber", "tracktotal", "trkn"),
        ("discnumber", "disctotal", "disk"),
    ):
        if atom in tags and tags[atom]:
            number, count = tags[atom][0]
            if number:
                values[name] = [str(number)]
            if count:
                values[total] = [str(count)]
    if tags.get("cpil"):
        values["compilation"] = ["1"]
    if "\xa9lyr" in tags:
        values["lyrics"] = [str(tags["\xa9lyr"][0])]
    reverse = {v.lower(): k for k, v in MP4_FREEFORM.items()}
    for atom, items in tags.items():
        if not atom.startswith("----:com.apple.iTunes:"):
            continue
        label = atom.split(":", 2)[2]
        name = reverse.get(label.lower(), label.lower())
        values[name] = [bytes(v).decode("utf-8", "replace") for v in items]
    pictures = []
    for cover in tags.get("covr", []):
        mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        pictures.append(Art(bytes(cover), mime))
    return Tags(values, pictures)


# ---------------------------------------------------------------- writing


def write_tags(path: Path, tags: Tags, lyrics: str) -> None:
    if path.suffix.lower() == ".flac":
        _write_flac(path, tags, lyrics)
    else:
        _write_mp4(path, tags, lyrics)


def _write_flac(path: Path, tags: Tags, lyrics: str) -> None:
    flac = FLAC(path)
    flac.delete()
    flac.clear_pictures()
    for name, values in tags.values.items():
        if name in SKIPPED or name in LYRICS_KEYS or not values:
            continue
        flac[name.upper()] = values
    if lyrics:
        flac["LYRICS"] = lyrics
    for art in tags.pictures:
        picture = Picture()
        picture.data, picture.mime, picture.type = art.data, art.mime, art.kind
        flac.add_picture(picture)
    flac.save()


def _number(tags: Tags, number: str, total: str) -> tuple[int, int] | None:
    raw = tags.first(number)
    if not raw:
        return None
    n, _, t = raw.partition("/")
    try:
        return int(n), int(t or tags.first(total) or 0)
    except ValueError:
        return None


def _write_mp4(path: Path, tags: Tags, lyrics: str) -> None:
    mp4 = MP4(path)
    if mp4.tags is None:
        mp4.add_tags()
    mp4.tags.clear()
    for name, atom in MP4_TEXT.items():
        values = [v for v in tags.values.get(name, []) if v]
        if values:
            mp4.tags[atom] = values
    for number, total, atom in (
        ("tracknumber", "tracktotal", "trkn"),
        ("discnumber", "disctotal", "disk"),
    ):
        pair = _number(tags, number, total)
        if pair:
            mp4.tags[atom] = [pair]
    if tags.first("compilation") == "1":
        mp4.tags["cpil"] = True
    for name, values in tags.values.items():
        if name in HANDLED or name in SKIPPED or not values:
            continue
        label = MP4_FREEFORM.get(name, name.upper())
        mp4.tags[f"----:com.apple.iTunes:{label}"] = [MP4FreeForm(v.encode()) for v in values]
    if lyrics:
        mp4.tags["\xa9lyr"] = [lyrics]
    covers = []
    for art in tags.pictures:
        kind = MP4Cover.FORMAT_PNG if art.mime == "image/png" else MP4Cover.FORMAT_JPEG
        covers.append(MP4Cover(art.data, imageformat=kind))
    if covers:
        mp4.tags["covr"] = covers
    mp4.save()
