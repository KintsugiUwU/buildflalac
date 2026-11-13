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
    stages = [m["stage"] for m in out if m["type"] == "stage"]
    assert stages[0] == "checking" and stages[-1] == "done"
    assert stages.count("converting") <= 1  # announced once, when the first song starts
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


def test_quality_options_reach_the_settings(tmp_path):
    args = engine._parser().parse_args(
        [
            "sync",
            "--source",
            "s",
            "--target",
            str(tmp_path / "A"),
            "--max-bit-depth",
            "24",
            "--max-sample-rate",
            "0",
            "--jellyfin-music-path",
            "/music",
        ]
    )
    s = engine._settings(args)
    assert (s.max_bit_depth, s.max_sample_rate, s.jellyfin_music_path) == (24, 0, "/music")
    assert s.config == tmp_path / ".flalac"


def test_unexpected_failures_are_error_lines_not_tracebacks(tmp_path, capsys, monkeypatch):
    source = tmp_path / "FLAC"
    source.mkdir()

    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(engine, "run", broken)
    args = ["sync", "--source", str(source), "--target", str(tmp_path / "ALAC")]
    assert engine.main(args) == 1
    error = lines(capsys)[-1]
    assert error == {"type": "error", "message": "RuntimeError: database is locked"}


def test_confirm_deletes_takes_the_count_shown(tmp_path):
    parse = engine._parser().parse_args
    base = ["sync", "--source", "s", "--target", "t"]
    assert parse(base).confirm_deletes is None
    assert parse([*base, "--confirm-deletes"]).confirm_deletes == -1
    assert parse([*base, "--confirm-deletes", "12"]).confirm_deletes == 12
