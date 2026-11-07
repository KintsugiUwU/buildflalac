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
