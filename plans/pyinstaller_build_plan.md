# PyInstaller 打包计划

## 1. 项目概述

**项目名称**: 视觉检测系统 (VisionTest2.0)  
**入口文件**: [`main.py`](../main.py)  
**Python 版本**: 3.9 (基于 dist 中 `python39.dll`)  
**打包工具**: PyInstaller  
**输出目标**: 便携版 exe 文件夹，部署到工程机运行  
**核心要求**: 尽可能减小体积（工程机性能较差），所有功能都需要

---

## 2. 项目结构分析

```
VisionTest2.0/
├── main.py                    # 入口文件
├── runtime_hook.py            # PyInstaller runtime hook (DLL 路径设置)
├── cleanup_after_build.bat    # 打包后清理脚本
├── main.spec                  # 现有 PyInstaller 配置文件（推荐保留并增强）
├── requirements.txt           # 依赖清单
├── camera_manager.py          # 相机管理模块
├── core/                      # 核心模块
│   ├── __init__.py
│   ├── config_manager.py      # 配置管理
│   ├── inspection_workflow.py # 检测工作流
│   ├── log_manager.py         # 日志管理
│   ├── nmc_sdk.py             # 运动控制卡 SDK (依赖 MCDLL_NET.dll)
│   ├── paths.py               # 路径管理
│   ├── product_manager.py     # 产品管理
│   ├── result_storage.py      # 结果存储
│   ├── serial_comm.py         # 串口通信 (依赖 pyserial)
│   └── serial_test_workflow.py
├── ui/                        # UI 模块
│   ├── __init__.py
│   ├── constants.py
│   ├── inspection_panel.py
│   ├── main_window.py
│   └── widgets/               # 子组件
│       ├── camera_panel.py
│       ├── flow_canvas.py
│       ├── nmc_control_dialog.py
│       ├── operator_toolbox.py
│       ├── param_config_dialog.py
│       ├── pipeline_editor.py
│       ├── result_panel.py
│       ├── serial_dialog.py
│       ├── step_slot_widget.py
│       └── zoomable_label.py
├── vision/                    # 视觉处理模块
│   ├── __init__.py
│   ├── pipeline.py            # 流水线引擎 (动态加载 tools)
│   ├── vision_engine.py       # 视觉引擎
│   └── tools/                 # 视觉工具集
│       ├── base_tool.py
│       ├── preprocess.py      # 预处理工具
│       ├── feature_extract.py # 特征提取
│       ├── geometry.py        # 几何检测
│       ├── measure.py         # 测量工具
│       ├── recognize.py       # 识别工具
│       └── utility.py         # 工具函数
├── gxipy/                     # 大恒相机 SDK (纯 Python 包)
│   ├── __init__.py
│   ├── dxwrapper.py
│   ├── gxiapi.py
│   ├── gxidef.py
│   └── gxwrapper.py
├── data/                      # 运行时数据
│   ├── icon.png               # ✅ 需打包 - 应用图标
│   ├── users.json             # ✅ 需打包 - 用户数据
│   ├── products/              # ✅ 需打包 - 产品配置
│   ├── schemes/               # ✅ 需打包 - 检测方案
│   ├── errors/                # ❌ 排除 - 运行时生成的错误图片
│   └── logs/                  # ❌ 排除 - 运行时生成的日志文件
├── model/                     # 模板图片资源
│   ├── long_mat.jpg
│   ├── mat1.png
│   ├── mat2.png
│   ├── title.jpg
│   ├── title.png
│   ├── title1.jpg
│   └── title1.png
├── GxIAPI.dll                 # 大恒相机 SDK DLL
├── DxImageProc.dll            # 大恒图像处理 DLL
└── MCDLL_NET.dll              # 运动控制卡 DLL
```

---

## 3. 依赖分析

### Python 包依赖 (来自 [`requirements.txt`](../requirements.txt))
| 包名 | 用途 | 备注 |
|------|------|------|
| PyQt5 >= 5.15.0 | GUI 框架 | 需包含 Qt 插件、翻译文件 |
| opencv-python >= 4.5.0 | 图像处理 | 含 ffmpeg DLL |
| numpy >= 1.21.0 | 数值计算 | |
| pyserial >= 3.5 | 串口通信 | |

### 内置依赖
| 模块 | 类型 | 说明 |
|------|------|------|
| `gxipy/` | 纯 Python 包 | 大恒相机 SDK，已内置于项目 |
| `GxIAPI.dll` | 原生 DLL | 大恒相机 SDK，需打包到 `_internal/` |
| `DxImageProc.dll` | 原生 DLL | 大恒图像处理，需打包到 `_internal/` |
| `MCDLL_NET.dll` | 原生 DLL | 运动控制卡 SDK，需打包到 `_internal/` 和 exe 同级目录 |

### 隐式导入 (需在 .spec 中显式声明)
- `vision/tools/` 下的工具类通过 [`pipeline.py`](../vision/pipeline.py) 中的 `importlib.import_module()` 动态加载
- `gxipy` 的子模块通过 `from gxipy.gxiapi import *` 导入
- `serial.tools.list_ports` 是 `pyserial` 的隐式子模块

---

## 4. 打包策略

### 4.1 打包模式
- **模式**: 单文件夹打包 (`--onedir`)
- **控制台**: 隐藏控制台 (`--noconsole`)
- **图标**: 使用 [`data/icon.png`](../data/icon.png)
- **UPX**: 不启用（工程机未安装）

### 4.2 数据文件打包
| 源路径 | 目标路径 (_internal 内) | 说明 |
|--------|------------------------|------|
| `data/` | `data/` | **排除** `errors/` 和 `logs/` 子目录 |
| `model/` | `model/` | 模板图片资源 |
| `GxIAPI.dll` | `.` | 大恒相机 DLL |
| `DxImageProc.dll` | `.` | 大恒图像处理 DLL |
| `MCDLL_NET.dll` | `.` | 运动控制卡 DLL |

### 4.3 Runtime Hook
使用现有的 [`runtime_hook.py`](../runtime_hook.py) 作为 runtime hook，在程序启动时将 `_internal/` 目录添加到 DLL 搜索路径中。

---

## 5. main.spec 与新 spec 方案对比分析

### 5.1 结论：保留 [`main.spec`](../main.spec) 并增强

**推荐保留 [`main.spec`](../main.spec)**，因为它：
1. ✅ 已通过验证，能成功打包出可运行的程序
2. ✅ 具有智能的 DLL 发现和 datas 收集机制
3. ✅ 内嵌了完整的后处理清理逻辑
4. ✅ 处理了 `MCDLL_NET.dll` 复制到 exe 同级目录的特殊需求

**只需对 [`main.spec`](../main.spec) 做 5 处修改**（详见第 7 章）。

---

## 6. 极致体积优化方案

### 6.1 体积分析（估算）

| 组件 | 估算体积 | 优化措施 |
|------|---------|---------|
| PyQt5 Qt DLL | ~80MB | 排除不需要的 Qt 模块 + 删除多余 DLL |
| opencv-python | ~50MB | 排除不需要的 cv2 子模块 |
| numpy | ~30MB | 无法大幅缩减（核心依赖） |
| Python 标准库 | ~20MB | 排除 tkinter 等 |
| gxipy + DLL | ~15MB | 必要，无法缩减 |
| model/ 图片 | ~5MB | 必要，无法缩减 |
| data/ 配置 | ~1MB | 必要，无法缩减 |
| **合计** | **~200MB** | **优化后目标 ~120-140MB** |

### 6.2 hiddenimports 增强（确保功能完整）

```python
hidden_imports = [
    # 原有 - 视觉工具动态加载
    'vision.tools.preprocess',
    'vision.tools.feature_extract',
    'vision.tools.geometry',
    'vision.tools.measure',
    'vision.tools.recognize',
    'vision.tools.utility',
    # 新增 - PyQt5 必要绑定
    'PyQt5.sip',
    # 新增 - gxipy 子模块
    'gxipy', 'gxipy.gxiapi', 'gxipy.gxidef',
    'gxipy.gxwrapper', 'gxipy.dxwrapper',
    # 新增 - pyserial 隐式子模块
    'serial.tools.list_ports',
    # 新增 - OpenCV 数据
    'cv2.data',
]
```

### 6.3 excludes 极致优化（最大程度减体积）

```python
excluded_imports = [
    # === PyQt5 不需要的模块（可节省 ~50MB） ===
    'PyQt5.QtWebEngine',        # 浏览器引擎
    'PyQt5.QtWebEngineWidgets', # 浏览器组件
    'PyQt5.QtWebEngineCore',    # 浏览器核心
    'PyQt5.QtWebChannel',       # Web 通信通道
    'PyQt5.QtWebSockets',       # WebSocket
    'PyQt5.QtBluetooth',        # 蓝牙
    'PyQt5.QtNfc',              # NFC
    'PyQt5.QtMultimedia',       # 多媒体
    'PyQt5.QtMultimediaWidgets',# 多媒体组件
    'PyQt5.QtSensors',          # 传感器
    'PyQt5.QtSerialPort',       # 串口（项目用 pyserial，不用 Qt 的）
    'PyQt5.QtXmlPatterns',      # XML 模式
    'PyQt5.QtHelp',             # 帮助系统
    'PyQt5.QtDesigner',         # UI 设计器
    'PyQt5.QtTest',             # 测试框架
    'PyQt5.QtSql',              # 数据库
    'PyQt5.QtNetwork',          # 网络（项目未使用）
    'PyQt5.QtPositioning',      # 定位
    'PyQt5.QtLocation',         # 地图位置
    'PyQt5.QtQuick',            # QML 快速界面
    'PyQt5.QtQml',              # QML 引擎
    'PyQt5.QtSvg',              # SVG 渲染
    'PyQt5.QtPrintSupport',     # 打印支持
    'PyQt5.QtQuickWidgets',     # QML 组件
    'PyQt5.QtOpenGL',           # OpenGL（项目未使用 3D）
    'PyQt5.QtXml',              # XML（项目用 json）
    'PyQt5.QtDBus',             # D-Bus（Linux 进程通信）

    # === 科学计算/可视化库（未使用，可节省 ~30MB） ===
    'matplotlib',
    'scipy',
    'notebook',
    'IPython',
    'jupyter',
    'jupyter_client',
    'jupyter_core',
    'nbformat',
    'nbconvert',

    # === 图像处理库（未使用） ===
    'PIL',
    'Pillow',

    # === 数据处理库（未使用） ===
    'pandas',
    'sympy',
    'statsmodels',
    'sklearn',
    'tensorflow',
    'torch',
    'keras',

    # === OpenCV 不需要的子模块（可节省 ~10MB） ===
    'cv2.gapi',         # 图形 API
    'cv2.dnn',          # 深度学习（项目未用）
    'cv2.ml',           # 机器学习
    'cv2.flann',        # 近似最近邻
    'cv2.saliency',     # 显著性检测
    'cv2.xfeatures2d',  # 额外特征
    'cv2.ximgproc',     # 额外图像处理
    'cv2.xphoto',       # 额外照片处理
    'cv2.photo',        # 照片修复
    'cv2.stitching',    # 图像拼接
    'cv2.freetype',     # 字体渲染
    'cv2.face',         # 人脸识别
    'cv2.bioinspired',  # 生物启发
    'cv2.optflow',      # 光流
    'cv2.reg',          # 图像配准
    'cv2.sfm',          # 结构光
    'cv2.superres',     # 超分辨率
    'cv2.videostab',    # 视频稳定
    'cv2.viz',          # 3D 可视化
    'cv2.aruco',        # ArUco 标记
    'cv2.bgsegm',       # 背景分割
    'cv2.ccalib',       # 相机校准
    'cv2.datasets',     # 数据集
    'cv2.dpm',          # 可变形部件模型
    'cv2.fuzzy',        # 模糊逻辑
    'cv2.hdf',          # HDF5
    'cv2.hfs',          # 层次特征分割
    'cv2.img_hash',     # 图像哈希
    'cv2.line_descriptor', # 线段描述
    'cv2.mcc',          # 色彩校正
    'cv2.quality',      # 图像质量
    'cv2.rapid',        # 快速检测
    'cv2.rgbd',         # RGB-D
    'cv2.shape',        # 形状匹配
    'cv2.stereo',       # 立体匹配
    'cv2.structured_light', # 结构光
    'cv2.text',         # 文本检测
    'cv2.tracking',     # 目标跟踪
    'cv2.wechat_qrcode',# 微信二维码

    # === 其他不需要的 ===
    'tornado',          # Web 框架
    'jinja2',           # 模板引擎
    'tkinter',          # Tk GUI（项目用 PyQt5）
    'curses',           # 终端 UI
    'distutils',        # 包构建
    'setuptools',       # 包构建
    'pkg_resources',    # 包资源
    'unittest',         # 测试框架
    'pydoc',            # 文档生成
    'http.server',      # HTTP 服务器
    'smtplib',          # 邮件
    'telnetlib',        # Telnet
    'ftplib',           # FTP
    'dbm',              # 数据库
    'sqlite3',          # SQLite
    'xmlrpc',           # XML-RPC
    'webbrowser',       # 浏览器
    'antigravity',      # 彩蛋
    'turtle',           # 海龟绘图
    'idlelib',          # IDLE IDE
]
```

### 6.4 后处理清理（删除大体积无用 DLL）

在 `main.spec` 的后处理中，除了已有的清理，额外增加：

```python
# 额外删除的大体积 DLL
_EXTRA_DLL_TO_REMOVE = [
    'Qt5Network.dll',       # ~1.3MB
    'Qt5Designer.dll',      # ~4.4MB
    'Qt5DBus.dll',          # ~0.4MB
    'Qt5Svg.dll',           # ~0.3MB
    'Qt5Quick.dll',         # ~4MB
    'Qt5Qml.dll',           # ~3.5MB
    'Qt5QmlModels.dll',     # ~0.4MB
    'opengl32sw.dll',       # ~20MB - 最大单文件！
    'libGLESv2.dll',        # ~3.3MB
    'd3dcompiler_47.dll',   # ~4MB
]
```

### 6.5 优化效果汇总

| 措施 | 节省空间 | 说明 |
|------|---------|------|
| 排除不需要的 Qt 模块 | ~50MB | 浏览器、蓝牙、多媒体等 |
| 删除大体积 Qt DLL | ~30MB | opengl32sw.dll 等 |
| 排除 OpenCV 子模块 | ~10MB | dnn, ml 等未使用模块 |
| 排除科学计算库 | ~30MB | scipy, matplotlib 等 |
| 排除 Python 标准库 | ~5MB | tkinter, unittest 等 |
| 删除多余 Qt 翻译 | ~5MB | 只保留中英文 |
| 排除 data/errors/ 和 data/logs/ | ~1-10MB | 运行时生成的文件 |
| **总计优化** | **~60-80MB** | **从 ~200MB 降至 ~120-140MB** |

---

## 7. 执行步骤

### 步骤 1: 增强 [`main.spec`](../main.spec)

在现有 `main.spec` 基础上做 **5 处修改**：

**修改 1**: `hidden_imports` 列表补充：
```python
hidden_imports = [
    # 原有
    'vision.tools.preprocess',
    'vision.tools.feature_extract',
    'vision.tools.geometry',
    'vision.tools.measure',
    'vision.tools.recognize',
    'vision.tools.utility',
    # 新增
    'PyQt5.sip',
    'gxipy', 'gxipy.gxiapi', 'gxipy.gxidef',
    'gxipy.gxwrapper', 'gxipy.dxwrapper',
    'serial.tools.list_ports',
    'cv2.data',
]
```

**修改 2**: `excluded_imports` 列表补充（加入第 6.3 节中的所有排除项）

**修改 3**: `Analysis` 中设置 `pathex`：
```python
a = Analysis(
    ['main.py'],
    pathex=[os.path.dirname(os.path.abspath(__file__))],  # 新增
    ...
)
```

**修改 4**: `EXE` 中将 `upx=True` 改为 `upx=False`（工程机未安装 UPX）

**修改 5**: `data/` 目录遍历时排除 `errors/` 和 `logs/`：
```python
# --- data/ 目录（配置文件、用户数据等） ---
_data_dir = 'data'
_exclude_dirs = {'errors', 'logs'}  # 排除运行时生成的目录
if os.path.exists(_data_dir):
    for _root, _dirs, _files in os.walk(_data_dir):
        # 跳过排除目录
        _dirs[:] = [d for d in _dirs if d not in _exclude_dirs]
        for _f in _files:
            _src = os.path.join(_root, _f)
            _dst = os.path.relpath(_root, '.')
            datas.append((_src, _dst))
    print(f"[INFO] data/ 目录已加入打包数据（排除 errors/ 和 logs/）")
else:
    print(f"[WARN] 未找到 data/ 目录")
```

### 步骤 2: 清理旧的打包输出
```powershell
Remove-Item -Recurse -Force dist/VisionSystem -ErrorAction SilentlyContinue
Remove-Item -Force dist/VisionSystem.exe -ErrorAction SilentlyContinue
```

### 步骤 3: 执行 PyInstaller 打包
```powershell
pyinstaller --clean main.spec
```

### 步骤 4: 验证打包结果
1. 确认 `dist/VisionSystem/VisionSystem.exe` 存在且可执行
2. 确认 `dist/VisionSystem/_internal/` 中包含关键文件：
   - `GxIAPI.dll`, `DxImageProc.dll`, `MCDLL_NET.dll`
   - `data/` 目录（**不包含** `errors/` 和 `logs/`）
   - `model/` 目录
3. 确认 `dist/VisionSystem/MCDLL_NET.dll` 已复制到 exe 同级目录
4. 检查打包总大小（目标 < 150MB）
5. 在工程机上测试运行

---

## 8. 部署说明

1. 将整个 `dist/VisionSystem/` 文件夹复制到工程机
2. 确保工程机已安装大恒相机网卡驱动（GigE 相机需要）
3. 运行 `VisionSystem.exe`
4. 程序首次启动时会自动在 `data/` 目录下创建 `errors/` 和 `logs/` 子目录

---

## 9. 注意事项

1. **DLL 搜索路径**: [`runtime_hook.py`](../runtime_hook.py) 负责在程序启动时将 `_internal/` 添加到 `PATH`
2. **动态导入**: [`vision/pipeline.py`](../vision/pipeline.py) 使用 `importlib.import_module()` 动态加载工具类，已在 `hiddenimports` 中声明
3. **数据目录**: [`core/paths.py`](../core/paths.py) 的 `_get_data_dir()` 先查找 exe 同级 `data/`，再回退到 `_internal/data/`
4. **MCDLL_NET.dll**: [`nmc_sdk.py`](../core/nmc_sdk.py) 的 `load_dll()` 会搜索 `os.getcwd()`（exe 目录），所以需要复制一份到 exe 同级
5. **errors/ 和 logs/ 自动创建**: [`core/paths.py`](../core/paths.py) 的 `ensure_dirs()` 会在程序启动时自动创建这两个目录
