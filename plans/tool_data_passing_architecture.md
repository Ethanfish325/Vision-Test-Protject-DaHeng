# 视觉工具间数据传递架构设计方案

## 1. 问题分析

### 当前架构问题

当前每个视觉工具是**完全独立**的，`process(cv_image)` 只接收一张图像，返回一个 `ToolResult`。工具之间没有数据传递通道。

**用户场景举例**：识别机器上的三个标签是否贴好
- 需要画 3 个 ROI 框（标签1、标签2、标签3）
- 将 3 个 ROI 子图像分别传入后续的检测工具
- 每个标签独立检测（如颜色识别、模板匹配）
- 当前架构无法实现

### 目标架构（类似海康威视方案）

```
每个工具可以选输入源
ROI工具可以输出多个命名区域
```

---

## 2. 核心架构设计

### 2.1 PipelineContext - 流水线上下文（数据总线）

新增 `PipelineContext` 类，作为整个流水线执行过程中的数据总线，携带所有共享数据。

```python
@dataclass
class PipelineContext:
    """流水线执行上下文 - 工具间的数据总线"""
    # 原始图像（始终可用）
    original_image: np.ndarray

    # 当前处理的图像（上一个工具的输出）
    current_image: np.ndarray

    # 命名区域字典 {区域名称: 子图像}
    regions: Dict[str, np.ndarray] = field(default_factory=dict)

    # 区域元数据 {区域名称: {x, y, width, height, ...}}
    regions_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 已执行工具的结果列表
    results: List[ToolResult] = field(default_factory=list)
```

### 2.2 ToolResult 增强

```python
@dataclass
class ToolResult:
    """单个工具的处理结果"""
    tool_name: str
    tool_type: str
    passed: bool = True
    message: str = ""
    annotated_image: Optional[np.ndarray] = None
    measurements: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    # 新增：工具输出的命名区域 {区域名称: 子图像}
    output_regions: Dict[str, np.ndarray] = field(default_factory=dict)

    # 新增：输出区域元数据
    output_regions_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
```

### 2.3 VisionTool.process() 签名变更

```python
class VisionTool(ABC):
    # 新增类属性：输入源类型
    INPUT_SOURCE_TYPES = ["原始图像"]  # 子类可扩展

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        self.params = params or {}
        # 新增：输入源参数（默认使用原始图像）
        if "input_source" not in self.params:
            self.params["input_source"] = "原始图像"
        self._name = ""

    @abstractmethod
    def process(self, context: PipelineContext) -> ToolResult:
        """
        处理图像（从上下文中获取输入）

        参数:
            context: 流水线上下文，包含原始图像、命名区域、当前图像等

        返回:
            ToolResult 处理结果
        """
        pass

    def _get_input_image(self, context: PipelineContext) -> np.ndarray:
        """
        根据 input_source 参数从上下文中获取输入图像
        """
        source = self.params.get("input_source", "原始图像")
        if source == "原始图像":
            return context.original_image.copy()
        elif source == "上一个工具输出":
            return context.current_image.copy()
        elif source.startswith("区域:"):
            region_name = source[3:]  # 去掉"区域:"前缀
            if region_name in context.regions:
                return context.regions[region_name].copy()
            raise ValueError(f"未找到命名区域: {region_name}")
        else:
            return context.original_image.copy()

    def get_input_source_widgets(self, parent, context_info: Dict[str, List[str]]) -> List[tuple]:
        """
        获取输入源选择控件

        参数:
            parent: 父控件
            context_info: 上下文信息，格式:
                {
                    "regions": ["标签1", "标签2", ...],  # 当前可用的命名区域列表
                }

        返回:
            [(label, widget, value_label)] 格式的控件列表
        """
        sources = ["原始图像", "上一个工具输出"]
        # 添加可用的命名区域
        for region_name in context_info.get("regions", []):
            sources.append(f"区域:{region_name}")

        label = QLabel("输入源:", parent)
        combo = QComboBox(parent)
        combo.addItems(sources)
        current = self.params.get("input_source", "原始图像")
        if current in sources:
            combo.setCurrentText(current)
        combo.currentTextChanged.connect(
            lambda v: self.params.update({"input_source": v})
        )
        return [(label, combo, QLabel(""))]
```

---

## 3. 工具改造方案

### 3.1 MultiROI 工具（新增，替代原有 ROI 工具）

```python
class MultiROI(VisionTool):
    """多区域ROI选取 - 支持定义多个命名区域"""
    DISPLAY_NAME = "多区域ROI"
    CATEGORY = "预处理"
    INPUT_SOURCE_TYPES = ["原始图像"]

    def __init__(self, params=None):
        default = {
            "input_source": "原始图像",
            "regions": [
                # 每个区域: {"name": "标签1", "x": 0, "y": 0, "width": 200, "height": 200, "enabled": True}
            ]
        }
        if params:
            # 合并 regions 列表
            if "regions" in params:
                default["regions"] = params["regions"]
            # 合并其他参数
            for k, v in params.items():
                if k != "regions":
                    default[k] = v
        super().__init__(default)

    def process(self, context: PipelineContext) -> ToolResult:
        start = cv2.getTickCount()
        img = self._get_input_image(context)
        h, w = img.shape[:2]
        output_regions = {}
        output_metadata = {}
        messages = []

        for region in self.params.get("regions", []):
            if not region.get("enabled", True):
                continue
            name = region.get("name", "未命名")
            x = max(0, region.get("x", 0))
            y = max(0, region.get("y", 0))
            rw = min(region.get("width", 100), w - x)
            rh = min(region.get("height", 100), h - y)
            if rw > 0 and rh > 0:
                sub_img = img[y:y+rh, x:x+rw]
                output_regions[name] = sub_img
                output_metadata[name] = {"x": x, "y": y, "width": rw, "height": rh}
                messages.append(f"{name}: ({x},{y}) {rw}x{rh}")

        # 在图像上绘制所有ROI框（标注用）
        annotated = img.copy()
        for region in self.params.get("regions", []):
            if not region.get("enabled", True):
                continue
            x = region.get("x", 0)
            y = region.get("y", 0)
            rw = region.get("width", 100)
            rh = region.get("height", 100)
            name = region.get("name", "")
            cv2.rectangle(annotated, (x, y), (x + rw, y + rh), (0, 255, 0), 2)
            cv2.putText(annotated, name, (x, y - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        elapsed = (cv2.getTickCount() - start) / cv2.getTickFrequency() * 1000
        return ToolResult(
            tool_name=self.name, tool_type=self.DISPLAY_NAME,
            message="; ".join(messages),
            annotated_image=annotated,
            output_regions=output_regions,
            output_regions_metadata=output_metadata,
            elapsed_ms=round(elapsed, 1)
        )
```

### 3.2 所有现有工具的改造

每个工具需要：
1. 在 `__init__` 中确保 `input_source` 参数存在
2. 将 `process(self, cv_image)` 改为 `process(self, context: PipelineContext)`
3. 使用 `self._get_input_image(context)` 获取输入图像
4. 在 `get_param_widgets` 中增加输入源选择

**以 CannyEdge 为例的改造模式**：

```python
class CannyEdge(VisionTool):
    DISPLAY_NAME = "Canny边缘检测"
    CATEGORY = "特征提取"

    def __init__(self, params=None):
        default = {
            "input_source": "原始图像",  # 新增
            "low_threshold": 50,
            "high_threshold": 150,
            "aperture_size": 3
        }
        if params:
            default.update(params)
        super().__init__(default)

    def process(self, context: PipelineContext) -> ToolResult:
        start = cv2.getTickCount()
        img = self._get_input_image(context)  # 从上下文获取输入
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray,
                         self.params["low_threshold"],
                         self.params["high_threshold"],
                         apertureSize=self.params["aperture_size"])
        elapsed = (cv2.getTickCount() - start) / cv2.getTickFrequency() * 1000
        return ToolResult(
            tool_name=self.name, tool_type=self.DISPLAY_NAME,
            message=f"边缘检测完成",
            annotated_image=cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR),
            elapsed_ms=round(elapsed, 1)
        )

    def get_param_widgets(self, parent):
        # ... 原有参数控件 ...
        pass

    def get_input_source_widgets(self, parent, context_info):
        # 使用基类的默认实现
        return super().get_input_source_widgets(parent, context_info)
```

---

## 4. Pipeline 执行流程改造

### 4.1 Pipeline.execute() 新逻辑

```python
def execute(self, cv_image: np.ndarray) -> Tuple[bool, List[ToolResult], np.ndarray]:
    # 创建上下文
    context = PipelineContext(
        original_image=cv_image.copy(),
        current_image=cv_image.copy()
    )

    all_passed = True

    for step in self.steps:
        if not step.enabled:
            result = ToolResult(
                tool_name=step.tool.name,
                tool_type=step.tool.DISPLAY_NAME,
                passed=True, message="已跳过",
                annotated_image=context.current_image
            )
            context.results.append(result)
            continue

        try:
            # 执行工具（传入上下文）
            result = step.tool.process(context)

            # 收集工具输出的命名区域
            if result.output_regions:
                context.regions.update(result.output_regions)
            if result.output_regions_metadata:
                context.regions_metadata.update(result.output_regions_metadata)

            # 更新当前图像
            if result.annotated_image is not None:
                context.current_image = result.annotated_image

            # 判定规则
            if step.judge_rule:
                result.passed = self._apply_judge_rule(result, step.judge_rule)

            if not result.passed:
                all_passed = False

            context.results.append(result)

        except Exception as e:
            all_passed = False
            result = ToolResult(
                tool_name=step.tool.name,
                tool_type=step.tool.DISPLAY_NAME,
                passed=False, message=f"执行异常: {str(e)}",
                annotated_image=context.current_image
            )
            context.results.append(result)

    # 整体判定逻辑
    if self.judge_logic == "AND":
        final_passed = all_passed
    else:
        final_passed = any(r.passed for r in context.results
                          if r.message != "已跳过")

    return final_passed, context.results, context.current_image
```

### 4.2 序列化兼容

```python
class PipelineStep:
    def to_dict(self) -> Dict:
        return {
            "tool_type": self.tool.DISPLAY_NAME,
            "display_name": self.tool.DISPLAY_NAME,
            "params": self.tool.params.copy(),  # 包含 input_source 和 regions
            "enabled": self.enabled,
            "judge_rule": copy.deepcopy(self.judge_rule)
        }
    # from_dict 无需修改，params 已包含所有新参数
```

---

## 5. UI 改造方案

### 5.1 ParamConfigDialog 增加输入源选择

```python
class ParamConfigDialog(QDialog):
    def __init__(self, tool: VisionTool, preview_image: Optional[np.ndarray] = None,
                 context_info: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.preview_image = preview_image
        self.context_info = context_info or {"regions": []}
        # ...

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 1. 输入源选择区域（新增）
        if hasattr(self.tool, 'get_input_source_widgets'):
            source_group = QGroupBox("输入源选择")
            source_layout = QVBoxLayout(source_group)
            source_widgets = self.tool.get_input_source_widgets(self, self.context_info)
            for label, widget, value_label in source_widgets:
                row = QHBoxLayout()
                row.addWidget(label)
                row.addWidget(widget, 1)
                source_layout.addLayout(row)
            layout.addWidget(source_group)

        # 2. 参数设置区域（原有）
        param_group = QGroupBox("参数设置")
        # ... 原有代码 ...

        # 3. 预览区域（原有）
        # ...
```

### 5.2 MultiROIEditorDialog - 多区域ROI编辑器（新增）

替代原有的 `ROIEditorDialog`，支持：
- 添加/删除多个命名区域
- 每个区域可独立命名
- 每个区域可独立绘制/调整
- 区域列表显示

```python
class MultiROIEditorDialog(QDialog):
    """
    多区域ROI编辑器：在图像上绘制多个命名ROI区域
    类似海康威视官方软件的多区域绘制体验
    """

    def __init__(self, tool: VisionTool, image: np.ndarray, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.original_image = image.copy()
        self.regions = []  # 每个元素: {"name": str, "x": int, "y": int, "w": int, "h": int, "enabled": bool}
        self._load_regions()
        self._selected_idx = -1
        self._setup_ui()

    def _load_regions(self):
        """从工具参数加载区域列表"""
        for r in self.tool.params.get("regions", []):
            self.regions.append({
                "name": r.get("name", "未命名"),
                "x": r.get("x", 0),
                "y": r.get("y", 0),
                "w": r.get("width", 200),
                "h": r.get("height", 200),
                "enabled": r.get("enabled", True)
            })
        if not self.regions:
            # 默认添加一个区域
            h, w = self.original_image.shape[:2]
            self.regions.append({
                "name": "区域1", "x": w//4, "y": h//4,
                "w": w//2, "h": h//2, "enabled": True
            })

    def _setup_ui(self):
        # 左侧：图像显示区（带MultiROIEditorLabel）
        # 右侧：区域列表（QListWidget + 添加/删除按钮）
        # 底部：区域属性编辑（名称、坐标、启用开关）
        # 底部按钮：确定/取消
        pass
```

### 5.3 PipelineEditor 改造

```python
class PipelineEditor(QWidget):
    def _config_step(self, index):
        """配置步骤参数"""
        if 0 <= index < len(self._pipeline.steps):
            step = self._pipeline.steps[index]
            tool = step.tool

            # 收集上下文信息（当前可用的命名区域）
            context_info = self._get_context_info(index)

            # 特殊处理多区域ROI工具
            if tool.DISPLAY_NAME == "多区域ROI":
                preview_img = self._get_preview_image()
                if preview_img is not None:
                    dialog = MultiROIEditorDialog(tool, preview_img, self)
                    if dialog.exec_() == QDialog.Accepted:
                        self._rebuild_ui()
                        self.pipeline_changed.emit()
                else:
                    dialog = ParamConfigDialog(tool, None, context_info, self)
                    if dialog.exec_() == QDialog.Accepted:
                        self._rebuild_ui()
                        self.pipeline_changed.emit()
            else:
                preview_img = self._get_preview_image()
                dialog = ParamConfigDialog(tool, preview_img, context_info, self)
                if dialog.exec_() == QDialog.Accepted:
                    self._rebuild_ui()
                    self.pipeline_changed.emit()

    def _get_context_info(self, current_step_index: int) -> Dict:
        """获取当前步骤之前的上下文信息（可用命名区域列表）"""
        regions = []
        for i in range(current_step_index):
            step = self._pipeline.steps[i]
            if step.tool.DISPLAY_NAME == "多区域ROI":
                for r in step.tool.params.get("regions", []):
                    if r.get("enabled", True):
                        regions.append(r.get("name", ""))
        return {"regions": regions}
```

### 5.4 ToolItemWidget 显示输入源

```python
class ToolItemWidget(QFrame):
    def _setup_ui(self):
        # ... 原有代码 ...

        # 显示输入源信息
        input_source = self.step.tool.params.get("input_source", "原始图像")
        if input_source != "原始图像":
            self.source_label = QLabel(f"← {input_source}")
            self.source_label.setStyleSheet("color: #888; font-size: 10px;")
            layout.addWidget(self.source_label)
```

---

## 6. 用户场景示例

### 场景：检测三个标签是否贴好

```
流水线步骤：
1. [多区域ROI]  ← 原始图像
   - 区域1: "标签1" (x=10, y=20, w=100, h=80)
   - 区域2: "标签2" (x=150, y=20, w=100, h=80)
   - 区域3: "标签3" (x=300, y=20, w=100, h=80)
   → 输出命名区域: {"标签1": sub_img1, "标签2": sub_img2, "标签3": sub_img3}

2. [灰度化]  ← 区域:标签1
   → 处理标签1区域

3. [模板匹配]  ← 区域:标签1
   → 检测标签1是否贴好

4. [灰度化]  ← 区域:标签2
   → 处理标签2区域

5. [模板匹配]  ← 区域:标签2
   → 检测标签2是否贴好

6. [灰度化]  ← 区域:标签3
   → 处理标签3区域

7. [模板匹配]  ← 区域:标签3
   → 检测标签3是否贴好
```

---

## 7. 实施步骤

### 阶段一：MVP 核心改造（当前任务）

| 步骤 | 文件 | 改动内容 |
|------|------|----------|
| 1 | `vision/tools/base_tool.py` | 新增 `PipelineContext` 类；修改 `ToolResult` 增加 `output_regions`；修改 `VisionTool.process()` 签名；新增 `_get_input_image()` 和 `get_input_source_widgets()` |
| 2 | `vision/pipeline.py` | 修改 `Pipeline.execute()` 使用 `PipelineContext`；`PipelineStep.from_dict` 兼容旧版 ROI→MultiROI |
| 3 | `vision/vision_engine.py` | 适配新的 `execute()` 签名（接口不变，无需修改） |
| 4 | `vision/tools/preprocess.py` | 改造5个工具：Grayscale, GaussianBlur, HistEqualize, Morphology, **ROI→MultiROI** |
| 5 | `vision/tools/feature_extract.py` | 改造4个工具：CannyEdge, Threshold, ContourAnalysis, BlobDetection |
| 6 | `vision/tools/measure.py` | 改造4个工具：AreaMeasure, DistanceMeasure, CircleDetection, ObjectCount |
| 7 | `vision/tools/recognize.py` | 改造2个工具：ColorRecognition, TemplateMatch |
| 8 | `vision/tools/__init__.py` | 更新工具注册表（ROI→MultiROI） |
| 9 | `ui/widgets/param_config_dialog.py` | `ParamConfigDialog` 增加输入源选择区域；新增 `MultiROIEditorDialog` |
| 10 | `ui/widgets/pipeline_editor.py` | `_config_step()` 适配新对话框；新增 `_get_context_info()`；`ToolItemWidget` 显示输入源 |
| 11 | 测试 | 运行测试脚本验证所有工具和UI |

### 阶段二：功能扩展（后续迭代）

根据您提供的完整功能需求，后续可扩展：

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **OCR字符识别** | 基于 Tesseract/PaddleOCR 的字符识别工具 | 高 |
| **二维码/条形码读取** | 基于 pyzbar/OpenCV 的条码识别工具 | 高 |
| **Blob分析增强** | 更完善的连通域分析，输出各Blob的几何特征 | 中 |
| **深度学习推理** | 加载 YOLO 等模型，支持目标检测、缺陷分类 | 中 |
| **定位与引导** | 工件位置/角度识别，输出坐标供机械臂 | 低 |
| **标定工具** | 相机标定、畸变校正、像素当量标定 | 低 |
| **更多预处理算子** | 傅里叶变换、直方图匹配、色彩空间转换等 | 低 |

---

## 8. 向后兼容性

- 旧方案 JSON 文件中的 `ROI选取` 工具会在加载时自动转换为 `多区域ROI`（通过 `PipelineStep.from_dict` 中的映射）
- 旧 `params` 中的 `x/y/width/height/enabled` 会被转换为 `regions` 列表的第一个元素
- 新增的 `input_source` 参数默认值为 `"原始图像"`，旧方案加载时自动获得此默认值

```python
# 在 PipelineStep.from_dict 中添加兼容转换
@classmethod
def from_dict(cls, data: Dict):
    tool_type = data.get("display_name") or data.get("tool_type", "")
    params = data.get("params", {}).copy()

    # 兼容旧版 ROI选取 → 新版 多区域ROI
    if tool_type == "ROI选取":
        tool_type = "多区域ROI"
        if "regions" not in params:
            params["regions"] = [{
                "name": "区域1",
                "x": params.pop("x", 0),
                "y": params.pop("y", 0),
                "width": params.pop("width", 640),
                "height": params.pop("height", 480),
                "enabled": params.pop("enabled", True)
            }]

    # 确保 input_source 存在
    if "input_source" not in params:
        params["input_source"] = "原始图像"

    enabled = data.get("enabled", True)
    judge_rule = data.get("judge_rule")
    tool = create_tool(tool_type, params)
    return cls(tool, enabled=enabled, judge_rule=judge_rule)
```
