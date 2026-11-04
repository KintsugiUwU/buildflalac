from pathlib import Path

from flalac.lyrics import Answer, blocks, choose, clean_lrc, clean_plain, lookup, lrc_to_text
from flalac.media import Tags


def test_plain_timed_lines():
    assert lrc_to_text("[00:10.10] One\n[00:12.43] Two\n") == "One\nTwo"


def test_headers_bom_crlf_are_dropped():
    raw = "﻿[ar:Artist]\r\n[ti:Song]\r\n[offset:+100]\r\n[00:01.00]Hello\r\n"
    assert lrc_to_text(raw) == "Hello"


def test_repeated_chorus_is_expanded_in_time_order():
    raw = "[00:05.00]Verse\n[00:10.00][00:30.00]Chorus\n[00:20.00]Bridge\n"
    assert lrc_to_text(raw) == "Verse\nChorus\nBridge\nChorus"


def test_word_level_timing_and_three_digit_fractions():
    raw = "[00:01.500]<00:01.500>Hel<00:02.000>lo\n[00:03:25]Next\n"
    assert lrc_to_text(raw) == "Hello\nNext"


def test_only_empty_timed_lines_become_breaks():
    raw = "[00:01.00]A\n[00:02.00]\n[00:03.00]\n[00:04.00]B\n[00:30.00]C\n[00:31.00]\n"
    assert lrc_to_text(raw) == "A\n\nB\nC"  # a long pause alone does not add a break


def test_untimed_text_and_section_headers_pass_through():
    raw = "[Verse 1]\nLine one\n\n\n[Chorus]\nLine two\n"
    assert lrc_to_text(raw) == "[Verse 1]\nLine one\n\n[Chorus]\nLine two"


def test_unicode_survives():
    assert lrc_to_text("[00:01.00]Ça va – 天使\n") == "Ça va – 天使"


def test_clean_plain_drops_music_notes():
    assert clean_plain("a\n♪\nb\r\n\r\n\r\nc") == "a\n\nb\n\nc"


def test_clean_lrc_keeps_timestamps():
    assert clean_lrc("﻿[00:01.00]Hi  \r\n[00:02.00]There\r\n") == "[00:01.00]Hi\n[00:02.00]There"


def entry(
    plain: str = "",
    duration: float = 200,
    title: str = "SKINNY",
    artist: str = "Billie Eilish",
    synced: str = "",
    **extra,
) -> dict:
    return {
        "plainLyrics": plain,
        "syncedLyrics": synced,
        "duration": duration,
        "trackName": title,
        "artistName": artist,
        **extra,
    }


def test_lookup_prefers_most_verse_breaks_within_two_seconds():
    results = [
        entry("one block"),
        entry("a\n\nb\n\nc", 201.9, synced="[00:01.00]a"),
        entry("w\n\nx\n\ny\n\nz", 197.9),  # 2.1 s off: a different edit
        entry("x\n\ny", 200, title="SKINNY (Live)"),
        entry("z\n\nz\n\nz\n\nz", 200, artist="Someone Else"),
    ]
    answer = lookup(results, "SKINNY", "Billie Eilish", 200)
    assert (answer.plain, answer.synced) == ("a\n\nb\n\nc", "[00:01.00]a")


def test_lookup_instrumental_and_feat():
    instrumental = entry(instrumental=True)
    assert lookup([instrumental], "SKINNY", "Billie Eilish", 200).instrumental
    both = lookup(
        [instrumental, entry("la\n\nla", artist="Billie Eilish, Khalid")],
        "SKINNY",
        "Billie Eilish feat. Khalid",
        200,
    )
    assert (both.plain, both.instrumental) == ("la\n\nla", False)


def test_blocks():
    assert blocks("a\n\nb\n\nc") == 3 and blocks("") == 0


def tags(title: str = "Song", artist: str = "Artist", **values: str) -> Tags:
    return Tags({"title": [title], "artist": [artist], **{k: [v] for k, v in values.items()}})


def online(plain: str = "online a\n\nonline b", synced: str = "[00:01.00]online"):
    return lambda *_: Answer(plain, synced)


def test_plain_style_uses_lrclib_plain_as_is(tmp_path: Path):
    song = tmp_path / "01 Song.flac"
    (tmp_path / "01 Song.lrc").write_text("[00:01.00]a\n[00:02.00]\n[00:03.00]b\n")
    result = choose(song, tags(), 200, "lrclib", "plain", online(plain="one block"))
    assert (result.text, result.source, result.synced) == ("one block", "lrclib", False)


def test_plain_style_order(tmp_path: Path):
    song = tmp_path / "01 Song.flac"
    (tmp_path / "01 Song.lrc").write_text("[00:01.00]from lrc\n")
    assert choose(song, tags(), 200, "sidecar", "plain", online()).text == "from lrc"
    assert choose(song, tags(), 200, "lrclib", "plain", online(plain="")).source == "lrc"
    assert choose(song, tags(), 200, "off", "plain", online()).source == "none"
    (tmp_path / "01 Song.txt").write_text("[Verse]\nfrom txt\n")
    asked = []
    result = choose(song, tags(), 200, "lrclib", "plain", lambda *a: asked.append(a))
    assert (result.text, asked) == ("[Verse]\nfrom txt", [])  # no LRCLIB request needed


def test_synced_style_order(tmp_path: Path):
    song = tmp_path / "02 Song.flac"
    result = choose(song, tags(), 200, "lrclib", "synced", online())
    assert (result.text, result.source, result.synced) == (
        "[00:01.00]online",
        "lrclib-synced",
        True,
    )
    (tmp_path / "02 Song.lrc").write_text("[00:01.00]mine\n")
    assert choose(song, tags(), 200, "lrclib", "synced", online()).source == "lrc-synced"
    plain_only = choose(tmp_path / "03 X.flac", tags(), 200, "lrclib", "synced", online(synced=""))
    assert (plain_only.source, plain_only.synced) == ("lrclib", False)


def test_falls_back_to_tag_lyrics_and_instrumental(tmp_path: Path):
    result = choose(
        tmp_path / "x.flac", tags(lyrics="in the tag"), 200, "lrclib", "plain", lambda *_: Answer()
    )
    assert (result.text, result.source) == ("in the tag", "tag")
    result = choose(
        tmp_path / "y.flac", tags(), 200, "lrclib", "plain", lambda *_: Answer(instrumental=True)
    )
    assert result.source == "instrumental"


def test_retry_requested_when_lrclib_is_down(tmp_path: Path):
    song = tmp_path / "03 Song.flac"
    result = choose(song, tags(), 200, "lrclib", "plain", lambda *_: None)
    assert (result.source, result.retry) == ("none", True)
    (tmp_path / "03 Song.lrc").write_text("[00:01.00]local\n")
    result = choose(song, tags(), 200, "lrclib", "plain", lambda *_: None)
    assert (result.text, result.source, result.retry) == ("local", "lrc", True)


def test_main_artist():
    from flalac.lyrics import main_artist

    assert main_artist("Flume feat. Anthony for Cleopatra") == "Flume"
    assert main_artist("Pola & Bryson × Emily Makis") == "Pola"
    assert main_artist("Flume") == "Flume"
