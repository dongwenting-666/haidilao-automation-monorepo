# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for KSB1 会计检查 GUI."""

import os
import sys

block_cipher = None
is_windows = sys.platform == 'win32'
is_macos = sys.platform == 'darwin'

# Resolve paths relative to this spec file
# SPECPATH is set by PyInstaller to the directory containing the spec file
spec_dir = SPECPATH if 'SPECPATH' in dir() else os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(spec_dir, '..', '..'))

a_hiddenimports = [
    'openpyxl',
    'ollama',
    'httpx',
    'et_xmlfile',
    'ksb1_accounting_check',
    'ksb1_accounting_check.analyze',
    'ksb1_accounting_check.rules',
    'ksb1_accounting_check.llm',
    'sap_gui',
    'sap_gui.session',
    'sap_gui.navigation',
    'sap_gui.export',
    'sap_gui.errors',
    'sap_gui.processes.ksb1',
    'ollama_client',
    'ollama_client.client',
]

if is_windows:
    a_hiddenimports.extend([
        'win32com',
        'win32com.client',
        'pythoncom',
        'pywintypes',
    ])

a = Analysis(
    [os.path.join(spec_dir, 'src', 'ksb1_accounting_check_gui', '__main__.py')],
    pathex=[
        os.path.join(repo_root, 'projects', 'ksb1-accounting-check', 'src'),
        os.path.join(repo_root, 'projects', 'ksb1-accounting-check-gui', 'src'),
        os.path.join(repo_root, 'libs', 'sap-gui', 'src'),
        os.path.join(repo_root, 'libs', 'ollama-client', 'src'),
    ],
    binaries=[],
    datas=[
        # Bundle data files into data/ directory
        (os.path.join(repo_root, 'projects', 'ksb1-accounting-check', 'src',
                      'ksb1_accounting_check', '报表科目.xlsx'), 'data'),
        (os.path.join(repo_root, 'libs', 'sap-gui', 'src', 'sap_gui',
                      'processes', 'ksb1', 'cost_centers.txt'), 'data'),
        (os.path.join(repo_root, 'projects', 'ksb1-accounting-check', 'src',
                      'ksb1_accounting_check', 'prompt.md'), 'data'),
    ],
    hiddenimports=a_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if is_macos:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='KSB1会计检查',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
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
        upx=True,
        upx_exclude=[],
        name='KSB1会计检查',
    )

    app = BUNDLE(
        coll,
        name='KSB1会计检查.app',
        icon=None,
        bundle_identifier='com.chloedong.ksb1-accounting-check',
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='KSB1会计检查',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # No console window
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
