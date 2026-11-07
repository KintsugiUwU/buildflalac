"""The engine contract the Mac app relies on: one JSON object per line on stdout."""

from __future__ import annotations

import json
import os

from conftest import default_tags, make_flac

from flalac import __version__, engine


def lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_version(capsys):
    assert engine.main(["version"]) == 0
    assert lines(capsys) == [{"type": "version", "version": __version__}]


def test_sync_without_library(tmp_path, capsys):
    source, target = tmp_path / "FLAC", tmp_path / "SSD" / "ALAC"
    song = make_flac(source / "A" / "01 One.flac", tags=default_tags("One", 1))
    os.utime(song, (1_000_000_000, 1_000_000_000))  # written long ago: past the settle time
    args = ["sync", "--source", str(source), "--target", str(target), "--lyrics", "off"]
    assert engine.main(args) == 0
    out = lines(capsys)
    assert [m["stage"] for m in out if m["type"] == "stage"] == ["checking", "converting", "done"]
    summary = out[-1]
    assert summary["type"] == "summary"
    assert (summary["converted"], summary["errors"], summary["library"]) == (1, 0, None)
    assert (target / "A" / "01 One.m4a").is_file()
    assert (tmp_path / "SSD" / ".flalac" / "flalac.db").is_file()


def test_unreachable_source_is_an_error_line(tmp_path, capsys):
    args = ["sync", "--source", str(tmp_path / "nope"), "--target", str(tmp_path / "ALAC")]
    assert engine.main(args) == 1
    error = lines(capsys)[-1]
    assert error["type"] == "error" and "Connect the share" in error["message"]


def test_jellyfin_test_needs_a_key(capsys, monkeypatch):
    monkeypatch.delenv(engine.KEY_ENV, raising=False)
    args = ["test-jellyfin", "--jellyfin-url", "http://x", "--jellyfin-user", "u"]
    assert engine.main(args) == 1
    assert lines(capsys)[-1]["type"] == "error"
