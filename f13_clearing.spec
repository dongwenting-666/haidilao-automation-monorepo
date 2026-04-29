# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['libs/sap-gui/f13_app.py'],
    pathex=['libs/sap-gui/src', 'libs/vpn/src'],
    binaries=[],
    datas=[],
    hiddenimports=['sap_gui', 'sap_gui.processes.f13', 'sap_gui.session', 'sap_gui.navigation', 'sap_gui.errors', 'sap_gui.export', 'vpn', 'vpn.connect', 'vpn._darwin', 'dotenv'],
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
    name='f13_clearing',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
