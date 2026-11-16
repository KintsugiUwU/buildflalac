import threading

from watchdog.events import (
    FileClosedEvent,
    FileClosedNoWriteEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileOpenedEvent,
)

from flalac.runner import Runner, _Changes


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


def test_the_loop_survives_a_failing_cleanup_and_pass(workspace, make_engine, monkeypatch):
    engine = make_engine(rescan_minutes=0)
    passes = []

    def broken_cleanup():
        raise OSError("target share is away")

    def broken_pass():
        passes.append(1)
        raise RuntimeError("unexpected")

    monkeypatch.setattr(engine, "remove_stale_temp_files", broken_cleanup)
    monkeypatch.setattr(engine, "run_pass", broken_pass)
    runner = Runner(engine)
    runner._thread.start()
    runner._thread.join(timeout=1)
    assert runner._thread.is_alive() and passes
    assert engine.status["phase"] == "paused"
    runner._stop.set()
    runner._wake.set()
    runner._thread.join(timeout=5)
