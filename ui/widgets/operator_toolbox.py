# -*- coding: utf-8 -*-
import os
from typing import List, Dict, Optional
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
                             QLineEdit, QLabel, QHBoxLayout, QApplication, QFrame)
from PyQt5.QtCore import Qt, QSize, QPoint, QMimeData, QEvent
from PyQt5.QtGui import QDrag, QPixmap, QPainter, QColor, QFont, QIcon, QBrush, QCursor

from ..constants import CATEGORY_COLORS, CATEGORY_ICONS


class DraggableOperatorItem(QListWidgetItem):
    def __init__(self, tool_name: str, category: str):
        super().__init__(tool_name)
        self._tool_name = tool_name
        self._category = category
        color = QColor(CATEGORY_COLORS.get(category, "#333333"))
        self.setForeground(color)
        self.setToolTip(f"{category} - {tool_name}")
        self.setSizeHint(QSize(0, 36))

    def tool_name(self) -> str:
        return self._tool_name

    def category(self) -> str:
        return self._category


class OperatorCategoryItem(QListWidgetItem):
    def __init__(self, category: str):
        super().__init__(f"  {CATEGORY_ICONS.get(category, '')} {category}")
        self._category = category
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        self.setFont(font)
        color = QColor(CATEGORY_COLORS.get(category, "#333333"))
        self.setForeground(color)
        bg = QColor(color)
        bg.setAlpha(20)
        self.setBackground(bg)
        self.setFlags(Qt.ItemIsEnabled)
        self.setSizeHint(QSize(0, 36))

    def category(self) -> str:
        return self._category


class ToolboxListWidget(QListWidget):
    def __init__(self, toolbox):
        super().__init__()
        self._toolbox = toolbox
        self._setup_style()

    def _setup_style(self):
        self.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-radius: 4px;
                margin: 2px 0;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
            QListWidget::item:selected {
                background-color: #1a3a5c;
                border: 1px solid #4A90D9;
            }
            QListWidget::item:selected:!active {
                background-color: #1a3a5c;
            }
        """)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if isinstance(item, DraggableOperatorItem):
            self._toolbox._start_drag(item)


class OperatorToolbox(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool_items: List[DraggableOperatorItem] = []
        self._category_rows: Dict[str, int] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(6)

        title_icon = QLabel("🧰")
        title_icon.setStyleSheet("font-size: 16px;")
        title_layout.addWidget(title_icon)

        title = QLabel("算子工具箱")
        title.setStyleSheet("""
            font-size: 15px;
            font-weight: bold;
            color: #d4d4d4;
            padding: 0;
        """)
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍 搜索算子...")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._filter_tools)
        self._search_box.installEventFilter(self)
        self._search_box.setStyleSheet("""
            QLineEdit {
                padding: 8px 12px;
                border: 1px solid #555;
                border-radius: 6px;
                background-color: #3c3c3c;
                font-size: 13px;
                color: #d4d4d4;
            }
            QLineEdit:focus {
                border: 2px solid #4A90D9;
                background-color: #2d2d2d;
            }
            QLineEdit:hover {
                border-color: #777;
            }
        """)
        layout.addWidget(self._search_box)

        self._list = ToolboxListWidget(self)
        self._list.setDragEnabled(True)
        self._list.setDefaultDropAction(Qt.CopyAction)
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.setIconSize(QSize(24, 24))
        self._list.setSpacing(0)
        layout.addWidget(self._list)

        self._populate_tools()

    def _get_display_name(self, tool_class_name: str) -> str:
        from vision.pipeline import ALL_TOOLS
        cls = ALL_TOOLS.get(tool_class_name)
        if cls and hasattr(cls, 'display_name'):
            return cls.display_name
        return tool_class_name

    def _populate_tools(self):
        self._list.clear()
        self._tool_items.clear()
        self._category_rows.clear()

        from vision.pipeline import get_tools_by_category
        categorized = get_tools_by_category()

        row = 0
        for category, tools in categorized.items():
            cat_item = OperatorCategoryItem(category)
            self._list.addItem(cat_item)
            self._category_rows[category] = row
            row += 1

            for tool_name in tools:
                display = self._get_display_name(tool_name)
                item = DraggableOperatorItem(tool_name, category)
                item.setText(display)
                self._list.addItem(item)
                self._tool_items.append(item)
                row += 1

    def _filter_tools(self, text: str):
        self._list.clear()
        if not text.strip():
            self._populate_tools()
            return

        from vision.pipeline import get_tools_by_category
        categorized = get_tools_by_category()

        for category, tools in categorized.items():
            matched = []
            for t in tools:
                display = self._get_display_name(t)
                if text.lower() in display.lower() or text.lower() in t.lower():
                    matched.append(t)
            if matched:
                cat_item = OperatorCategoryItem(category)
                self._list.addItem(cat_item)
                for tool_name in matched:
                    display = self._get_display_name(tool_name)
                    item = DraggableOperatorItem(tool_name, category)
                    item.setText(display)
                    self._list.addItem(item)
                    self._tool_items.append(item)

    def eventFilter(self, obj, event):
        if obj is self._search_box and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Down:
                self._list.setFocus()
                if self._list.count() > 0:
                    self._list.setCurrentRow(0)
                return True
        return super().eventFilter(obj, event)

    def _start_drag(self, item: DraggableOperatorItem):
        drag = QDrag(self._list)
        mime = QMimeData()
        import json
        data = json.dumps({
            "tool_name": item.tool_name(),
            "category": item.category(),
            "params": {},
            "enabled": True,
            "from_slot": -1
        })
        mime.setData("application/x-operator", data.encode("utf-8"))
        drag.setMimeData(mime)

        display = self._get_display_name(item.tool_name())
        icon = CATEGORY_ICONS.get(item.category(), "")

        pixmap = QPixmap(160, 40)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor(CATEGORY_COLORS.get(item.category(), "#333333"))
        bg_color = QColor(color)
        bg_color.setAlpha(230)
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, 160, 40, 8, 8)

        painter.setPen(Qt.white)
        icon_font = QFont("Segoe UI Emoji", 14)
        painter.setFont(icon_font)
        painter.drawText(12, 26, icon)

        text_font = QFont("Microsoft YaHei", 11, QFont.Bold)
        painter.setFont(text_font)
        painter.drawText(40, 25, display)

        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(80, 20))

        result = drag.exec_(Qt.CopyAction)

    def get_all_tool_names(self) -> List[str]:
        return [item.tool_name() for item in self._tool_items]
