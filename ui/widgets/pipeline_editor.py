# -*- coding: utf-8 -*-
from typing import Dict, Optional, List, Any, Callable

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QDrag, QPixmap, QPainter, QColor

from vision.pipeline import Pipeline, PipelineStep, create_tool, get_all_tool_names, get_tools_by_category
from vision.tools.base_tool import VisionTool

from .operator_toolbox import OperatorToolbox
from .flow_canvas import FlowCanvas
from .step_slot_widget import StepSlot, CATEGORY_COLORS
from .param_config_dialog import ParamConfigDialog, MultiROIEditorDialog


class PropertyPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_slot: Optional[StepSlot] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel("属性")
        title.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #d4d4d4;
            padding: 8px 10px; background-color: #1e1e1e;
            border-bottom: 1px solid #444;
        """)
        title.setFixedHeight(36)

        self.info_group = QGroupBox("步骤信息")
        self.info_group.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #444;
                        border-radius: 4px; margin-top: 8px; padding-top: 12px; color: #d4d4d4; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #d4d4d4; }
        """)
        info_layout = QVBoxLayout(self.info_group)
        info_layout.setSpacing(2)

        self.index_label = QLabel("")
        self.index_label.setStyleSheet("color: #4A90D9; font-size: 15px; font-weight: bold;")
        self.name_label = QLabel("未选择步骤")
        self.name_label.setStyleSheet("font-size: 17px; font-weight: bold; color: #d4d4d4;")
        self.category_label = QLabel("")
        self.category_label.setStyleSheet("color: #999; font-size: 15px;")
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 15px;")

        info_layout.addWidget(self.index_label)
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.category_label)
        info_layout.addWidget(self.status_label)

        self.enable_check = QCheckBox("启用此步骤")
        self.enable_check.setStyleSheet("color: #d4d4d4; font-size: 15px;")
        self.enable_check.toggled.connect(self._on_enable_toggled)
        info_layout.addWidget(self.enable_check)

        self.param_group = QGroupBox("参数")
        self.param_group.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #444;
                        border-radius: 4px; margin-top: 8px; padding-top: 12px; color: #d4d4d4; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #d4d4d4; }
        """)
        param_group_layout = QVBoxLayout(self.param_group)
        param_group_layout.setContentsMargins(0, 4, 0, 4)
        param_group_layout.setSpacing(0)

        self.param_table = QTableWidget()
        self.param_table.setColumnCount(2)
        self.param_table.setHorizontalHeaderLabels(["参数", "值"])
        self.param_table.horizontalHeader().setStretchLastSection(True)
        self.param_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.param_table.verticalHeader().setVisible(False)
        self.param_table.setShowGrid(False)
        self.param_table.setAlternatingRowColors(True)
        self.param_table.setStyleSheet("""
            QTableWidget {
                background-color: #252525; color: #b0b0b0;
                border: none; font-size: 12px;
                alternate-background-color: #2a2a2a;
            }
            QTableWidget::item {
                padding: 5px 8px; border-bottom: 1px solid #3a3a3a;
            }
            QHeaderView::section {
                background-color: #3c3c3c; color: #999;
                border: none; border-bottom: 1px solid #444;
                padding: 5px 8px; font-weight: bold; font-size: 14px;
            }
        """)
        self.param_table.setMinimumHeight(60)

        param_group_layout.addWidget(self.param_table)

        self.btn_configure = QPushButton("⚙ 配置参数")
        self.btn_configure.setStyleSheet("""
            QPushButton {
                background-color: #1a3a5c; color: #4A90D9; padding: 6px 15px;
                border: 1px solid #2a5a8c; border-radius: 3px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2a4a7c; }
        """)
        self.btn_configure.clicked.connect(self._on_configure)

        self.btn_delete = QPushButton("🗑 删除步骤")
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #EF5350; padding: 6px 15px;
                border: 1px solid #555; border-radius: 3px;
            }
            QPushButton:hover { background-color: #4a2a2a; }
        """)
        self.btn_delete.clicked.connect(self._on_delete)

        layout.addWidget(title)
        layout.addWidget(self.info_group)
        layout.addWidget(self.param_group)
        layout.addStretch()
        layout.addWidget(self.btn_configure)
        layout.addWidget(self.btn_delete)

        self.setEnabled(False)

    def _get_display_name(self, tool_class_name: str) -> str:
        from vision.pipeline import ALL_TOOLS
        cls = ALL_TOOLS.get(tool_class_name)
        if cls and hasattr(cls, 'display_name'):
            return cls.display_name
        return tool_class_name

    def set_slot(self, slot: Optional[StepSlot]):
        self._current_slot = slot
        if slot is None or slot.is_empty():
            self.setEnabled(False)
            self.name_label.setText("未选择步骤")
            self.category_label.setText("")
            self.index_label.setText("")
            self.status_label.setText("")
            self._clear_params()
            return

        self.setEnabled(True)

        self.index_label.setText(f"▸ 步骤 #{slot.slot_index + 1}")

        display = self._get_display_name(slot.tool_name)
        self.name_label.setText(display)

        self.category_label.setText(f"类别: {slot.category}")

        enabled = slot.is_enabled()
        if enabled:
            self.status_label.setText("● 已启用")
            self.status_label.setStyleSheet("font-size: 15px; color: #66BB6A;")
        else:
            self.status_label.setText("● 已禁用")
            self.status_label.setStyleSheet("font-size: 15px; color: #EF5350;")

        self.enable_check.blockSignals(True)
        self.enable_check.setChecked(enabled)
        self.enable_check.blockSignals(False)

        self._update_params(slot.params)

    def _update_params(self, params: Dict):
        self._clear_params()

        rows = []
        for k, v in params.items():
            if k == "input_source":
                display_key = "输入源"
                display_val = str(v)
                row_color = "#4fc3f7"
            elif k == "regions":
                if isinstance(v, list):
                    display_key = "ROI区域"
                    display_val = f"{len(v)} 个区域"
                    row_color = "#ffa726"
                else:
                    continue
            else:
                display_key = k
                display_val = str(v)
                row_color = "#b0b0b0"
            rows.append((display_key, display_val, row_color))

        if not rows:
            self.param_table.setRowCount(1)
            self.param_table.setItem(0, 0, QTableWidgetItem("(无参数)"))
            self.param_table.item(0, 0).setForeground(QColor("#888"))
            return

        self.param_table.setRowCount(len(rows))
        for i, (key, val, color) in enumerate(rows):
            key_item = QTableWidgetItem(key)
            key_item.setForeground(QColor(color))
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)

            val_item = QTableWidgetItem(val)
            val_item.setForeground(QColor("#d4d4d4"))
            val_item.setFlags(val_item.flags() & ~Qt.ItemIsEditable)

            self.param_table.setItem(i, 0, key_item)
            self.param_table.setItem(i, 1, val_item)

    def _clear_params(self):
        self.param_table.setRowCount(0)

    def _on_enable_toggled(self, checked: bool):
        if self._current_slot and not self._current_slot.is_empty():
            self._current_slot.set_enabled(checked)
            if checked:
                self.status_label.setText("● 已启用")
                self.status_label.setStyleSheet("font-size: 13px; color: #66BB6A;")
            else:
                self.status_label.setText("● 已禁用")
                self.status_label.setStyleSheet("font-size: 13px; color: #EF5350;")
            parent = self.parent()
            while parent:
                if hasattr(parent, 'pipeline_changed'):
                    parent.pipeline_changed.emit()
                    break
                parent = parent.parent()

    def _on_configure(self):
        if self._current_slot and not self._current_slot.is_empty():
            parent = self.parent()
            while parent:
                if hasattr(parent, '_config_step'):
                    parent._config_step(self._current_slot.slot_index)
                    break
                parent = parent.parent()

    def _on_delete(self):
        if self._current_slot and not self._current_slot.is_empty():
            parent = self.parent()
            while parent:
                if hasattr(parent, '_remove_step'):
                    parent._remove_step(self._current_slot.slot_index)
                    break
                parent = parent.parent()


class PipelineEditor(QWidget):
    pipeline_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pipeline = Pipeline("未命名")
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        toolbar = self._build_toolbar()
        main_layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Horizontal)

        self.operator_toolbox = OperatorToolbox()
        self.operator_toolbox.setMinimumWidth(200)
        self.operator_toolbox.setMaximumWidth(300)

        self.flow_canvas = FlowCanvas()
        self.flow_canvas.setMinimumWidth(400)

        self.property_panel = PropertyPanel()
        self.property_panel.setMinimumWidth(200)
        self.property_panel.setMaximumWidth(300)

        splitter.addWidget(self.operator_toolbox)
        splitter.addWidget(self.flow_canvas)
        splitter.addWidget(self.property_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([220, 600, 220])

        main_layout.addWidget(splitter, 1)

        self._connect_signals()

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setStyleSheet("""
            background-color: #252525; border-bottom: 1px solid #444;
        """)
        toolbar.setFixedHeight(40)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self.btn_clear = QPushButton("🗑 清空")
        self.btn_clear.setStyleSheet("""
            QPushButton { background-color: #3c3c3c; color: #EF5350; padding: 2px 12px;
                         border: 1px solid #555; border-radius: 3px; font-size: 15px; }
            QPushButton:hover { background-color: #4a2a2a; }
        """)

        layout.addWidget(self.btn_clear)
        layout.addStretch()

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #999; font-size: 15px;")

        self.node_count_label = QLabel("算子: 0")
        self.node_count_label.setStyleSheet("color: #999; font-size: 15px;")

        layout.addWidget(self.node_count_label)
        layout.addWidget(self.status_label)

        return toolbar

    def _connect_signals(self):
        self.btn_clear.clicked.connect(self._clear_pipeline)

        self.flow_canvas.pipeline_changed.connect(self._on_canvas_changed)
        self.flow_canvas.node_config_requested.connect(self._config_step)
        self.flow_canvas.slot_selected.connect(self._on_slot_selected)

    def _on_canvas_changed(self):
        slot_widget = self.flow_canvas.get_slot_widget()
        occupied = slot_widget.get_occupied_slots()
        count = len(occupied)
        self.node_count_label.setText(f"算子: {count}")
        self.status_label.setText(f"已更新 ({count} 个算子)")

        self._sync_to_pipeline()
        self.pipeline_changed.emit()

    def _sync_to_pipeline(self):
        slot_widget = self.flow_canvas.get_slot_widget()
        self._pipeline.steps.clear()

        for slot in slot_widget.get_occupied_slots():
            try:
                tool = create_tool(slot.tool_name)
                if tool:
                    tool.params = slot.params.copy()
                    self._pipeline.add_step(tool, enabled=slot.is_enabled())
            except Exception:
                continue

    def _clear_pipeline(self):
        slot_widget = self.flow_canvas.get_slot_widget()
        if slot_widget.get_occupied_slots():
            reply = QMessageBox.question(self, "确认", "确定清空所有步骤？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.flow_canvas.clear_all()
                self.property_panel.set_slot(None)
                self.pipeline_changed.emit()

    def _config_step(self, index: int):
        slot_widget = self.flow_canvas.get_slot_widget()
        # 使用slot_index直接查找，而不是索引过滤后的occupied列表
        slot = slot_widget.get_slot_by_index(index)
        if slot is None or slot.is_empty():
            return

        context_info = self._get_context_info(index)

        tool = create_tool(slot.tool_name)
        if tool is None:
            return
        tool.params = slot.params.copy()

        # 注意: VisionTool.__init__ 会覆盖 display_name 为类名，所以用类名比较
        if tool.name == "MultiROI":
            preview_img = self._get_preview_image()
            if preview_img is not None:
                dialog = MultiROIEditorDialog(tool, preview_img, self)
                if dialog.exec_() == QDialog.Accepted:
                    slot.params = tool.params.copy()
                    self._sync_to_pipeline()
                    self.pipeline_changed.emit()
                    self.property_panel.set_slot(slot)
            else:
                QMessageBox.information(self, "提示",
                    "请先加载一张图片（点击「加载图片」按钮），"
                    "然后才能绘制ROI区域。\n\n"
                    "或者，您也可以在方案JSON文件中手动编辑regions参数。")
        else:
            preview_img = self._get_preview_image()
            dialog = ParamConfigDialog(tool, preview_img, context_info, self)
            if dialog.exec_() == QDialog.Accepted:
                slot.params = tool.params.copy()
                self._sync_to_pipeline()
                self.pipeline_changed.emit()
                self.property_panel.set_slot(slot)

    def _get_context_info(self, current_step_index: int) -> Dict:
        regions = []
        regions_map = {}  # name -> (x, y, w, h)
        steps = []
        slot_widget = self.flow_canvas.get_slot_widget()
        # 遍历所有slots，使用slot_index进行比较
        for slot in slot_widget._slots:
            if not slot._is_occupied:
                continue
            if slot.slot_index == current_step_index:
                continue
            # slot.tool_name是类名(如"MultiROI")，需要用类名比较
            if slot.slot_index < current_step_index and slot.tool_name == "MultiROI":
                for r in slot.params.get("regions", []):
                    if r.get("enabled", True):
                        name = r.get("name", "")
                        regions.append(name)
                        regions_map[name] = (
                            r.get("x", 0),
                            r.get("y", 0),
                            r.get("width", r.get("w", 100)),
                            r.get("height", r.get("h", 100)),
                        )
            steps.append({
                "index": slot.slot_index,
                "name": slot.tool_name,
            })
        return {"regions": regions, "regions_map": regions_map, "steps": steps}

    def _get_preview_image(self):
        # 优先从MainWindow获取_raw_image
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_raw_image') and parent._raw_image is not None:
                return parent._raw_image.copy()
            parent = parent.parent()
        # 如果父链没找到，尝试从顶层窗口获取
        top = self.window()
        if hasattr(top, '_raw_image') and top._raw_image is not None:
            return top._raw_image.copy()
        return None

    def _on_slot_selected(self, slot_index: int):
        slot_widget = self.flow_canvas.get_slot_widget()
        slot = slot_widget.get_slot_by_index(slot_index)
        if slot and not slot.is_empty():
            self.property_panel.set_slot(slot)

    def _remove_step(self, index: int):
        slot_widget = self.flow_canvas.get_slot_widget()
        slot = slot_widget.get_slot_by_index(index)
        if slot and slot._is_occupied:
            slot_widget._on_delete_operator(slot.slot_index)
            self.property_panel.set_slot(None)
            self.pipeline_changed.emit()

    def set_pipeline(self, pipeline: Pipeline):
        self._pipeline = pipeline
        self.flow_canvas.from_pipeline(pipeline)
        self.property_panel.set_slot(None)

        slot_widget = self.flow_canvas.get_slot_widget()
        count = len(slot_widget.get_occupied_slots())
        self.node_count_label.setText(f"算子: {count}")

    def get_pipeline(self) -> Pipeline:
        self._sync_to_pipeline()
        return self._pipeline
