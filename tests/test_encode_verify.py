"""Verification uses the FLAC header checksum instead of decoding the source again."""

from __future__ import annotations

import dataclasses

import pytest
from conftest import default_tags, make_flac

from flalac import encode
from flalac.config import Settings
from flalac.media import facts, pcm_md5


def test_header_checksum_matches_decoded_audio(tmp_path):
    song = make_flac(tmp_path / "a.flac", tags=default_tags("A", 1))
    audio = facts(song)
    assert audio.stream_md5 and encode.expected_md5(song, audio) == pcm_md5(song, 16)


def test_source_is_not_decoded_again(tmp_path, monkeypatch):
    song = make_flac(tmp_path / "a.flac", tags=default_tags("A", 1))
    audio = facts(song)
    decoded = []
    real = encode.pcm_md5
    monkeypatch.setattr(
        encode, "pcm_md5", lambda path, bits: decoded.append(path) or real(path, bits)
    )
    encode.encode(song, tmp_path / "a.m4a", audio, Settings())
    assert decoded == [encode.temp_path(tmp_path / "a.m4a")]  # only the output is decoded


def test_a_wrong_checksum_is_caught(tmp_path):
    song = make_flac(tmp_path / "a.flac", tags=default_tags("A", 1))
    audio = dataclasses.replace(facts(song), stream_md5="0" * 32)
    with pytest.raises(encode.EncodeError, match="differs"):
        encode.encode(song, tmp_path / "a.m4a", audio, Settings())


def test_quick_header_read_matches_the_full_reader(tmp_path):
    from mutagen.flac import FLAC

    from flalac.media import _flac_streaminfo

    for rate, seconds in ((44100, 1.0), (48000, 2.5)):
        song = make_flac(
            tmp_path / f"{rate}.flac", tags=default_tags("A", 1), rate=rate, seconds=seconds
        )
        quick, info = _flac_streaminfo(song), FLAC(song).info
        assert (quick.sample_rate, quick.bits, quick.channels) == (
            info.sample_rate,
            info.bits_per_sample,
            info.channels,
        )
        assert abs(quick.seconds - info.length) < 1e-6
        assert quick.stream_md5 == f"{info.md5_signature:032x}"


def test_not_a_plain_flac_falls_back(tmp_path):
    from flalac.media import _flac_streaminfo

    odd = tmp_path / "odd.flac"
    odd.write_bytes(b"ID3" + bytes(60))
    assert _flac_streaminfo(odd) is None
