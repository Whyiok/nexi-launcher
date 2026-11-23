# -*- mode: python ; coding: utf-8 -*-
#
# Folder build used by the installer and published as NexiLauncher.zip. The
# executable is a plain PyInstaller onedir bootloader and loads its runtime
# files from _internal next to it, so it is never unpacked into %TEMP% and
# behaves like an ordinary installed program for antivirus products.


a = Analysis(
    ['../launcher.py'],
    pathex=['..'],
    binaries=[],
    datas=[('../webui', 'webui')],
    hiddenimports=[],
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
    name='NexiLauncher',
    icon='../assets/nexi.ico',
    version='../assets/version_info_app.txt',
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
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='NexiLauncher',
)
