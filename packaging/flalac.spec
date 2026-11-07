# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for flalac.app (Apple Silicon). Build it with packaging/build_mac_app.sh,
# which builds ffmpeg first and passes its install folder in FLALAC_FFMPEG_DIR.
#
# Entry: packaging/launcher.py puts the bundled ffmpeg first on PATH, then runs
# flalac.macapp:main when src/flalac/macapp.py exists, else the self-test in smoke_entry.py.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import flalac

HERE = Path(SPECPATH)
ROOT = HERE.parent
FFMPEG_DIR = Path(os.environ["FLALAC_FFMPEG_DIR"])
MIN_MACOS = os.environ.get("FLALAC_MIN_MACOS", "11.0")
BUNDLE_ID = "com.davidepetris.flalac"

if (ROOT / "src" / "flalac" / "macapp.py").is_file():
    print("flalac.spec: entry flalac.macapp:main")
else:
    print("flalac.spec: src/flalac/macapp.py not found, entry is the smoke test")

licenses = [(str(ROOT / "LICENSE"), "licenses/flalac")]
licenses += [(str(p), "licenses/ffmpeg") for p in sorted((FFMPEG_DIR / "licenses").iterdir())]

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(HERE)],
    # The ffmpeg executable goes to Contents/Frameworks/bin, which launcher.py puts on PATH.
    binaries=[(str(FFMPEG_DIR / "bin" / "ffmpeg"), "bin")],
    # Templates, static files and fonts that flalac reads next to its modules.
    datas=collect_data_files("flalac") + licenses,
    # Every flalac module (and so its dependencies), also when the entry is the smoke test.
    hiddenimports=collect_submodules("flalac") + ["smoke_entry"],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="flalac",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,  # ad-hoc signature
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="flalac")
app = BUNDLE(
    coll,
    name="flalac.app",
    icon=str(HERE / "flalac.icns"),
    bundle_identifier=BUNDLE_ID,
    version=flalac.__version__,
    info_plist={
        "CFBundleName": "flalac",
        "CFBundleDisplayName": "flalac",
        "CFBundleVersion": flalac.__version__,
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSUIElement": True,  # no Dock icon: it talks through dialogs and notifications
        "NSHumanReadableCopyright": "GPL-3.0-or-later. Includes FFmpeg (LGPL-2.1-or-later).",
    },
)
