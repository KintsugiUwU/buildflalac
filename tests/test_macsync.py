"""The Mac sync: library actions for the AppleScript and play counts with Jellyfin."""

from __future__ import annotations

import time
import unicodedata
from pathlib import Path

import pytest

from flalac.config import Settings
from flalac.db import Database, Track
from flalac.jellyfin import Item, JellyfinError
from flalac.macsync import MacSync, parse_request

ROOT = "/Volumes/Music/ALAC"


class FakeJellyfin:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.fail = False

    def play_counts(self) -> dict[str, Item]:
        return {rel: Item(f"id-{rel}", n) for rel, n in self.counts.items()}

    def set_play_count(self, item_id: str, plays: int) -> None:
        if self.fail:
            raise JellyfinError("down")
        self.counts[item_id.removeprefix("id-")] = plays


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "flalac.db")
    yield database
    database.close()


def mirror(db: Database, name: str, identity: str, updated: float = 1.0) -> None:
    db.save(
        Track(
            rel=f"A/{name}.flac",
            size=1,
            mtime=1.0,
            identity=identity,
            tag_hash="t",
            target_rel=f"A/{name}.m4a",
            output_key="k",
            lyrics_source="none",
            lyrics_hash=None,
            lyrics_locked=0,
            status="synced",
            error=None,
            updated=updated,
        )
    )


def request(*tracks: tuple[str, int, str]) -> str:
    lines = ["mac\tMacBook", f"root\t{ROOT}/"]
    lines += [f"track\t{pid}\t{plays}\t{path}" for pid, plays, path in tracks]
    return "\n".join(lines)


def run(db: Database, jellyfin: FakeJellyfin | None, text: str) -> list[str]:
    return MacSync(Settings(), db, jellyfin).sync(parse_request(text))


def test_first_sync_adds_every_mirrored_song(db):
    mirror(db, "One", "i1")
    mirror(db, "Two", "i2")
    assert run(db, None, request()) == [f"add\t{ROOT}/A/One.m4a", f"add\t{ROOT}/A/Two.m4a"]


def test_first_pairing_keeps_the_larger_count_then_plays_add_up(db):
    mirror(db, "One", "i1")
    jelly = FakeJellyfin({"A/One.flac": 7})
    actions = run(db, jelly, request(("P1", 3, f"{ROOT}/A/One.m4a")))
    assert actions == ["plays\tP1\t7"]
    assert jelly.counts["A/One.flac"] == 7
    jelly.counts["A/One.flac"] = 10  # 3 plays on Jellyfin
    actions = run(db, jelly, request(("P1", 9, f"{ROOT}/A/One.m4a")))  # 2 on this Mac
    assert actions[0] == "plays\tP1\t12"
    assert jelly.counts["A/One.flac"] == 12


def test_decreases_are_not_passed_on(db):
    mirror(db, "One", "i1")
    jelly = FakeJellyfin({"A/One.flac": 5})
    run(db, jelly, request(("P1", 5, f"{ROOT}/A/One.m4a")))
    actions = run(db, jelly, request(("P1", 0, f"{ROOT}/A/One.m4a")))  # count reset on the Mac
    assert actions == ["plays\tP1\t5"]
    assert jelly.counts["A/One.flac"] == 5


def test_renamed_song_is_followed_and_keeps_its_plays(db):
    mirror(db, "One", "i1")
    jelly = FakeJellyfin({"A/One.flac": 4})
    run(db, jelly, request(("P1", 4, f"{ROOT}/A/One.m4a")))
    db.rename("A/One.flac", "A/Uno.flac")
    track = db.get("A/Uno.flac")
    track.target_rel = "A/Uno.m4a"
    db.save(track)
    jelly.counts = {"A/Uno.flac": 4}
    actions = run(db, jelly, request(("P1", 4, "")))  # Music shows the old file as missing
    assert actions == [f"move\tP1\t{ROOT}/A/Uno.m4a", "refresh\tP1"]


def test_deleted_song_is_removed_and_other_songs_are_left_alone(db):
    mirror(db, "One", "i1")
    actions = run(
        db,
        None,
        request(
            ("P1", 0, f"{ROOT}/A/One.m4a"),
            ("P2", 0, f"{ROOT}/A/Gone.m4a"),
            ("P3", 9, "/Users/me/Music/Podcast.mp3"),
            ("P4", 0, ""),
        ),
    )
    assert actions == ["remove\tP2"]


def test_retagged_song_is_refreshed(db):
    mirror(db, "One", "i1", updated=1.0)
    run(db, None, request(("P1", 0, f"{ROOT}/A/One.m4a")))
    mirror(db, "One", "i1", updated=4_000_000_000.0)  # retagged after the last sync
    assert run(db, None, request(("P1", 0, f"{ROOT}/A/One.m4a"))) == ["refresh\tP1"]


def test_failed_jellyfin_update_is_retried(db):
    mirror(db, "One", "i1")
    jelly = FakeJellyfin({"A/One.flac": 1})
    jelly.fail = True
    actions = run(db, jelly, request(("P1", 6, f"{ROOT}/A/One.m4a")))
    assert any(a.startswith("info\t1 Jellyfin play counts could not be saved") for a in actions)
    jelly.fail = False
    run(db, jelly, request(("P1", 6, f"{ROOT}/A/One.m4a")))
    assert jelly.counts["A/One.flac"] == 6  # not 11: the 5 plays are not counted twice


def test_accented_paths_match_whatever_the_normalization(db):
    mirror(db, "Réel", "i1")
    nfd = unicodedata.normalize("NFD", f"{ROOT}/A/Réel.m4a")
    assert run(db, None, request(("P1", 0, nfd))) == []


def test_a_song_whose_last_retag_failed_stays_in_the_library(db):
    mirror(db, "One", "i1")
    mirror(db, "Two", "i2")
    text = request(("P1", 5, f"{ROOT}/A/One.m4a"), ("P2", 9, f"{ROOT}/A/Two.m4a"))
    assert run(db, None, text) == []
    track = db.get("A/Two.flac")
    track.status, track.error = "error", "RemoteDisconnected"  # the copy is still on disk
    db.save(track)
    assert not [action for action in run(db, None, text) if action.startswith("remove")]


def test_only_a_changed_copy_is_refreshed(db):
    mirror(db, "One", "i1")
    text = request(("P1", 0, f"{ROOT}/A/One.m4a"))
    run(db, None, text)
    track = db.get("A/One.flac")
    track.changed = 1.0  # checked again since (updated moves), but the file is as it was
    db.save(track)
    assert run(db, None, text) == []
    track.changed = 4_000_000_000.0
    db.save(track)
    assert run(db, None, text) == ["refresh\tP1"]


def test_renamed_song_is_followed_without_jellyfin(db):
    mirror(db, "One", "i1")
    run(db, None, request(("P1", 2, f"{ROOT}/A/One.m4a")))
    db.rename("A/One.flac", "A/Uno.flac")
    track = db.get("A/Uno.flac")
    track.target_rel = "A/Uno.m4a"
    db.save(track)
    actions = run(db, None, request(("P1", 2, "")))
    assert actions == [f"move\tP1\t{ROOT}/A/Uno.m4a", "refresh\tP1"]


def test_tracks_remembered_before_jellyfin_take_the_larger_count_when_first_paired(db):
    mirror(db, "One", "i1")
    run(db, None, request(("P1", 3, f"{ROOT}/A/One.m4a")))  # Jellyfin not set up yet
    jelly = FakeJellyfin({"A/One.flac": 5})  # the same plays, counted on both sides
    assert run(db, jelly, request(("P1", 3, f"{ROOT}/A/One.m4a"))) == ["plays\tP1\t5"]
    assert jelly.counts["A/One.flac"] == 5


def test_a_new_cover_re_adds_the_song_with_its_plays(db):
    mirror(db, "One", "i1")
    run(db, None, request(("P1", 4, f"{ROOT}/A/One.m4a")))
    track = db.get("A/One.flac")
    track.changed = track.art_changed = 4_000_000_000.0  # new cover after the last sync
    db.save(track)
    actions = run(db, None, request(("P1", 4, f"{ROOT}/A/One.m4a")))
    assert actions == [f"readd\tP1\t{ROOT}/A/One.m4a\t4"]
    assert "P1" not in db.mac_memory("MacBook")  # the new entry is paired next time


def test_a_re_added_song_carries_the_agreed_count_and_updates_jellyfin(db):
    mirror(db, "One", "i1")
    jelly = FakeJellyfin({"A/One.flac": 4})
    run(db, jelly, request(("P1", 4, f"{ROOT}/A/One.m4a")))
    track = db.get("A/One.flac")
    track.art_changed = time.time()  # new cover after the last sync
    db.save(track)
    jelly.counts["A/One.flac"] = 6  # two plays on Jellyfin, one on this Mac
    actions = run(db, jelly, request(("P1", 5, f"{ROOT}/A/One.m4a")))
    assert actions[0] == f"readd\tP1\t{ROOT}/A/One.m4a\t7"
    assert not [a for a in actions if a.startswith(("plays", "refresh", "move"))]
    assert jelly.counts["A/One.flac"] == 7
    # next sync: the new entry (P9) is paired with the larger count, nothing is doubled
    actions = run(db, jelly, request(("P9", 7, f"{ROOT}/A/One.m4a")))
    assert not [a for a in actions if not a.startswith("info")]
    assert jelly.counts["A/One.flac"] == 7


def test_a_renamed_song_with_a_new_cover_is_re_added_at_its_new_path(db):
    mirror(db, "One", "i1")
    run(db, None, request(("P1", 1, f"{ROOT}/A/One.m4a")))
    db.rename("A/One.flac", "A/Uno.flac")
    track = db.get("A/Uno.flac")
    track.target_rel = "A/Uno.m4a"
    track.art_changed = 4_000_000_000.0
    db.save(track)
    assert run(db, None, request(("P1", 1, ""))) == [f"readd\tP1\t{ROOT}/A/Uno.m4a\t1"]
