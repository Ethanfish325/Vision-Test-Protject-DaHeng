# -*- coding: utf-8 -*-
import cv2
import numpy as np
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QImage


class ResultPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("检测结果")
        title.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #d4d4d4;
            padding: 6px 10px; background-color: #1e1e1e;
            border-bottom: 1px solid #444;
        """)
        title.setFixedHeight(32)

        self.status_indicator = QLabel("等待检测...")
        self.status_indicator.setAlignment(Qt.AlignCenter)
        self.status_indicator.setMinimumHeight(80)
        self.status_indicator.setStyleSheet("""
            font-size: 26px; font-weight: bold; color: #666;
            background-color: #1e1e1e; border: 2px solid #444;
            border-radius: 6px; padding: 8px;
        """)

        # 标注结果图像显示区域
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumHeight(200)
        self.image_label.setStyleSheet("""
            background-color: #1e1e1e; border: 1px solid #444;
            border-radius: 4px; padding: 4px;
        """)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setScaledContents(False)
        self.image_label.hide()

        layout.addWidget(title)
        layout.addWidget(self.status_indicator)
        layout.addWidget(self.image_label, 1)

    def show_result(self, passed, message, annotated_image=None, tool_results=None):
        if passed:
            self.status_indicator.setText("✓ OK")
            self.status_indicator.setStyleSheet("""
                font-size: 32px; font-weight: bold; color: #66BB6A;
                background-color: #1a3a1a; border: 3px solid #4CAF50;
                border-radius: 6px; padding: 8px;
            """)
        else:
            self.status_indicator.setText("✗ NG")
            self.status_indicator.setStyleSheet("""
                font-size: 32px; font-weight: bold; color: #EF5350;
                background-color: #3a1a1a; border: 3px solid #EF5350;
                border-radius: 6px; padding: 8px;
            """)

        # 显示标注结果图像
        if annotated_image is not None:
            self._display_image(annotated_image)
            self.image_label.show()
        else:
            self.image_label.hide()

    def _display_image(self, cv_img):
        """将 OpenCV BGR 图像转换为 QPixmap 并显示"""
        try:
            h, w = cv_img.shape[:2]
            if len(cv_img.shape) == 2:
                # 单通道灰度图 -> 三通道
                rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_GRAY2RGB)
            else:
                # BGR -> RGB
                rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)

            bytes_per_line = 3 * w
            q_img = QImage(rgb_img.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)

            # 缩放以适应 label，保持宽高比
            scaled = pixmap.scaled(
                self.image_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
        except Exception as e:
            print(f"ResultPanel 显示图像失败: {e}")

    def resizeEvent(self, event):
        """窗口大小变化时重新缩放图像"""
        super().resizeEvent(event)
        if self.image_label.pixmap() is not None:
            pixmap = self.image_label.pixmap()
            scaled = pixmap.scaled(
                self.image_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)

    def clear(self):
        self.status_indicator.setText("等待检测...")
        self.status_indicator.setStyleSheet("""
            font-size: 26px; font-weight: bold; color: #666;
            background-color: #1e1e1e; border: 2px solid #444;
            border-radius: 6px; padding: 8px;
        """)
        self.image_label.clear()
        self.image_label.hide()
