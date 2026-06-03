# -*- coding: utf-8 -*-

hidden_imports = [
    'vision.tools.preprocess',
    'vision.tools.feature_extract',
    'vision.tools.geometry',
    'vision.tools.measure',
    'vision.tools.recognize',
    'vision.tools.utility',
]

excluded_imports = [
    'PyQt5.QtWebEngine',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebChannel',
    'PyQt5.QtBluetooth',
    'PyQt5.QtNfc',
    'PyQt5.QtMultimedia',
    'PyQt5.QtSensors',
    'PyQt5.QtSerialPort',
    'PyQt5.QtXmlPatterns',
    'PyQt5.QtHelp',
    'PyQt5.QtDesigner',
    'PyQt5.QtTest',
    'PyQt5.QtSql',
    'PyQt5.QtNetwork',
    'PyQt5.QtPositioning',
    'PyQt5.QtLocation',
    'PyQt5.QtQuick',
    'PyQt5.QtQml',
    'PyQt5.QtSvg',
    'PyQt5.QtPrintSupport',
    'matplotlib',
    'scipy',
    'notebook',
    'IPython',
    'PIL',
]

datas = [
    ('MvImport', 'MvImport'),
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_imports,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VisionSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VisionSystem',
)
