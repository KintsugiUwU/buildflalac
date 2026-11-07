"""The Mac app's drive layout and settings (no dialogs are shown)."""

from __future__ import annotations

import json

from flalac import macapp


def test_drive_is_the_folder_holding_the_app(tmp_path, monkeypatch):
    exe = tmp_path / "MusicSSD" / "flalac.app" / "Contents" / "MacOS" / "flalac"
    exe.parent.mkdir(parents=True)
    exe.touch()
    monkeypatch.delenv("FLALAC_DRIVE", raising=False)
    monkeypatch.setattr(macapp.sys, "executable", str(exe))
    assert macapp.drive_root() == tmp_path / "MusicSSD"


def test_settings_live_on_the_drive(tmp_path):
    drive = tmp_path / "MusicSSD"
    (drive / ".flalac").mkdir(parents=True)
    source = tmp_path / "FLAC"
    source.mkdir()
    (drive / ".flalac" / "settings.json").write_text(json.dumps({"source": str(source)}))
    s = macapp.load_settings(drive)
    assert (s.source, s.target, s.config) == (source, drive / "ALAC", drive / ".flalac")
    assert (s.lyrics_files, s.max_bit_depth, s.max_sample_rate) == (False, 16, 44100)
