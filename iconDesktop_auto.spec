# -*- mode: python ; coding: utf-8 -*-
# 本文件由 build.py 根据 build_config.json 自动生成，请勿手改；
# 要改打包参数请编辑 build_config.json。
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('win32com')

a = Analysis(
    ['E:\\BOVC\\Project\\iconDesktop\\main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy'],
    noarchive=False,
)

# 剔除用不到的二进制（片段匹配，来自 build_config.json 的 strip_binaries）
strip_binaries = ['opengl32sw', 'qt6quick', 'qt6qml', 'qt6pdf', 'qt6virtualkeyboard', 'qt6opengl', 'qt6network', 'qtnetwork.pyd', 'libcrypto-3-x64', 'libssl-3-x64', 'platforminputcontexts', 'qmltooling', 'qpdf', 'pythonwin', 'mfc140u', 'win32ui']
a.binaries = [b for b in a.binaries
              if not any(p in b[0].lower() for p in strip_binaries)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='iconDesktop',
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
    upx_exclude=[],
    runtime_tmpdir=None,
)
