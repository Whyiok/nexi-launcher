# -*- mode: python ; coding: utf-8 -*-


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
    a.binaries,
    a.datas,
    [],
    name='Nexi-Portable',
    icon='../assets/nexi.ico',
    version='../assets/version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed executables are the single biggest trigger for antivirus
    # false positives: packed bootloaders look like malware heuristics. The
    # exe is larger without it but flags much less often.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
