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
# 数据目录打包
# ============================================================
datas = []
binaries = []

# --- model/ 目录（模板匹配图片） ---
_model_dir = 'model'
if os.path.exists(_model_dir):
    for _root, _dirs, _files in os.walk(_model_dir):
        for _f in _files:
            _src = os.path.join(_root, _f)
            _dst = os.path.relpath(_root, '.')
            datas.append((_src, _dst))
    print(f"[INFO] model/ 目录已加入打包数据")
else:
    print(f"[WARN] 未找到 model/ 目录")

# --- data/ 目录（配置文件、用户数据等） ---
_data_dir = 'data'
if os.path.exists(_data_dir):
    for _root, _dirs, _files in os.walk(_data_dir):
        for _f in _files:
            _src = os.path.join(_root, _f)
            _dst = os.path.relpath(_root, '.')
            datas.append((_src, _dst))
    print(f"[INFO] data/ 目录已加入打包数据")
else:
    print(f"[WARN] 未找到 data/ 目录")

# ============================================================
# 大恒 GalaxySDK DLL 打包
# ============================================================
# gxipy 模块通过 WinDLL('GxIAPI.dll') 和 WinDLL('DxImageProc.dll') 加载
# PyInstaller 的 pyimod03_ctypes.py 拦截了 WinDLL 调用，
# 其 _frozen_name() 函数只在 sys._MEIPASS（即 _internal/）下搜索 DLL。
# 因此 DLL 必须放在 _internal/ 根目录下，不能放在子目录中。

# 优先使用项目根目录下的 DLL（便携式部署）
_daheng_dlls = []
for _dll_name in ['GxIAPI.dll', 'DxImageProc.dll']:
    _local_dll = os.path.join(os.getcwd(), _dll_name)
    if os.path.exists(_local_dll):
        _daheng_dlls.append(_local_dll)
        print(f"[INFO] 找到大恒 DLL（项目目录）: {_local_dll}")
    else:
        # 回退到 SDK 安装目录
        _sdk_dll = os.path.join(
            os.environ.get('ProgramFiles', 'C:\\Program Files'),
            'Daheng Imaging', 'GalaxySDK', 'APIDll', 'Win64', _dll_name
        )
        if os.path.exists(_sdk_dll):
            _daheng_dlls.append(_sdk_dll)
            print(f"[INFO] 找到大恒 DLL（SDK 目录）: {_sdk_dll}")
        else:
            print(f"[WARN] 未找到大恒 DLL: {_dll_name}，相机功能将不可用")

for _dll_path in _daheng_dlls:
    binaries.append((_dll_path, '.'))  # '.' 表示 _internal/ 根目录

# ============================================================
# NMC 运动控制卡 DLL 打包
# ============================================================
# core/nmc_sdk.py 通过 ctypes.CDLL('MCDLL_NET.dll') 加载
# PyInstaller 无法自动追踪 ctypes.CDLL 调用，需要手动添加
# nmc_sdk.load_dll() 的搜索路径包括 os.getcwd()（exe 目录）和脚本目录
# 因此 DLL 需要放在 _internal/ 根目录下
_nmc_dll_name = 'MCDLL_NET.dll'
_nmc_dll_path = os.path.join(os.getcwd(), _nmc_dll_name)
if os.path.exists(_nmc_dll_path):
    binaries.append((_nmc_dll_path, '.'))  # '.' 表示 _internal/ 根目录
    print(f"[INFO] 找到 NMC DLL: {_nmc_dll_path}")
else:
    print(f"[WARN] 未找到 NMC DLL: {_nmc_dll_name}，运动控制功能将不可用")

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
    icon='data/icon.png',
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
# 后处理：删除顶层多余的独立 exe（只保留目录模式）
# ============================================================
# EXE() 会生成 dist/VisionSystem.exe（单文件），
# COLLECT() 会生成 dist/VisionSystem/VisionSystem.exe（目录模式）。
# 删除顶层的单文件 exe，避免两个 exe 并存。
_TOP_LEVEL_EXE = os.path.join('dist', 'VisionSystem.exe')
if os.path.exists(_TOP_LEVEL_EXE):
    try:
        os.remove(_TOP_LEVEL_EXE)
        print(f"[后处理] 已删除顶层独立 exe: {_TOP_LEVEL_EXE}")
    except Exception as e:
        print(f"[后处理] 删除顶层 exe 失败: {e}")

# ============================================================
# 后处理：将 MCDLL_NET.dll 复制到 exe 同级目录
# ============================================================
# nmc_sdk.py 的 load_dll() 会搜索 os.getcwd()（即 exe 所在目录）
# 而 binaries 打包到 _internal/，所以需要额外复制一份到 exe 目录
_NMC_DLL_SRC = os.path.join('dist', 'VisionSystem', '_internal', 'MCDLL_NET.dll')
_NMC_DLL_DST = os.path.join('dist', 'VisionSystem', 'MCDLL_NET.dll')
if os.path.exists(_NMC_DLL_SRC) and not os.path.exists(_NMC_DLL_DST):
    try:
        import shutil
        shutil.copy2(_NMC_DLL_SRC, _NMC_DLL_DST)
        print(f"[后处理] 已复制 MCDLL_NET.dll 到 exe 同级目录")
    except Exception as e:
        print(f"[后处理] 复制 MCDLL_NET.dll 失败: {e}")

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
