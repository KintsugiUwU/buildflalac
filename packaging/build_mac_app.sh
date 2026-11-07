#!/bin/bash
# =====================================
# flalac Mac app build script
# =====================================
# Builds packaging/dist/flalac.app for Apple Silicon with Python, flalac and ffmpeg inside,
# so the Mac that runs it needs nothing installed (no Homebrew, no Python, no ffmpeg).
#
# Needs on the build Mac: uv, and the Xcode Command Line Tools (xcode-select --install)
# to compile ffmpeg from the official source. The version is read from pyproject.toml.
# =====================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$PWD
PKG=$ROOT/packaging
BUILD=$PKG/build
DIST=$PKG/dist
APP=$DIST/flalac.app

MIN_MACOS=11.0                 # the first macOS for Apple Silicon
PYINSTALLER_VERSION=6.22.3
FFMPEG_VERSION=9.0.2
FFMPEG_URL=https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
# FFmpeg's own code only (LGPL-2.1-or-later): every native codec, format and filter, no
# external or GPL libraries, no network, no capture devices. --disable-autodetect keeps
# configure from picking up whatever the build Mac happens to have. The result links only
# parts of macOS: libSystem, zlib, and CoreFoundation/CoreMedia/CoreVideo (always used by
# libavutil on macOS).
FFMPEG_CONFIGURE=(
    --cc=clang
    "--extra-cflags=-mmacosx-version-min=$MIN_MACOS"
    "--extra-ldflags=-mmacosx-version-min=$MIN_MACOS"
    --disable-autodetect
    --enable-zlib
    --disable-network
    --disable-avdevice
    --disable-ffplay
    --disable-ffprobe
    --disable-doc
    --disable-debug
)
FFMPEG_DIR=$BUILD/ffmpeg-$FFMPEG_VERSION
# Apple's tools only, so nothing from Homebrew or /usr/local gets into the build.
CLEAN_ENV=(env -i "HOME=$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin LANG=C)

APP_VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml | head -n 1)
echo "Building flalac.app $APP_VERSION (arm64, macOS $MIN_MACOS or later)"

if [ "$(uname -m)" != arm64 ]; then
    echo "Run this in a native arm64 shell on an Apple Silicon Mac (not under Rosetta)." >&2
    exit 1
fi
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/" >&2; exit 1; }
xcode-select -p >/dev/null 2>&1 || { echo "Run: xcode-select --install" >&2; exit 1; }

# -------------------------------------
# 1. ffmpeg from the official source (kept between builds while nothing here changes)
# -------------------------------------
STAMP="$FFMPEG_SHA256 ${FFMPEG_CONFIGURE[*]}"
if [ -x "$FFMPEG_DIR/bin/ffmpeg" ] && [ "$(cat "$FFMPEG_DIR/.stamp" 2>/dev/null)" = "$STAMP" ]; then
    echo "Using ffmpeg $FFMPEG_VERSION built earlier in $FFMPEG_DIR"
else
    echo "Building ffmpeg $FFMPEG_VERSION..."
    TARBALL=$BUILD/downloads/ffmpeg-$FFMPEG_VERSION.tar.xz
    SRC=$BUILD/ffmpeg-src
    mkdir -p "$BUILD/downloads"
    if [ ! -f "$TARBALL" ]; then
        echo "Downloading $FFMPEG_URL"
        curl -fsSL --proto '=https' -o "$TARBALL.part" "$FFMPEG_URL"
        mv "$TARBALL.part" "$TARBALL"
    fi
    if ! echo "$FFMPEG_SHA256  $TARBALL" | shasum -a 256 -c - >/dev/null; then
        echo "Checksum mismatch for $TARBALL; deleted it, run again to download it anew." >&2
        rm -f "$TARBALL"
        exit 1
    fi
    rm -rf "$SRC" "$FFMPEG_DIR"
    mkdir -p "$SRC"
    tar -xJf "$TARBALL" -C "$SRC" --strip-components 1
    echo "Compiling (a few minutes; output in $BUILD/ffmpeg-build.log)..."
    # Chained with && because set -e does not apply inside a subshell followed by ||.
    (
        cd "$SRC" \
            && "${CLEAN_ENV[@]}" MACOSX_DEPLOYMENT_TARGET=$MIN_MACOS \
                ./configure --prefix="$FFMPEG_DIR" "${FFMPEG_CONFIGURE[@]}" \
            && "${CLEAN_ENV[@]}" MACOSX_DEPLOYMENT_TARGET=$MIN_MACOS make -j"$(sysctl -n hw.ncpu)" \
            && "${CLEAN_ENV[@]}" make install
    ) >"$BUILD/ffmpeg-build.log" 2>&1 || {
        tail -n 30 "$BUILD/ffmpeg-build.log"
        echo "Building ffmpeg failed; the full output is in $BUILD/ffmpeg-build.log" >&2
        exit 1
    }
    mkdir -p "$FFMPEG_DIR/licenses"
    cp "$SRC/LICENSE.md" "$SRC/COPYING.LGPLv2.1" "$FFMPEG_DIR/licenses/"
    cat >"$FFMPEG_DIR/licenses/SOURCE.txt" <<EOF
FFmpeg $FFMPEG_VERSION, LGPL-2.1-or-later, built unmodified from the release tarball
  $FFMPEG_URL
  SHA-256 $FFMPEG_SHA256
with: ./configure ${FFMPEG_CONFIGURE[*]}
(packaging/build_mac_app.sh in https://codeberg.org/KintsugiUwU/flalac)
EOF
    rm -rf "$SRC"
    echo "$STAMP" >"$FFMPEG_DIR/.stamp"
fi

FFMPEG=$FFMPEG_DIR/bin/ffmpeg
[ "$(lipo -archs "$FFMPEG")" = arm64 ] || { echo "$FFMPEG is not arm64" >&2; exit 1; }
"${CLEAN_ENV[@]}" "$FFMPEG" -hide_banner -encoders | grep -q ' alac ' \
    || { echo "$FFMPEG has no alac encoder" >&2; exit 1; }
"${CLEAN_ENV[@]}" "$FFMPEG" -hide_banner -decoders | grep -q ' flac ' \
    || { echo "$FFMPEG has no flac decoder" >&2; exit 1; }

# -------------------------------------
# 2. The app, with PyInstaller in a separate build environment
# -------------------------------------
# The project's locked runtime dependencies (no dev group) go into packaging/build/venv
# with a uv-managed CPython (built for macOS 11); PyInstaller is added only for this run
# and never becomes a dependency of flalac. The project .venv is not touched.
echo "Building flalac.app with PyInstaller $PYINSTALLER_VERSION..."
rm -rf "$BUILD/pyinstaller" "$APP" "$DIST/flalac"
FLALAC_FFMPEG_DIR=$FFMPEG_DIR FLALAC_MIN_MACOS=$MIN_MACOS UV_PROJECT_ENVIRONMENT=$BUILD/venv \
    uv run --project "$ROOT" --locked --no-dev --no-editable --reinstall-package flalac \
    --managed-python --with "pyinstaller==$PYINSTALLER_VERSION" \
    pyinstaller --noconfirm --clean --log-level WARN \
    --distpath "$DIST" --workpath "$BUILD/pyinstaller" "$PKG/flalac.spec"
rm -rf "$DIST/flalac"  # the plain folder PyInstaller makes next to the .app

# -------------------------------------
# 3. Check that the app is self-contained
# -------------------------------------
echo "Checking every executable and library in the app..."
MINOS=0
find "$APP" -type f -print0 | xargs -0 file --mime-type \
    | grep -v ' (for architecture ' | sed -n 's/:[[:space:]]*application\/x-mach-binary$//p' \
    >"$BUILD/machos.txt"
while IFS= read -r MACHO; do
    lipo -archs "$MACHO" | grep -qw arm64 || { echo "not arm64: $MACHO" >&2; exit 1; }
    otool -l "$MACHO" | awk '/cmd LC_(LOAD|LOAD_WEAK|REEXPORT|LAZY_LOAD)_DYLIB$/{d=1}
        d && $1 == "name" {print $2; d=0}' | while IFS= read -r LIB; do
        case $LIB in
            /usr/lib/* | /System/Library/* | @rpath/* | @loader_path/* | @executable_path/*) ;;
            *) echo "$MACHO links $LIB, which is not part of macOS or the app" >&2; exit 1 ;;
        esac
    done
    for V in $(otool -l "$MACHO" | awk '/cmd LC_BUILD_VERSION/{b=1} b && $1 == "minos" {print $2; b=0}
        /cmd LC_VERSION_MIN_MACOSX/{m=1} m && $1 == "version" {print $2; m=0}'); do
        MINOS=$(printf '%s\n%s\n' "$MINOS" "$V" | sort -V | tail -n 1)
    done
done <"$BUILD/machos.txt"
if [ "$(printf '%s\n%s\n' "$MINOS" "$MIN_MACOS" | sort -V | tail -n 1)" != "$MIN_MACOS" ]; then
    echo "A file in the app needs macOS $MINOS, newer than $MIN_MACOS in Info.plist" >&2
    exit 1
fi
codesign --verify --deep --strict "$APP"

echo "Running the smoke test inside the app, with PATH=/usr/bin:/bin only..."
"${CLEAN_ENV[@]}" FLALAC_SMOKE_TEST=1 "$APP/Contents/MacOS/flalac"

echo
echo "Build complete: $APP"
echo "  size: $(du -sh "$APP" | cut -f1), $(wc -l <"$BUILD/machos.txt" | tr -d ' ') Mach-O files"
echo "  needs: macOS $MIN_MACOS or later on Apple Silicon (highest minos in the app: $MINOS)"
