import threading

from watchdog.events import (
    FileClosedEvent,
    FileClosedNoWriteEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileOpenedEvent,
)

from flalac.runner import _Changes


def woken(event) -> bool:
    wake = threading.Event()
    _Changes(wake).on_any_event(event)
    return wake.is_set()


def test_reading_files_does_not_wake_the_runner():
    assert not woken(FileOpenedEvent("/source/a/01 Song.flac"))
    assert not woken(FileClosedNoWriteEvent("/source/a/01 Song.flac"))


def test_real_changes_wake_the_runner():
    assert woken(FileCreatedEvent("/source/a/01 Song.flac"))
    assert woken(FileModifiedEvent("/source/a/01 Song.flac"))
    assert woken(FileClosedEvent("/source/a/01 Song.flac"))
    assert woken(FileMovedEvent("/source/a/.tmp123", "/source/a/01 Song.flac"))


def test_hidden_temp_files_are_ignored():
    assert not woken(FileCreatedEvent("/source/a/.01 Song.flac.part"))
