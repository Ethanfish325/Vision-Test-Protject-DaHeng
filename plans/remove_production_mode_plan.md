# 移除"生产模式"UI 元素计划

## 目标

将 `main_window.py` 中的"生产模式"（Worker Mode / index=0）相关 UI 元素注释掉，但保留核心检测功能代码（`_do_detect`、`_on_detect_finished`、`DetectWorker`、`_import_worker_scheme`、`_toggle_auto_test` 等），以便后期可以重新添加回来。

## 方案说明

**方案B**：注释 UI 元素但保留核心检测功能。具体来说：
- 注释模式切换工具栏中的"生产模式"按钮
- 注释 `_build_worker_page` 的调用（不再构建生产模式页面）
- 注释所有"生产模式"文字标签
- **保留** `_do_detect`、`_on_detect_finished`、`DetectWorker`、`WorkflowTestWorker` 等核心检测功能代码
- **保留** `_build_worker_page` 方法本身（只是不调用它）
- **保留** `_import_worker_scheme`、`_refresh_worker_scheme_list` 等方法

## 详细修改清单

### 文件：`ui/main_window.py`

所有修改均使用 `# === COMMENTED OUT: 生产模式 ... ===` 包裹注释块，方便后续搜索和恢复。

---

### 修改 1：`__init__` 中的生产模式标记注释（第 196-200 行）

```python
# 原代码
self._pending_engineer_test = False  # 设计模式测试标记：拍照后自动执行流水线
self._pending_detect = False    # 生产模式标记：拍照后自动执行检测

# 生产模式最近一次检测的标注结果，用于实时预览时保持显示检测结果
self._last_annotated = None

# 修改为
self._pending_engineer_test = False  # 设计模式测试标记：拍照后自动执行流水线
# === COMMENTED OUT: 生产模式标记 ===
# self._pending_detect = False    # 生产模式标记：拍照后自动执行检测
# === END ===

# === COMMENTED OUT: 生产模式最近一次检测的标注结果 ===
# self._last_annotated = None
# === END ===
```

### 修改 2：`_setup_ui` 中移除 `_build_worker_page` 调用（第 250 行）

```python
# 原代码
self._build_worker_page()
self._build_automation_page()
self._build_engineer_page()
self.stack.setCurrentIndex(0)

# 修改为
# === COMMENTED OUT: 生产模式页面 ===
# self._build_worker_page()
# === END ===
self._build_automation_page()
self._build_engineer_page()
self.stack.setCurrentIndex(0)  # 改为指向自动化模式页面（索引0现在是自动化模式）
```

注意：由于移除了 worker page，`stack` 的索引会变化：
- 原：0=生产模式, 1=自动化模式, 2=设计模式
- 新：0=自动化模式, 1=设计模式

因此需要调整 `_switch_mode` 中的索引映射，以及 `_set_user_role` 中的索引判断。

### 修改 3：`_setup_mode_toolbar` 中注释"生产模式"按钮（第 274-289 行）

```python
# 原代码
self.btn_worker_mode = QPushButton("🔧 生产模式")
self.btn_worker_mode.setCheckable(True)
self.btn_worker_mode.setChecked(True)
self.btn_worker_mode.setStyleSheet("""...""")

# 修改为
# === COMMENTED OUT: 生产模式按钮 ===
# self.btn_worker_mode = QPushButton("🔧 生产模式")
# self.btn_worker_mode.setCheckable(True)
# self.btn_worker_mode.setChecked(True)
# self.btn_worker_mode.setStyleSheet("""...""")
# === END ===
```

同时注释掉 `layout.addWidget(self.btn_worker_mode)`（第 325 行）和 `self.btn_worker_mode.clicked.connect(...)`（第 335 行）。

### 修改 4：`_switch_mode` 中移除生产模式相关逻辑（第 341-356 行）

```python
# 原代码
def _switch_mode(self, index: int):
    # 如果尝试切换到设计模式但当前用户不是工程师/管理员，阻止切换
    if index == 2 and self._current_user_role not in ("engineer", "admin"):
        QMessageBox.warning(self, "权限不足", "请先通过「用户」菜单登录工程师账号")
        self.btn_worker_mode.setChecked(True)
        self.btn_automation_mode.setChecked(False)
        self.btn_engineer_mode.setChecked(False)
        return

    self.stack.setCurrentIndex(index)
    self.btn_worker_mode.setChecked(index == 0)
    self.btn_automation_mode.setChecked(index == 1)
    self.btn_engineer_mode.setChecked(index == 2)

    mode_names = {0: "生产模式", 1: "自动化模式", 2: "设计模式"}
    self.status_label.setText(mode_names.get(index, "未知模式"))

# 修改为
def _switch_mode(self, index: int):
    # 如果尝试切换到设计模式但当前用户不是工程师/管理员，阻止切换
    if index == 1 and self._current_user_role not in ("engineer", "admin"):  # 索引变化：1=设计模式
        QMessageBox.warning(self, "权限不足", "请先通过「用户」菜单登录工程师账号")
        # === COMMENTED OUT: 生产模式按钮 ===
        # self.btn_worker_mode.setChecked(True)
        # === END ===
        self.btn_automation_mode.setChecked(True)
        self.btn_engineer_mode.setChecked(False)
        return

    self.stack.setCurrentIndex(index)
    # === COMMENTED OUT: 生产模式按钮 ===
    # self.btn_worker_mode.setChecked(index == 0)
    # === END ===
    self.btn_automation_mode.setChecked(index == 0)  # 索引变化
    self.btn_engineer_mode.setChecked(index == 1)     # 索引变化

    # === COMMENTED OUT: 生产模式 ===
    # mode_names = {0: "生产模式", 1: "自动化模式", 2: "设计模式"}
    # === END ===
    mode_names = {0: "自动化模式", 1: "设计模式"}
    self.status_label.setText(mode_names.get(index, "未知模式"))
```

### 修改 5：`_set_user_role` 中注释生产模式相关逻辑（第 458-460 行）

```python
# 原代码
# 如果当前在设计模式但角色不是工程师，自动切回生产模式
if not is_engineer and self.stack.currentIndex() == 1:
    self._switch_mode(0)

# 修改为
# === COMMENTED OUT: 生产模式 ===
# 如果当前在设计模式但角色不是工程师，自动切回自动化模式
if not is_engineer and self.stack.currentIndex() == 1:
    self._switch_mode(0)
# === END ===
```

### 修改 6：`_logout` 中注释生产模式文本（第 467 行）

```python
# 原代码
def _logout(self):
    """退出登录，回到操作员模式"""
    self._set_user_role("operator", "操作员")
    self.status_label.setText("生产模式")

# 修改为
def _logout(self):
    """退出登录，回到操作员模式"""
    self._set_user_role("operator", "操作员")
    # === COMMENTED OUT: 生产模式 ===
    # self.status_label.setText("生产模式")
    # === END ===
    self.status_label.setText("自动化模式")
```

### 修改 7：`_build_worker_page` 方法整体注释（第 469-670 行）

将整个 `_build_worker_page` 方法体注释掉，但保留方法定义（方便后续恢复）。

```python
# 原代码
def _build_worker_page(self):
    page = QWidget()
    ...（整个方法体）
    self.stack.addWidget(page)

# 修改为
def _build_worker_page(self):
    """生产模式页面 - 已注释，保留以方便后续恢复"""
    pass
    # === COMMENTED OUT: 生产模式页面 ===
    # page = QWidget()
    # ...（整个方法体）
    # self.stack.addWidget(page)
    # === END ===
```

### 修改 8：`_import_worker_scheme` 中的"生产模式"日志文本（第 698, 714 行）

```python
# 第698行
# log_error(f"生产模式导入方案失败: {e}")
# === COMMENTED OUT ===
# log_error(f"生产模式导入方案失败: {e}")
# === END ===

# 第714行
# log_info(f"生产模式导入方案: {name}")
# === COMMENTED OUT ===
# log_info(f"生产模式导入方案: {name}")
# === END ===
```

### 修改 9：`_on_capture_completed` 中的"生产模式"注释（第 2496-2499 行）

```python
# 原代码
# 生产模式：拍照后自动执行检测
if self._pending_detect:
    self._pending_detect = False
    self._do_detect()

# 修改为
# === COMMENTED OUT: 生产模式自动检测 ===
# # 生产模式：拍照后自动执行检测
# if self._pending_detect:
#     self._pending_detect = False
#     self._do_detect()
# === END ===
```

### 修改 10：`_overlay_roi_on_image` 中的"生产模式"注释（第 2504 行）

```python
# 原代码
"""
用于生产模式实时预览时，让操作员看到检测区域的位置。
如果未设置流水线或没有 MultiROI 工具，则返回原始图像的副本。
"""

# 修改为
"""
用于实时预览时，让操作员看到检测区域的位置。
如果未设置流水线或没有 MultiROI 工具，则返回原始图像的副本。
"""
```

## 保留的核心功能代码（不做任何修改）

以下代码必须**完整保留**，因为它们不依赖于"生产模式"UI：

1. **`DetectWorker` 类**（第 136-148 行）- 后台检测线程
2. **`WorkflowTestWorker` 类**（第 151-169 行）- 后台工作流测试线程
3. **`_do_detect` 方法**（第 2766-2804 行）- 核心检测逻辑
4. **`_on_detect_finished` 方法**（第 2806-2871 行）- 检测完成回调
5. **`_refresh_worker_scheme_list` 方法**（第 672-681 行）- 方案列表刷新
6. **`_import_worker_scheme` 方法**（第 683-716 行）- 方案导入（仅注释日志文本）
7. **`_toggle_auto_test` / `_start_auto_test` / `_stop_auto_test`**（第 3088-3152 行）- 自动测试
8. **`_on_workflow_capture_requested` / `_on_workflow_test_requested` / `_on_workflow_test_finished`**（第 3167-3205 行）- 工作流回调
9. **`_update_auto_test_btn_state`**（第 3076-3086 行）- 自动测试按钮状态
10. **`_on_frame_received` / `_on_capture_completed`**（第 2454-2499 行）- 相机回调（仅注释生产模式相关部分）
11. **`_overlay_roi_on_image`**（第 2501-2539 行）- ROI 叠加（仅修改注释文字）
12. **`_show_worker_image`** 等相关图像显示方法

## 恢复指南

如果需要重新添加生产模式，只需：
1. 搜索 `# === COMMENTED OUT: 生产模式` 找到所有注释块
2. 删除注释标记 `# === COMMENTED OUT ... ===` 和 `# === END ===`，恢复被注释的代码
3. 恢复 `_setup_ui` 中的 `self._build_worker_page()` 调用
4. 恢复 `_switch_mode` 中的索引映射
5. 恢复 `_build_worker_page` 的方法体
