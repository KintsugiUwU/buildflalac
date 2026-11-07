# flalac.app for Macs

`build_mac_app.sh` builds `flalac.app` for Apple Silicon Macs. Python, flalac, its
dependencies and ffmpeg are all inside the app, so the Mac that runs it needs nothing
installed: no Homebrew, no Python, no ffmpeg.

## Build

On the build Mac only: Apple Silicon, [uv](https://docs.astral.sh/uv/) and the Xcode
Command Line Tools (`xcode-select --install`).

```sh
packaging/build_mac_app.sh
```

The app ends up in `packaging/dist/flalac.app`. The first build compiles ffmpeg (about two
minutes on an 8-core M-series Mac); later builds reuse it from `packaging/build/` and take
well under a minute. Both folders are ignored by git.

What the script does:

1. Downloads the ffmpeg source from ffmpeg.org, checks its SHA-256 and compiles it with
   Apple's tools only (`PATH=/usr/bin:/bin:/usr/sbin:/sbin`, nothing from Homebrew).
2. Runs PyInstaller (pinned in the script) with `uv run --with pyinstaller==…`, in its own
   environment `packaging/build/venv`: the locked runtime dependencies without the dev
   group, on a uv-managed CPython 3.12. PyInstaller is not a dependency of flalac;
   `pyproject.toml`, `uv.lock` and `.venv` are not touched.
3. Checks every executable and library in the app: arm64, linked only against macOS or the
   app itself, built for macOS 11 or older; then verifies the signature.
4. Runs the smoke test inside the app with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`.

## What is inside

| Part | Version | Licence |
| --- | --- | --- |
| flalac and its locked runtime dependencies | from `pyproject.toml` | GPL-3.0-or-later (flalac) |
| CPython, uv-managed (python-build-standalone) | 3.12 | PSF |
| ffmpeg | 9.0.2 | LGPL-2.1-or-later |

Size: about 44 MB (21 MB zipped), mostly ffmpeg (21 MB) and libpython (17 MB). It runs on
macOS 11 Big Sur or later (`LSMinimumSystemVersion`; every binary in the app is built for
11.0).

ffmpeg is built from the unmodified release tarball (URL and SHA-256 in the script; the
checksum is the same one Homebrew's formula pins). It contains FFmpeg's own code only: the
native ALAC, FLAC and AAC encoders and decoders, all native formats and filters, and no
external or GPL libraries, network access or capture devices. It links only libSystem, zlib
and CoreFoundation, CoreMedia and CoreVideo, all part of macOS. The licence texts, the source
URL and the configure flags are in `Contents/Resources/licenses/`.

A prebuilt ffmpeg was not used: the osxexperts.net arm64 build replaces its files in place
at each release, is offered "for educational purposes only" and carries many GPL libraries
flalac does not need; Homebrew's ffmpeg needs dozens of its dylibs relinked into the app and
is built for the build Mac's macOS version.

## How flalac finds ffmpeg

flalac runs `ffmpeg` by name. The app's entry point, `launcher.py`, puts the app's
`Contents/Frameworks/bin` first on PATH before it imports flalac, so the ffmpeg inside the
app is used even when another one is on the PATH.

The app starts `flalac.macapp:main` when `src/flalac/macapp.py` exists at build time (the
build output says which entry it used), and otherwise the self-test in `smoke_entry.py`.
`FLALAC_SMOKE_TEST=1` runs the self-test in any build: it imports every flalac module,
checks that the ffmpeg on PATH is the one in the app, and converts a generated one-second
FLAC to ALAC, checking that both decode to the same audio.

```sh
env -i PATH=/usr/bin:/bin FLALAC_SMOKE_TEST=1 packaging/dist/flalac.app/Contents/MacOS/flalac
```

## On another Mac

The app is signed ad hoc only, without an Apple developer account, so it is not notarized.
If it arrived by download, AirDrop or mail, macOS says it is damaged or refuses to open it.
Once it is where it belongs (on the music drive, next to the ALAC folder), run this in
Terminal and open it again:

```sh
xattr -cr /Volumes/<drive>/flalac.app
```

This also keeps macOS from running it from a hidden temporary copy (App Translocation),
which would hide which drive it is on. Copied from a local disk with Finder, the app needs
no such step. It also works from an exFAT drive.

## Updating

Change `FFMPEG_VERSION` and `FFMPEG_SHA256` in `build_mac_app.sh` (check the checksum
against ffmpeg.org's `.asc` signature or Homebrew's formula), or `PYINSTALLER_VERSION`, and
build again. A changed ffmpeg version or configuration is recompiled automatically.
