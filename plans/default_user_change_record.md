# 默认用户修改为工程师 — 修改记录

> 修改日期：2026-06-26
> 修改目的：将系统默认用户从"操作员(operator)"改为"工程师(engineer)"

---

## 修改文件

[`ui/main_window.py`](../ui/main_window.py)

---

## 修改内容

### 1. 默认角色和名称 — ✅ 已修改

**位置：** [`__init__`](../ui/main_window.py:132) 第 132-134 行

**修改前：**
```python
self._current_user_role = "operator"   # 当前用户角色: operator / engineer / admin
self._current_user_name = "操作员"      # 当前用户显示名称
```

**修改后：**
```python
self._current_user_role = "engineer"   # 当前用户角色: operator / engineer / admin
self._current_user_name = "工程师"      # 当前用户显示名称
```

> 旧代码用 `'''` 注释保留在第 135-139 行，方便后续恢复。

---

### 2. 设计模式按钮默认启用 — ✅ 已修改

**位置：** [`_setup_mode_toolbar`](../ui/main_window.py:209) 第 209 行

**修改前：**
```python
self.btn_engineer_mode.setEnabled(False)  # 默认操作员模式，禁用设计模式
```

**修改后：**
```python
self.btn_engineer_mode.setEnabled(True)  # 默认操作员模式，禁用设计模式
```

> 注释文字未更新（仍写"默认操作员模式"），建议后续改为 `# 默认工程师模式，启用设计模式`。

---

### 3. 用户菜单默认显示文本 — ✅ 已修改

**位置：** [`_setup_menu_bar`](../ui/main_window.py:866) 第 866 行

**修改前：**
```python
self.act_current_user = QAction("当前用户：操作员", self)
```

**修改后：**
```python
self.act_current_user = QAction("当前用户：工程师", self)
```

---

### 4. 退出登录按钮默认状态 — ✅ 已修改

**位置：** [`_setup_menu_bar`](../ui/main_window.py:871) 第 871 行

**修改前：**
```python
self.act_logout.setEnabled(False)
```

**修改后：**
```python
self.act_logout.setEnabled(True)
```

---

### 5. 当前用户菜单启用状态 — ⚠️ 已修改但可能不需要

**位置：** [`_setup_menu_bar`](../ui/main_window.py:867) 第 867 行

**修改前：**
```python
self.act_current_user.setEnabled(False)
```

**修改后：**
```python
self.act_current_user.setEnabled(True)
```

> 注意：`act_current_user` 原本设计为只读显示（`setEnabled(False)` 使其灰色不可点击），改为 `True` 后该菜单项变为可点击，但未连接任何信号，点击无反应。建议保持 `False` 或连接一个显示用户信息的弹窗。

---

## 待完成项

| # | 事项 | 位置 | 行号 |
|---|------|------|------|
| 1 | 考虑是否将 `act_current_user.setEnabled` 改回 `False` | `_setup_menu_bar` | 867 |
| 2 | 更新第 209 行注释文字 | `_setup_mode_toolbar` | 209 |

---

## 回滚方法

如需恢复为默认操作员，只需：

1. 删除第 133-134 行的新代码
2. 取消第 135-139 行 `'''` 注释（或直接恢复旧代码）
3. 第 209 行 `setEnabled(True)` → `setEnabled(False)`
4. 第 866 行 `"当前用户：工程师"` → `"当前用户：操作员"`
5. 第 867 行 `setEnabled(True)` → `setEnabled(False)`（如果改过的话）
6. 第 871 行 `setEnabled(True)` → `setEnabled(False)`
