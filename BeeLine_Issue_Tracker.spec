# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH).resolve()
APP_DIR = ROOT / "app"

datas = [
    (str(ROOT / "templates" / "beeline_config.template.json"), "templates"),
    (str(ROOT / "templates" / "beeline.template.sqlite"), "templates"),
    (str(ROOT / "templates" / "beeline_archive.template.xlsx"), "templates"),
    (str(ROOT / "assets" / "branding" / "nolato_logo.png"), "assets/branding"),
    (str(ROOT / "assets" / "branding" / "nolato_logo_placeholder.png"), "assets/branding"),
]

hiddenimports = []
excludes = [
    "_pytest",
    "app_future",
    "matplotlib",
    "numpy",
    "pandas",
    "PIL",
    "pytest",
    "scipy",
    "tests",
]

a = Analysis(
    ["run_beeline.py"],
    pathex=[str(ROOT), str(APP_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BeeLine Issue Tracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BeeLine Issue Tracker",
)
