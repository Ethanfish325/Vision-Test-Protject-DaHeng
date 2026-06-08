# -*- coding: utf-8 -*-

import os
import shutil

hidden_imports = [
    'vision.tools.preprocess',
    'vision.tools.feature_extract',
    'vision.tools.geometry',
    'vision.tools.measure',
    'vision.tools.recognize',
    'vision.tools.utility',
]

# 排除不需要的模块以减小打包体积
excluded_imports = [
    # --- PyQt5 不需要的模块 ---
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
    'PyQt5.QtQuickWidgets',
    # --- 科学计算/可视化库（未使用） ---
    'matplotlib',
    'scipy',
    'notebook',
    'IPython',
    'PIL',
    'pandas',
    'sympy',
    # --- OpenCV 不需要的子模块 ---
    'cv2.gapi',
    'cv2.dnn',
    'cv2.ml',
    'cv2.flann',
    'cv2.saliency',
    'cv2.xfeatures2d',
    'cv2.ximgproc',
    'cv2.xphoto',
    'cv2.photo',
    'cv2.stitching',
    # --- 其他不需要的 ---
    'tornado',
    'jinja2',
]

# ============================================================
# MvImport 目录 - 海康威视相机 SDK
# ============================================================
# 将 MvImport Python 模块作为 data 打包
_mvimport_dir = 'MvImport'
datas = []
binaries = []

if os.path.exists(_mvimport_dir):
    datas.append((_mvimport_dir, _mvimport_dir))
    print(f"[INFO] 找到 MvImport 目录，已加入打包数据")
else:
    print(f"[WARN] 未找到 MvImport 目录，相机功能将不可用")
    print(f"[WARN] 请从工控机拷贝 MvImport 目录到项目根目录后重新打包")

# 查找 MVS Runtime 安装目录（64位）
# MvCameraControl.dll 依赖大量其他 DLL（MVGigEVisionSDK.dll、MvUsb3vTL.dll 等），
# 需要将整个 Runtime 目录的 DLL 都打包进去
#
# 注意：PyInstaller 的 pyimod03_ctypes.py 拦截了 WinDLL 调用，
# 其 _frozen_name() 函数只在 sys._MEIPASS（即 _internal/）下搜索 DLL。
# 因此 DLL 必须放在 _internal/ 根目录下，不能放在子目录中。
_mvs_runtime_dirs = [
    os.path.join(os.environ.get('ProgramFiles', 'C:\\Program Files'),
                 'Common Files', 'MVS', 'Runtime', 'Win64_x64'),
    os.path.join(os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'),
                 'Common Files', 'MVS', 'Runtime', 'Win64_x64'),
]

_mvs_runtime_dir = None
for _dir in _mvs_runtime_dirs:
    if os.path.isdir(_dir):
        _mvs_runtime_dir = _dir
        print(f"[INFO] 找到 MVS Runtime 目录: {_dir}")
        break

if _mvs_runtime_dir:
    # 将 MVS Runtime 目录下所有 DLL 打包到 _internal/ 根目录（即 sys._MEIPASS）
    # 这样 PyInstaller 的 _frozen_name() 就能找到它们
    for _f in os.listdir(_mvs_runtime_dir):
        if _f.lower().endswith('.dll'):
            _src = os.path.join(_mvs_runtime_dir, _f)
            binaries.append((_src, '.'))  # '.' 表示 _internal/ 根目录
    print(f"[INFO] MVS Runtime DLL 已全部加入打包 binaries（到 _internal/ 根目录）")
else:
    print(f"[WARN] 未找到 MVS Runtime 目录，相机功能将不可用")
    print(f"[WARN] 请安装海康威视 MVS SDK")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook.py'],
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
    icon=None,
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

# ============================================================
# 后处理：删除不需要的大体积 DLL 文件（可安全删除，项目未使用）
# ============================================================
# 这些 DLL 是 PyQt5 自带的，但项目代码中没有使用对应的功能
_QT_BIN_DIR = os.path.join('dist', 'VisionSystem', 'PyQt5', 'Qt5', 'bin')
_DLL_TO_REMOVE = [
    'opengl32sw.dll',       # ~20MB - 软件 OpenGL 渲染器
    'libGLESv2.dll',        # ~3.3MB - OpenGL ES 模拟
    'd3dcompiler_47.dll',   # ~4MB - DirectX 编译器
    'Qt5Quick.dll',         # ~4MB - QML 快速界面
    'Qt5Qml.dll',           # ~3.5MB - QML 引擎
    'Qt5QmlModels.dll',     # ~0.4MB - QML 模型
    'Qt5Network.dll',       # ~1.3MB - 网络模块
    'Qt5Designer.dll',      # ~4.4MB - Qt Designer
    'Qt5Svg.dll',           # ~0.3MB - SVG 渲染
    'Qt5DBus.dll',          # ~0.4MB - D-Bus 通信
]

# 删除不需要的 Qt 翻译文件（.qm），只保留中文和英文
_QT_TRANSLATIONS_DIR = os.path.join('dist', 'VisionSystem', 'PyQt5', 'Qt5', 'translations')

for dll_name in _DLL_TO_REMOVE:
    dll_path = os.path.join(_QT_BIN_DIR, dll_name)
    if os.path.exists(dll_path):
        try:
            os.remove(dll_path)
            print(f"[后处理] 已删除: {dll_name}")
        except Exception as e:
            print(f"[后处理] 删除失败 {dll_name}: {e}")

# 只保留中文和英文翻译文件，删除其他语言的 .qm 文件
if os.path.exists(_QT_TRANSLATIONS_DIR):
    for f in os.listdir(_QT_TRANSLATIONS_DIR):
        if f.endswith('.qm'):
            # 保留 qt_zh_CN.qm, qt_zh_TW.qm, qtbase_zh_CN.qm, qt_en.qm, qtbase_en.qm
            keep = False
            for lang in ['zh_CN', 'zh_TW', 'zh', '_en']:
                if lang in f:
                    keep = True
                    break
            if not keep:
                try:
                    os.remove(os.path.join(_QT_TRANSLATIONS_DIR, f))
                    print(f"[后处理] 已删除翻译文件: {f}")
                except Exception as e:
                    print(f"[后处理] 删除翻译文件失败 {f}: {e}")
