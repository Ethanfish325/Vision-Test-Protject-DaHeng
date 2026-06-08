# 亮度测量算子实施计划

## 概述

1. 删除 `recognize.py` 中的 `FootPadDetect`（脚垫识别）算子
2. 在 `measure.py` 中新增 `BrightnessMeasure`（亮度测量）算子
3. 更新所有注册表和方案文件

---

## 实施步骤

### 步骤 1：在 [`vision/tools/measure.py`](vision/tools/measure.py) 中新增 `BrightnessMeasure` 类

**位置**：在文件末尾（`ObjectCount` 类之后）新增。

**类定义**：

```python
class BrightnessMeasure(VisionTool):
    display_name = "亮度测量"
```

**参数** (`__init__`)：

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `pass_min` | 0 | 合格判定 - 平均灰度下限 |
| `pass_max` | 255 | 合格判定 - 平均灰度上限 |

**`process()` 方法逻辑**：

1. 获取输入图像（支持 `_input_source` 机制，自动支持 ROI 输入）
2. 如果输入是彩色图，先转为灰度图
3. 计算以下亮度指标：
   - `mean_gray`：平均灰度值 (`np.mean`)
   - `std_gray`：灰度标准差 (`np.std`)
   - `min_gray`：最小灰度值 (`np.min`)
   - `max_gray`：最大灰度值 (`np.max`)
4. 合格判定：`pass_min <= mean_gray <= pass_max`
5. 生成显示图像：
   - 在图像上标注 Mean / Std / Min / Max 数值
   - 生成 overlay 图像（同样标注）
   - 支持 ROI 输入源时的坐标平移（参考其他算子的 `_full_frame_image` 和 `_input_source` 处理模式）
6. 返回 `ToolResult`，`data` 包含：
   ```python
   {
       "mean_gray": float,
       "std_gray": float,
       "min_gray": int,
       "max_gray": int,
   }
   ```

**`get_param_widgets()` 方法**：

- 合格下限 (`pass_min`)：`QDoubleSpinBox`，范围 0~255
- 合格上限 (`pass_max`)：`QDoubleSpinBox`，范围 0~255

### 步骤 2：更新 [`vision/tools/__init__.py`](vision/tools/__init__.py)

- 在 `from .measure import (...)` 中添加 `BrightnessMeasure`
- 从 `from .recognize import (...)` 中移除 `FootPadDetect`

### 步骤 3：更新 [`vision/pipeline.py`](vision/pipeline.py)

需要修改 4 处：

1. **`CN_TO_EN` 映射表**（约第 43 行）：
   - 删除 `"脚垫识别": "FootPadDetect"`
   - 新增 `"亮度测量": "BrightnessMeasure"`

2. **`_TOOL_CATEGORIES` 分类表**（约第 74 行）：
   - 从 `"识别"` 类别中删除 `"FootPadDetect"`
   - 在 `"测量"` 类别中添加 `"BrightnessMeasure"`

3. **`_register_all_tools()` 函数**（约第 93 行）：
   - 从 `"recognize"` 模块列表中删除 `"FootPadDetect"`
   - 在 `"measure"` 模块列表中添加 `"BrightnessMeasure"`

### 步骤 4：从 [`vision/tools/recognize.py`](vision/tools/recognize.py) 中删除 `FootPadDetect` 类

- 删除 `FootPadDetect` 类的完整定义（约第 1108~1342 行）
- 注意保留文件中的其他类（`ColorRecognition`、`TemplateMatch`、`EdgeMatch`、`FastMatch`）

### 步骤 5：更新 [`data/schemes/默认方案.json`](data/schemes/默认方案.json)

当前结构（简化）：
```
MultiROI (定义脚垫1~4 和 标签1~3 区域)
FootPadDetect (脚垫1)
FootPadDetect (脚垫2)
FootPadDetect (脚垫3)
FootPadDetect (脚垫4)
```

修改为：
```
MultiROI (保持不变)
BrightnessMeasure (输入源: region:脚垫1)
BrightnessMeasure (输入源: region:脚垫2)
BrightnessMeasure (输入源: region:脚垫3)
BrightnessMeasure (输入源: region:脚垫4)
```

每个 `BrightnessMeasure` 步骤的 params：
```json
{
    "_input_source": "region:脚垫1",  // 分别对应脚垫1~4
    "pass_min": 0,
    "pass_max": 255
}
```

### 步骤 6：检查其他方案文件

检查 [`data/schemes/`](data/schemes/) 目录下所有 `.json` 文件，看是否有引用 `FootPadDetect` 或 `脚垫识别`，如有则更新。

---

## 影响范围

| 文件 | 修改类型 |
|------|----------|
| `vision/tools/measure.py` | 新增 `BrightnessMeasure` 类 |
| `vision/tools/recognize.py` | 删除 `FootPadDetect` 类 |
| `vision/tools/__init__.py` | 修改导入列表 |
| `vision/pipeline.py` | 修改注册表、分类、映射 |
| `data/schemes/默认方案.json` | 替换步骤 |

## 注意事项

- `BrightnessMeasure` 的 `process()` 方法需要遵循与其他算子一致的 ROI 输入源处理模式（使用 `_full_frame_image` 和 `_input_source` 坐标平移）
- 如果输入是彩色图，自动转为灰度图后再计算亮度指标
- 合格判定基于**平均灰度值**（`mean_gray`）
