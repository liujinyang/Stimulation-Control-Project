# -*- mode: python ; coding: utf-8 -*-
#
# Builds for whichever platform PyInstaller is run on - PyInstaller cannot
# cross-compile, so to get a macOS build this file must be run with
# PyInstaller installed on an actual Mac (`pyinstaller "Stimulation Control.spec"`).
# On macOS it additionally produces a double-clickable Stimulation Control.app
# via BUNDLE() below; on Windows that step is skipped, same as before.

import sys

is_macos = sys.platform == "darwin"
# UPX-compressed binaries are a common source of Gatekeeper/codesign trouble
# on macOS (can fail to launch, especially on Apple Silicon) - skip it there.
use_upx = not is_macos

a = Analysis(
    ['run_app.py'],
    pathex=['..'],  # parent folder, so 'perfusion_app.*' imports resolve
    binaries=[],
    datas=[],
    hiddenimports=['openpyxl', 'serial.tools.list_ports_osx', 'serial.tools.list_ports_posix'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Stimulation Control',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=use_upx,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=use_upx,
    upx_exclude=[],
    name='Stimulation Control',
)

if is_macos:
    app = BUNDLE(
        coll,
        name='Stimulation Control.app',
        icon=None,
        bundle_identifier='org.janelia.stimulationcontrol',
        info_plist={
            'NSHighResolutionCapable': 'True',
            'NSRequiresAquaSystemAppearance': 'False',
        },
    )
