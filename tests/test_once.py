"""One pass and exit, with the state folder next to the copy."""

from __future__ import annotations

import dataclasses

import pytest
from conftest import default_tags, make_flac

from flalac.config import Settings
from flalac.once import OnceError, run


def settings(tmp_path, **changes) -> Settings:
    base = Settings(
        source=tmp_path / "flac",
        target=tmp_path / "ssd" / "ALAC",
        config=tmp_path / "ssd" / ".flalac",
        settle_seconds=0,
        lyrics="off",
        lyrics_files=False,
    )
    return dataclasses.replace(base, **changes)


def test_one_pass_then_nothing_to_do(tmp_path):
    s = settings(tmp_path)
    make_flac(s.source / "A" / "01 One.flac", tags=default_tags("One", 1))
    make_flac(s.source / "A" / "02 Two.flac", tags=default_tags("Two", 2))
    first = run(s)
    assert (first.encoded, first.errors) == (2, 0)
    assert (s.target / "A" / "01 One.m4a").is_file()
    assert (s.config / "flalac.db").is_file()
    again = run(s)
    assert (again.encoded, again.retagged, again.deleted) == (0, 0, 0)


def test_large_removal_waits_for_confirmation(tmp_path):
    s = settings(tmp_path)
    for n in range(1, 6):
        make_flac(s.source / "A" / f"0{n} S.flac", tags=default_tags(f"S{n}", n))
    run(s)
    for n in range(1, 5):
        (s.source / "A" / f"0{n} S.flac").unlink()
    held = run(s, confirm_deletes=lambda count: False)
    assert (held.held_deletes, held.deleted) == (4, 0)
    assert len(list((s.target / "A").glob("*.m4a"))) == 5
    done = run(s, confirm_deletes=lambda count: True)
    assert done.deleted == 4
    assert len(list((s.target / "A").glob("*.m4a"))) == 1


def test_unreachable_source_is_explained(tmp_path):
    with pytest.raises(OnceError, match="Connect the share"):
        run(settings(tmp_path))


def test_unreachable_target_is_explained(tmp_path):
    s = settings(tmp_path)
    s.source.mkdir(parents=True)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    s = dataclasses.replace(s, target=blocker / "ALAC")
    with pytest.raises(OnceError, match="Connect the drive"):
        run(s)
