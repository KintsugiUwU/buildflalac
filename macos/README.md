# Flalac for Mac

A small native front end for flalac: settings, a Sync button, progress and the result. The
work is done by `flalac-engine`, a command-line program bundled in the app. SwiftUI and
AppKit, Apple Silicon, macOS 11 or later, built with the Command Line Tools only (no Xcode
project).

## Build

```sh
macos/build.sh                              # macos/build/Flalac.app, engine from $FLALAC_ENGINE
ENGINE_DIR=path/to/flalac-engine macos/build.sh   # with the engine folder inside the app
```

`build.sh` compiles `Sources/*.swift` with `swiftc` (Swift 6 language mode,
`arm64-apple-macos11.0`), writes `Info.plist` (version from `../pyproject.toml`), copies
`../packaging/flalac.icns`, copies `ENGINE_DIR` to `Contents/Resources/engine` (it must hold
an executable `flalac-engine`) and signs ad hoc. Swift concurrency is part of macOS from 12
on; for macOS 11 the build puts Apple's back-deployed `libswift_Concurrency.dylib` in
`Contents/Frameworks` (macOS 12 and later use their own).

Run against the stand-in engine while developing:

```sh
open -n macos/build/Flalac.app --env FLALAC_ENGINE="$PWD/macos/dev/fake-engine"
```

## Engine contract

The app runs `<app>/Contents/Resources/engine/flalac-engine`, or `$FLALAC_ENGINE` when set.
The Jellyfin API key is never an argument: it is passed in `FLALAC_JELLYFIN_KEY`. The app
also sets `PYTHONUNBUFFERED=1` and `PYTHONIOENCODING=utf-8`.

```text
flalac-engine sync --source <FLAC dir> --target <ALAC dir> [--state <dir>]
    --library itunes|music|none
    [--jellyfin-url <url> --jellyfin-user <user> [--jellyfin-music-path <path>]]
    --lyrics lrclib --lyrics-style plain|synced | --lyrics off
    --max-bit-depth 16|24|0 --max-sample-rate 44100|48000|0
    [--confirm-deletes]
flalac-engine test-jellyfin --jellyfin-url <url> --jellyfin-user <user> [--jellyfin-music-path <path>]
flalac-engine version
```

- Jellyfin arguments are passed only when address, user and a saved key are all set;
  `--jellyfin-music-path` only with them, and only when not empty.
- `--state` is passed only when set with
  `defaults write com.davidepetris.flalac stateFolder <dir>`; otherwise the engine's default
  (`.flalac` next to the ALAC folder) applies. The app edits `no-lyrics.txt` in that folder
  (one path per line, relative to the FLAC folder; `#` lines are comments and are kept).

stdout is one JSON object per line: `stage` (checking, converting, library, done),
`progress` (`done`/`total`/`current` while converting, `message` in the library stage),
`held-deletes` (`count`), `summary`, `jellyfin`, `version`, `error` (then exit code 1).
Lines that are not JSON objects, and all of stderr, go to the Log. Unknown message types are
ignored. Missing summary fields count as 0.

- After `held-deletes` and exit 0, the app asks whether to remove the songs; if the user
  agrees it runs `sync` again with `--confirm-deletes` and shows both runs as one summary.
- Cancel sends SIGTERM and, if the engine is still running 10 seconds later, SIGKILL. The
  engine should stop its workers (ffmpeg) and exit on SIGTERM.
- Exit code 0 without a summary, a non-zero exit without an `error` message, or a signal are
  shown as failures with the exit code or signal.

## Layout

| Path | What |
| --- | --- |
| `Sources/App.swift` | entry point, app delegate, windows, menu bar |
| `Sources/MainView.swift`, `SummaryView.swift`, `LogView.swift` | main window |
| `Sources/SettingsView.swift`, `AppSettings.swift`, `NoLyrics.swift` | Settings (UserDefaults, no-lyrics.txt) |
| `Sources/Keychain.swift` | API key: generic password, service `flalac-jellyfin`, account = user |
| `Sources/Engine.swift`, `EngineProtocol.swift` | starting the engine, reading its output, the messages |
| `Sources/SyncController.swift` | a sync from start to summary; the last result is kept in UserDefaults |
| `Sources/Notifier.swift` | a notification when a sync ends while the app is in the background |
| `dev/fake-engine` | a stand-in engine with made-up songs (`FLALAC_FAKE_SCENARIO`: normal, held-deletes, error, crash) |
| `dev/DevControl.swift`, `dev/ctl.sh` | `DEV=1 ./build.sh` only: drive the app and capture its windows from a script |
| `screenshots/` | the main window and Settings, light and dark |

Settings other than the key are in UserDefaults (`com.davidepetris.flalac`); the key is only
in the login Keychain. A development build (`DEV=1`) uses the bundle id
`com.davidepetris.flalac.dev` and so keeps its own settings.

## Notes

- Ad-hoc signed: after each rebuild macOS asks once to let Flalac read its Keychain item
  ("Always Allow"), and may ask again for access to network and removable volumes and to
  control iTunes or Music (the engine's AppleScript runs on the app's behalf).
- Built for macOS 11; so far run only on a much newer macOS.
