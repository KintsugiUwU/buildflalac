"""End-to-end behaviour on real files: encode, retag, move, delete, guards, lyrics."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from conftest import FakeLrclib, default_tags, make_flac, tiny_png
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from flalac.media import pcm_md5

ALBUM = "Pola & Bryson/Test Album"


def song(source: Path, name: str = "01 First", track: int = 1, **kwargs) -> Path:
    return make_flac(source / ALBUM / f"{name}.flac", tags=default_tags(name[3:], track), **kwargs)


def events(engine, kind: str) -> list[str]:
    return [row["rel"] for row in engine.db.events(1000) if row["kind"] == kind]


def test_first_pass_mirrors_bit_identical_with_tags_cover_and_lyrics(workspace, make_engine):
    source, target, _ = workspace
    flac = song(source)
    flac.with_suffix(".lrc").write_text("[00:00.50]Hello there\n[00:01.00]General\n")
    engine = make_engine()
    engine.run_pass()

    out = target / ALBUM / "01 First.m4a"
    mp4 = MP4(out)
    assert mp4.info.codec == "alac"
    assert pcm_md5(flac, 16) == pcm_md5(out, 16)
    assert mp4["\xa9nam"] == ["First"]
    assert mp4["\xa9ART"] == ["Pola & Bryson × Emily Makis"]
    assert mp4["aART"] == ["Pola & Bryson"]
    assert mp4["trkn"] == [(1, 10)] and mp4["disk"] == [(1, 1)]
    assert mp4["\xa9day"] == ["2024-05-17"]
    artists = [bytes(v).decode() for v in mp4["----:com.apple.iTunes:ARTISTS"]]
    assert artists == ["Pola & Bryson", "Emily Makis"]
    assert bytes(mp4["----:com.apple.iTunes:MusicBrainz Track Id"][0]).decode().endswith("01")
    assert not any("ACOUSTID" in key.upper() for key in mp4)
    assert bytes(mp4["covr"][0]) == tiny_png()
    assert mp4["\xa9lyr"] == ["Hello there\nGeneral"]
    assert out.with_suffix(".txt").read_text() == "Hello there\nGeneral\n"
    assert engine.db.get(f"{ALBUM}/01 First.flac").status == "synced"


def test_second_pass_changes_nothing(workspace, make_engine):
    song(workspace[0])
    engine = make_engine()
    engine.run_pass()
    assert engine.run_pass().empty


def test_tag_edit_retags_without_reencoding(workspace, make_engine):
    source, target, _ = workspace
    flac = song(source)
    engine = make_engine()
    engine.run_pass()
    out = target / ALBUM / "01 First.m4a"
    audio_before = pcm_md5(out, 16)
    tags = FLAC(flac)
    tags["TITLE"] = "First (Remastered)"
    tags.save()
    plan = engine.run_pass()
    assert len(plan.retag) == 1 and not plan.encode
    assert MP4(out)["\xa9nam"] == ["First (Remastered)"]
    assert pcm_md5(out, 16) == audio_before
    assert events(engine, "encoded") == [f"{ALBUM}/01 First.flac"]


def test_rename_moves_target_and_txt(workspace, make_engine):
    source, target, _ = workspace
    flac = song(source)
    flac.with_suffix(".lrc").write_text("[00:00.50]Words\n")
    engine = make_engine()
    engine.run_pass()
    new_dir = source / "Pola & Bryson" / "Renamed Album"
    new_dir.mkdir()
    os.rename(flac, new_dir / "01 First.flac")
    os.rename(flac.with_suffix(".lrc"), new_dir / "01 First.lrc")
    plan = engine.run_pass()
    assert len(plan.moves) == 1 and not plan.encode and not plan.deletes
    moved = target / "Pola & Bryson" / "Renamed Album" / "01 First.m4a"
    assert moved.is_file() and moved.with_suffix(".txt").read_text() == "Words\n"
    assert not (target / ALBUM).exists()  # emptied folder pruned


def test_delete_removes_target_and_empty_folders(workspace, make_engine):
    source, target, _ = workspace
    flacs = [song(source, f"0{i} Song", i) for i in range(1, 4)]
    engine = make_engine(delete_guard_percent=50)
    engine.run_pass()
    flacs[0].unlink()
    plan = engine.run_pass()
    assert plan.deletes == [f"{ALBUM}/01 Song.flac"]
    assert not (target / ALBUM / "01 Song.m4a").exists()
    assert (target / ALBUM / "02 Song.m4a").exists()


def test_mass_delete_is_held_until_confirmed(workspace, make_engine):
    source, target, _ = workspace
    flacs = [song(source, f"0{i} Song", i) for i in range(1, 6)]
    engine = make_engine()
    engine.run_pass()
    for flac in flacs[:4]:
        flac.unlink()
    plan = engine.run_pass()
    assert plan.held_deletes and not plan.deletes
    assert len(list((target / ALBUM).glob("*.m4a"))) == 5
    engine.confirm_deletes()
    plan = engine.run_pass()
    assert len(plan.deletes) == 4
    assert len(list((target / ALBUM).glob("*.m4a"))) == 1


def test_missing_source_pauses_and_deletes_nothing(workspace, make_engine):
    source, target, _ = workspace
    song(source)
    engine = make_engine()
    engine.run_pass()
    for path in sorted(source.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    assert engine.run_pass() is None
    assert engine.status["phase"] == "paused"
    assert (target / ALBUM / "01 First.m4a").exists()


def test_files_still_being_written_wait(workspace, make_engine):
    song(workspace[0])
    engine = make_engine(settle_seconds=3600)
    plan = engine.run_pass()
    assert plan.unsettled == 1 and plan.empty


def test_edited_txt_is_embedded_and_never_overwritten(workspace, make_engine):
    source, target, _ = workspace
    flac = song(source)
    flac.with_suffix(".lrc").write_text("[00:00.50]Original\n")
    engine = make_engine()
    engine.run_pass()
    txt = target / ALBUM / "01 First.txt"
    txt.write_text("[Verse]\nMy own lyrics\n")
    engine.run_pass()
    out = target / ALBUM / "01 First.m4a"
    assert MP4(out)["\xa9lyr"] == ["[Verse]\nMy own lyrics"]
    tags = FLAC(flac)
    tags["TITLE"] = "Retitled"
    tags.save()
    flac.with_suffix(".lrc").write_text("[00:00.50]Changed upstream\n")
    engine.run_pass()
    assert MP4(out)["\xa9lyr"] == ["[Verse]\nMy own lyrics"]
    assert txt.read_text() == "[Verse]\nMy own lyrics\n"
    assert engine.db.get(f"{ALBUM}/01 First.flac").lyrics_locked == 1


def test_lrclib_plain_is_used_and_cached(workspace, make_engine):
    source, target, _ = workspace
    song(source, seconds=3.0)
    client = FakeLrclib(
        {
            ("First", "Pola & Bryson × Emily Makis"): [
                {
                    "trackName": "First",
                    "artistName": "Pola & Bryson, Emily Makis",
                    "duration": 3,
                    "plainLyrics": "Verse one\n\nVerse two",
                }
            ]
        }
    )
    engine = make_engine(client)
    engine.run_pass()
    assert MP4(target / ALBUM / "01 First.m4a")["\xa9lyr"] == ["Verse one\n\nVerse two"]
    engine.db._conn.execute("UPDATE tracks SET status='error'")
    engine.run_pass()  # re-encode, lyrics come from the cache
    assert len(client.calls) == 1


def test_hi_res_is_reduced_for_ipods(workspace, make_engine):
    source, target, _ = workspace
    song(source, rate=96000, bits=24)
    engine = make_engine()
    engine.run_pass()
    info = MP4(target / ALBUM / "01 First.m4a").info
    assert (info.sample_rate, info.bits_per_sample) == (44100, 16)


def test_hi_res_kept_when_limits_are_off(workspace, make_engine):
    source, target, _ = workspace
    flac = song(source, rate=96000, bits=24)
    engine = make_engine(max_bit_depth=0, max_sample_rate=0)
    engine.run_pass()
    out = target / ALBUM / "01 First.m4a"
    assert (MP4(out).info.sample_rate, MP4(out).info.bits_per_sample) == (96000, 24)
    assert pcm_md5(flac, 24) == pcm_md5(out, 24)


def test_foreign_target_files_are_never_overwritten(workspace, make_engine):
    source, target, _ = workspace
    song(source)
    foreign = target / ALBUM / "01 First.m4a"
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b"not ours")
    engine = make_engine()
    engine.run_pass()
    assert foreign.read_bytes() == b"not ours"
    assert "already exists" in (engine.db.events(10)[0]["detail"] or "")


def test_alac_source_to_flac_target(workspace, make_engine):
    source, target, _ = workspace
    flac = make_flac(source / "tmp" / "x.flac", tags=default_tags("Back"))
    alac = source / ALBUM / "01 Back.m4a"
    alac.parent.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(flac),
            "-map",
            "0:a",
            "-c:a",
            "alac",
            str(alac),
        ],
        check=True,
    )
    flac.unlink()
    (source / "tmp").rmdir()
    MP4(alac).save()
    engine = make_engine(target_format="flac")
    engine.run_pass()
    out = target / ALBUM / "01 Back.flac"
    assert pcm_md5(alac, 16) == pcm_md5(out, 16)


def test_aac_target_is_lossy_but_valid(workspace, make_engine):
    source, target, _ = workspace
    song(source)
    engine = make_engine(target_format="aac")
    engine.run_pass()
    assert MP4(target / ALBUM / "01 First.m4a").info.codec.startswith("mp4a")


def test_dry_run_writes_nothing(workspace, make_engine):
    source, target, _ = workspace
    song(source)
    engine = make_engine(dry_run=True)
    engine.run_pass()
    assert not any(target.iterdir())
    assert events(engine, "would-encode") == [f"{ALBUM}/01 First.flac"]


def test_non_lossless_m4a_is_skipped_once(workspace, make_engine):
    source, target, _ = workspace
    aac = source / ALBUM / "lossy.m4a"
    aac.parent.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=duration=1",
            "-c:a",
            "aac",
            str(aac),
        ],
        check=True,
    )
    engine = make_engine()
    engine.run_pass()
    engine.run_pass()
    assert events(engine, "skipped") == [f"{ALBUM}/lossy.m4a"]
    assert not any(target.rglob("*.m4a"))


def test_changing_output_settings_reencodes(workspace, make_engine):
    source, target, _ = workspace
    song(source)
    make_engine().run_pass()
    engine = make_engine(target_format="flac")
    time.sleep(0.01)
    plan = engine.run_pass()
    assert len(plan.encode) == 1
    assert (target / ALBUM / "01 First.flac").exists()
    assert not (target / ALBUM / "01 First.m4a").exists()


def test_no_temp_files_are_left_behind(workspace, make_engine):
    source, target, _ = workspace
    song(source)
    stale = target / ALBUM / ".02 Old.flalac-tmp.m4a"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"half written")
    keep = target / ALBUM / ".hidden-but-not-ours"
    keep.write_bytes(b"x")
    engine = make_engine()
    assert engine.remove_stale_temp_files() == 1
    engine.run_pass()
    assert keep.exists() and not stale.exists()
    assert not list(target.rglob("*flalac-tmp*"))


def test_lrclib_down_is_not_cached_and_is_retried_later(workspace, make_engine):
    source, target, _ = workspace
    first = song(source, "01 First", 1, seconds=3.0)
    first.with_suffix(".lrc").write_text("[00:00.50]local words\n")
    song(source, "02 Second", 2, seconds=3.0)
    client = FakeLrclib(
        {
            ("First", "Pola & Bryson × Emily Makis"): [
                {
                    "trackName": "First",
                    "artistName": "Pola & Bryson",
                    "duration": 3,
                    "plainLyrics": "Verse one\n\nVerse two",
                }
            ]
        }
    )
    client.down = True
    engine = make_engine(client)
    engine.run_pass()
    track = engine.db.get(f"{ALBUM}/01 First.flac")
    assert (track.lyrics_source, track.lyrics_retry) == ("lrc", 1)
    assert len(client.calls) == 1  # LRCLIB is paused after the first failure
    assert engine.db.cached_lyrics("pola bryson emily makis|first|3") is None
    assert engine.run_pass().empty  # not retried before an hour has passed

    client.down = False
    engine.clock = lambda: time.time() + 4000
    engine._lrclib_paused_until = 0
    plan = engine.run_pass()
    assert len(plan.retag) == 2 and not plan.encode  # lyrics refresh only, no re-encode
    track = engine.db.get(f"{ALBUM}/01 First.flac")
    assert (track.lyrics_source, track.lyrics_retry) == ("lrclib", 0)
    assert MP4(target / ALBUM / "01 First.m4a")["\xa9lyr"] == ["Verse one\n\nVerse two"]


def test_instrumental_songs_are_labelled(workspace, make_engine):
    source, target, _ = workspace
    song(source, seconds=3.0)
    client = FakeLrclib(
        {
            ("First", "Pola & Bryson × Emily Makis"): [
                {
                    "trackName": "First",
                    "artistName": "Pola & Bryson",
                    "duration": 3,
                    "instrumental": True,
                    "plainLyrics": None,
                }
            ]
        }
    )
    engine = make_engine(client)
    engine.run_pass()
    assert engine.db.get(f"{ALBUM}/01 First.flac").lyrics_source == "instrumental"
    assert not (target / ALBUM / "01 First.txt").exists()


def test_synced_style_and_switching_back_to_plain(workspace, make_engine):
    source, target, _ = workspace
    flac = song(source)
    flac.with_suffix(".lrc").write_text("[00:00.50]Hello there\n[00:01.00]General\n")
    engine = make_engine(lyrics_style="synced")
    engine.run_pass()
    out = target / ALBUM / "01 First.m4a"
    assert MP4(out)["\xa9lyr"] == ["[00:00.50]Hello there\n[00:01.00]General"]
    assert out.with_suffix(".lrc").exists() and not out.with_suffix(".txt").exists()
    assert engine.db.get(f"{ALBUM}/01 First.flac").lyrics_source == "lrc-synced"

    engine.set_lyrics_style("plain")
    plan = engine.run_pass()
    assert len(plan.retag) == 1 and not plan.encode  # lyrics refresh only
    assert MP4(out)["\xa9lyr"] == ["Hello there\nGeneral"]
    assert out.with_suffix(".txt").exists() and not out.with_suffix(".lrc").exists()
    assert engine.run_pass().empty


def test_lrclib_is_asked_again_with_the_main_artist(workspace, make_engine):
    source, target, _ = workspace
    make_flac(
        source / "Flume/Sleepless/01 Sleepless.flac",
        seconds=3.0,
        tags={"TITLE": "Sleepless", "ARTIST": "Flume feat. Anthony for Cleopatra"},
    )
    client = FakeLrclib(
        {
            ("Sleepless", "Flume"): [
                {
                    "trackName": "Sleepless",
                    "artistName": "Flume feat. Jezzabell Doran",
                    "duration": 3,
                    "plainLyrics": "Sleepless words",
                },
                {
                    "trackName": "Sleepless",
                    "artistName": "Flume",
                    "duration": 9,
                    "plainLyrics": "a different edit",
                },
            ]
        }
    )
    engine = make_engine(client)
    engine.run_pass()
    assert client.calls == [
        ("Sleepless", "Flume feat. Anthony for Cleopatra"),
        ("Sleepless", "Flume"),
    ]
    out = target / "Flume/Sleepless/01 Sleepless.m4a"
    assert MP4(out)["\xa9lyr"] == ["Sleepless words"]


def test_48k_sources_follow_the_limit(workspace, make_engine):
    source, target, _ = workspace
    song(source, rate=48000, bits=16)
    make_engine().run_pass()
    assert MP4(target / ALBUM / "01 First.m4a").info.sample_rate == 44100
    song(source, "02 Second", 2, rate=48000, bits=16)
    make_engine(max_sample_rate=48000).run_pass()
    assert MP4(target / ALBUM / "02 Second.m4a").info.sample_rate == 48000
