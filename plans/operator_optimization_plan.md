# 算子全面优化计划

## 一、核心架构问题修复

### 1.1 `base_tool.py` - `display_name` 被覆盖问题

**问题描述**：`VisionTool.__init__` 第48行设置 `self.display_name: str = self.name`，其中 `self.name = type(self).__name__`。这导致所有子类在类级别定义的 `display_name`（如 `display_name = "多区域ROI"`）在 `__init__` 中被覆盖为类名（如 `"MultiROI"`）。

**影响范围**：所有32个算子，但主要影响 `_config_step` 中通过 `tool.display_name` 判断工具类型的逻辑。

**修复方案**：在 `base_tool.py` 的 `VisionTool.__init__` 中，仅在 `display_name` 未被子类设置时才使用类名作为默认值：

```python
def __init__(self, params: Optional[Dict[str, Any]] = None):
    self.name = type(self).__name__
    self.params: Dict[str, Any] = params if params is not None else {}
    # 如果子类已经定义了 display_name，保留它；否则使用类名
    if not hasattr(type(self), 'display_name') or 'display_name' not in type(self).__dict__:
        self.display_name = self.name
    else:
        self.display_name = type(self).display_name
```

### 1.2 `pipeline.py` - 重复类名注册问题

**问题描述**：`BlobDetection`、`LineDetection`、`RectangleDetection` 这三个类名在 `feature_extract.py` 和 `geometry.py` 中重复出现。`_register_all_tools()` 按模块顺序注册，后注册的会覆盖先注册的。这导致：
- `feature_extract.py` 中的 `BlobDetection`（display_name="斑点检测"）被 `geometry.py` 中的 `BlobDetection`（display_name="Blob检测"）覆盖
- 用户无法同时使用两个模块中的同名算子

**影响范围**：3个重复类名，6个算子实例

**修复方案**：将 `geometry.py` 中的重复类重命名，避免冲突：
- `geometry.LineDetection` → `geometry.HoughLineDetection`
- `geometry.RectangleDetection` → `geometry.ContourRectDetection`
- `geometry.BlobDetection` → `geometry.SimpleBlobDetect`

同时在 `_TOOL_CATEGORIES` 和 `_register_all_tools` 中更新类名。

---

## 二、各工具文件优化

### 2.1 `preprocess.py` 优化

| 算子 | 问题 | 优化方案 |
|------|------|----------|
| **Grayscale** | 无参数，但 `get_param_widgets` 返回空列表，对话框显示"该工具无需额外参数"，正常 | 无需修改 |
| **GaussianBlur** | `kernel_size` 默认5，但 `setdefault` 在 `__init__` 中设置，如果从JSON加载参数时不会触发默认值逻辑 | 在 `process()` 中也使用 `self.params.get("kernel_size", 5)` 而非依赖 `__init__` |
| **HistEqualize** | 无参数，正常 | 无需修改 |
| **Morphology** | 同上，`process()` 中已用 `.get()` 获取参数，安全 | 无需修改 |
| **MultiROI** | 无参数widgets，但通过 `MultiROIEditorDialog` 编辑 | 无需修改 |
| **MedianBlur** | 同上 GaussianBlur | 在 `process()` 中使用 `.get()` 确保安全 |
| **Resize** | `mode` 参数为 "ratio" 时，`width` 和 `height` 参数仍然显示在UI中，造成困惑 | 根据 mode 动态显示/隐藏参数 |
| **AdaptiveThreshold** | 同上，参数获取安全 | 无需修改 |

**主要优化**：
1. 所有 `process()` 方法统一使用 `self.params.get("key", default)` 而非依赖 `__init__` 中的 `setdefault`
2. `Resize` 的UI根据 mode 动态切换参数可见性

### 2.2 `feature_extract.py` 优化

| 算子 | 问题 | 优化方案 |
|------|------|----------|
| **CannyEdge** | `context.set_image('edges', edges)` 存储了边缘图，但 `context.set_data('edge_count', None)` 存储了None，无意义 | 移除无意义的 `set_data` 调用 |
| **Threshold** | 参数 `threshold_type` 使用OpenCV常量（如 `cv2.THRESH_BINARY`），JSON序列化后无法正确反序列化 | 改用字符串存储类型，在 `process()` 中映射回OpenCV常量 |
| **ContourAnalysis** | 内部硬编码 `cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)`，没有利用前面步骤的二值化结果 | 添加参数控制是否使用当前图像的已有二值化结果 |
| **BlobDetection** | 与 geometry.py 重复 | 见 1.2 节 |
| **ContourFilter** | 依赖 `context.get_data('contour_data')`，如果前面没有 ContourAnalysis 会报错"请先运行轮廓分析工具" | 添加更友好的错误提示，建议用户添加 ContourAnalysis 步骤 |
| **LineDetection** | 与 geometry.py 重复；内部硬编码 `cv2.Canny(gray, 50, 150)` | 见 1.2 节；添加Canny阈值参数 |
| **RectangleDetection** | 与 geometry.py 重复；内部硬编码 `cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)` | 见 1.2 节；添加二值化阈值参数 |

**主要优化**：
1. `Threshold` 的类型参数改为字符串存储，确保JSON序列化兼容
2. `ContourAnalysis` 添加 `use_existing_binary` 参数
3. `LineDetection` 添加Canny阈值参数
4. 移除无意义的 `set_data` 调用

### 2.3 `geometry.py` 优化

| 算子 | 问题 | 优化方案 |
|------|------|----------|
| **CircleDetection** | 无输入图像检查；`display = img.copy()` 在 circles 为 None 时仍创建副本 | 添加 `img is None` 检查；延迟创建 display |
| **LineDetection** | 使用标准Hough变换（非概率版），返回的是极坐标参数而非线段端点；硬编码Canny阈值 | 添加Canny阈值参数；考虑添加概率Hough模式选项 |
| **RectangleDetection** | 硬编码二值化阈值；`epsilon` 参数名与 feature_extract 版不一致（`epsilon_factor` vs `epsilon`） | 统一参数名；添加二值化阈值参数 |
| **BlobDetection** | 与 feature_extract 重复；`detector.detect(img)` 直接对彩色图检测，未做灰度转换 | 见 1.2 节；添加灰度转换 |

**主要优化**：
1. 所有算子添加 `img is None` 检查
2. 重命名重复类名（见 1.2 节）
3. 统一参数命名风格
4. `CircleDetection` 延迟创建 display

### 2.4 `measure.py` 优化

| 算子 | 问题 | 优化方案 |
|------|------|----------|
| **AreaMeasure** | 硬编码二值化阈值127；`pass_min`/`pass_max` 默认值与过滤范围重叠，逻辑混淆 | 添加二值化阈值参数；明确分离"过滤"和"判定"逻辑 |
| **DistanceMeasure** | 只有 `contour_center` 模式，缺少其他距离测量模式；硬编码二值化阈值 | 添加更多模式（点-点、点-线）；添加二值化阈值参数 |
| **PointMeasure** | 三种模式工作正常 | 添加 `img is None` 检查 |
| **LineMeasure** | `contour` 模式下 `length = max(w, h)` 不够精确；硬编码Canny阈值 | 使用对角线长度代替；添加Canny阈值参数 |
| **AngleMeasure** | `contour_angle` 模式下 `rect[2]` 返回的角度范围是 [-90, 0)，需要归一化 | 将角度归一化到 [0, 180) |
| **ObjectCount** | 硬编码二值化阈值127 | 添加二值化阈值参数 |

**主要优化**：
1. 所有测量算子添加二值化/Canny阈值参数
2. `AngleMeasure` 角度归一化
3. `LineMeasure.contour` 模式长度计算改进
4. `DistanceMeasure` 添加更多模式

### 2.5 `recognize.py` 优化

| 算子 | 问题 | 优化方案 |
|------|------|----------|
| **ColorRecognition** | `_update_range_from_color` 在 `get_param_widgets` 中通过信号触发，但如果在 `process()` 中直接设置参数不会自动更新范围 | 在 `process()` 开头也调用 `_update_range_from_color()` |
| **TemplateMatch** | `_multi_angle_match` 中 `mask=mask` 参数在 OpenCV 某些版本中不支持与 TM_CCOEFF_NORMED 同时使用 | 移除 mask 参数，改用旋转后直接匹配 |
| **EdgeMatch** | `_load_template` 在 `__init__` 中未调用，需要用户手动点击按钮加载；`process()` 中每次都会重新加载 | 优化加载逻辑，只在模板路径变化时重新加载 |
| **FastMatch** | 金字塔匹配只返回最佳匹配位置，不返回所有匹配结果；`best_scale` 计算可能不准确 | 返回所有金字塔层级的匹配结果；改进尺度恢复计算 |

**主要优化**：
1. `ColorRecognition.process()` 开头调用 `_update_range_from_color()`
2. `TemplateMatch._multi_angle_match` 移除不兼容的 mask 参数
3. `EdgeMatch` 优化模板加载缓存逻辑
4. `FastMatch` 返回多结果，改进尺度计算

### 2.6 `utility.py` 优化

| 算子 | 问题 | 优化方案 |
|------|------|----------|
| **CoordinateTransform** | `input_key` 需要用户手动输入工具类名，但用户不知道类名是什么 | 添加下拉选择框，列出所有已执行步骤的工具类名 |
| **Calculator** | `_safe_eval` 的字符白名单缺少 `%`（取模运算符已包含），但缺少 `**`（幂运算） | 添加 `**` 支持；改进表达式安全性检查 |
| **LogicJudge** | `_get_common_measurement_keys` 方法未在UI中使用，条件配置需要用户手动输入"工具名.数据键" | 在下拉框中提供可用的数据键选择 |

**主要优化**：
1. `CoordinateTransform` 的 `input_key` 改为下拉选择
2. `Calculator` 添加 `**` 幂运算支持
3. `LogicJudge` 条件配置添加数据键下拉提示

---

## 三、执行顺序

1. **基础架构修复**：`base_tool.py` display_name 问题 + `pipeline.py` 重复类名
2. **preprocess.py**：Resize 动态UI
3. **feature_extract.py**：Threshold类型序列化 + ContourAnalysis参数 + LineDetection参数
4. **geometry.py**：类名重命名 + 输入检查 + 参数统一
5. **measure.py**：阈值参数 + 角度归一化 + 模式扩展
6. **recognize.py**：颜色范围更新 + 模板匹配mask修复 + 缓存优化
7. **utility.py**：下拉选择 + 表达式增强
