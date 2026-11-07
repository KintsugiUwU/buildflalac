#!/bin/bash
# =====================================
# Flalac.app (SwiftUI front end) build script
# =====================================
# Compiles macos/Sources with swiftc from the Command Line Tools (no Xcode project) and
# assembles macos/build/Flalac.app for Apple Silicon, macOS 11 or later.
#
#   ./build.sh                          the app, using $FLALAC_ENGINE at run time
#   ENGINE_DIR=<folder> ./build.sh      with the engine folder copied into
#                                       Contents/Resources/engine (must hold flalac-engine)
#   DEV=1 ./build.sh                    a development build in build/dev/ (bundle id
#                                       com.davidepetris.flalac.dev, own settings) that
#                                       dev/ctl.sh can drive; see README.md
# =====================================
set -euo pipefail

cd "$(dirname "$0")"
HERE=$PWD
MIN_MACOS=11.0
BUNDLE_ID=com.davidepetris.flalac
OUT=$HERE/build
SWIFT_FLAGS=()
SOURCES=("$HERE"/Sources/*.swift)
if [ "${DEV:-0}" = 1 ]; then
    BUNDLE_ID=$BUNDLE_ID.dev
    OUT=$HERE/build/dev
    SWIFT_FLAGS+=(-D FLALAC_DEV)
    SOURCES+=("$HERE/dev/DevControl.swift")
fi
APP=$OUT/Flalac.app
VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' ../pyproject.toml | head -n 1)
VERSION=${VERSION:-0.0.0}
SDK=$(xcrun --sdk macosx --show-sdk-path)
TOOLCHAIN=$(dirname "$(dirname "$(xcrun --find swiftc)")")
# Swift concurrency is part of macOS from 12 on; macOS 11 gets Apple's back-deployed copy.
CONCURRENCY=$TOOLCHAIN/lib/swift-5.5/macosx/libswift_Concurrency.dylib

echo "Building Flalac.app $VERSION (arm64, macOS $MIN_MACOS or later)"
[ -f "$CONCURRENCY" ] || { echo "Missing $CONCURRENCY (Command Line Tools too old?)" >&2; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" "$APP/Contents/Frameworks"

swiftc \
    -target "arm64-apple-macos$MIN_MACOS" \
    -sdk "$SDK" \
    -swift-version 6 \
    -parse-as-library \
    -O \
    ${SWIFT_FLAGS[@]+"${SWIFT_FLAGS[@]}"} \
    -framework SwiftUI -framework AppKit -framework Security -framework UserNotifications \
    -Xlinker -rpath -Xlinker @executable_path/../Frameworks \
    -o "$APP/Contents/MacOS/flalac" \
    "${SOURCES[@]}"

cp "$CONCURRENCY" "$APP/Contents/Frameworks/"
cp ../packaging/flalac.icns "$APP/Contents/Resources/flalac.icns"

cat >"$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleExecutable</key><string>flalac</string>
    <key>CFBundleIconFile</key><string>flalac</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
    <key>CFBundleName</key><string>Flalac</string>
    <key>CFBundleDisplayName</key><string>Flalac</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>LSMinimumSystemVersion</key><string>$MIN_MACOS</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
    <key>NSHumanReadableCopyright</key><string>© 2026 KintsugiUwU. GPL-3.0-or-later.</string>
    <key>NSPrincipalClass</key><string>NSApplication</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSSupportsSuddenTermination</key><false/>
    <key>NSAppleEventsUsageDescription</key><string>Flalac adds, moves and removes songs in the iTunes or Music library to match the ALAC folder, and reads and sets their play counts.</string>
    <key>NSNetworkVolumesUsageDescription</key><string>Flalac reads the FLAC folder on the network share.</string>
    <key>NSRemovableVolumesUsageDescription</key><string>Flalac writes the ALAC copy to the music drive.</string>
</dict>
</plist>
EOF
printf 'APPL????' >"$APP/Contents/PkgInfo"

if [ -n "${ENGINE_DIR:-}" ]; then
    [ -x "$ENGINE_DIR/flalac-engine" ] || { echo "$ENGINE_DIR/flalac-engine is missing or not executable" >&2; exit 1; }
    echo "Copying the engine from $ENGINE_DIR"
    ditto "$ENGINE_DIR" "$APP/Contents/Resources/engine"
else
    echo "No ENGINE_DIR: the app runs the engine named by FLALAC_ENGINE."
fi

codesign --force --deep -s - "$APP"
codesign --verify --deep --strict "$APP"

echo "Built $APP ($(du -sh "$APP" | cut -f1))"
