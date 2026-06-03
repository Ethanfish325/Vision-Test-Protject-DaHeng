# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QImage

from camera_manager import CameraManager
from core.log_manager import log_info, log_error


class CameraPanel(QWidget):

    frame_received = pyqtSignal(int, int, int, bytes)
    capture_completed = pyqtSignal(int, int, int, bytes)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cam_mgr = CameraManager()
        self._device_data = {}
        self._is_capturing = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        ctrl_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.refresh_btn = QPushButton("刷新设备")
        self.open_btn = QPushButton("打开相机")
        self.close_btn = QPushButton("关闭相机")
        self.capture_btn = QPushButton("拍 照")
        self.capture_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2; color: #fff; font-weight: bold;
                padding: 8px 22px; border: none;
                border-radius: 3px; font-size: 16px;
            }
            QPushButton:hover { background-color: #1565C0; }
            QPushButton:disabled { background-color: #3c3c3c; color: #666; }
        """)
        self.open_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)

        lbl_camera = QLabel("相机:")
        lbl_camera.setStyleSheet("color: #d4d4d4;")
        ctrl_layout.addWidget(lbl_camera)
        ctrl_layout.addWidget(self.device_combo)
        ctrl_layout.addWidget(self.refresh_btn)
        ctrl_layout.addWidget(self.open_btn)
        ctrl_layout.addWidget(self.close_btn)
        ctrl_layout.addWidget(self.capture_btn)
        ctrl_layout.addStretch()

        self.display_label = QLabel()
        self.display_label.setStyleSheet("background-color: #0d0d0d; border: 1px solid #444;")
        self.display_label.setMinimumSize(640, 480)
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setText("相机未打开")

        layout.addLayout(ctrl_layout)
        layout.addWidget(self.display_label, 1)

        self.refresh_btn.clicked.connect(self.enumerate_devices)
        self.open_btn.clicked.connect(self.open_camera)
        self.close_btn.clicked.connect(self.close_camera)
        self.capture_btn.clicked.connect(self.capture_once)

    def enumerate_devices(self):
        try:
            devices = self.cam_mgr.enumerate_devices()
            self.device_combo.clear()
            self._device_data = {}
            for device in devices:
                idx = device.get("index", 0)
                name = device.get("name", "未知")
                self.device_combo.addItem(name, idx)
                self._device_data[idx] = device.get("info")
            self.open_btn.setEnabled(len(devices) > 0)
            self.status_message.emit(f"发现 {len(devices)} 个相机")
        except Exception as e:
            QMessageBox.warning(self, "错误", str(e))

    def open_camera(self):
        if self.cam_mgr.is_open:
            QMessageBox.warning(self, "提示", "相机已打开")
            return

        idx = self.device_combo.currentData()
        if idx is None:
            QMessageBox.warning(self, "提示", "请先刷新并选择相机")
            return

        dev_info = self._device_data.get(idx)
        if not dev_info:
            return

        try:
            self.cam_mgr.open_camera(dev_info)
            self.cam_mgr.start_grabbing(self._on_frame_received)
            self.open_btn.setEnabled(False)
            self.close_btn.setEnabled(True)
            self.capture_btn.setEnabled(True)
            self.display_label.setText("实时画面中...")
            self.status_message.emit("相机已打开")
            log_info("相机已打开")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            log_error(f"打开相机失败: {e}")

    def close_camera(self):
        self.cam_mgr.close_camera()
        self.open_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        self.display_label.clear()
        self.display_label.setText("相机未打开")
        self.status_message.emit("相机已关闭")
        log_info("相机已关闭")

    def _on_frame_received(self, width, height, pixel_type, img_bytes):
        self.frame_received.emit(width, height, pixel_type, img_bytes)
        self.cam_mgr.display_frame(self.display_label, width, height, pixel_type, img_bytes)

    def capture_once(self):
        if self._is_capturing:
            return

        self._is_capturing = True
        self.capture_btn.setEnabled(False)
        self.capture_btn.setText("拍照中...")
        self.status_message.emit("拍照中...")

        class CaptureThread(QThread):
            finished = pyqtSignal(object)

            def __init__(self, cam_mgr):
                super().__init__()
                self.cam_mgr = cam_mgr

            def run(self):
                result = self.cam_mgr.capture_once(timeout_ms=3000)
                self.finished.emit(result)

        self._capture_thread = CaptureThread(self.cam_mgr)
        self._capture_thread.finished.connect(self._on_capture_finished)
        self._capture_thread.start()

    def _on_capture_finished(self, result):
        self._is_capturing = False
        self.capture_btn.setEnabled(True)
        self.capture_btn.setText("拍 照")

        if result is not None:
            width, height, pixel_type, img_bytes = result
            self.cam_mgr.display_frame(self.display_label, width, height, pixel_type, img_bytes)
            self.capture_completed.emit(width, height, pixel_type, img_bytes)
            self.status_message.emit("拍照完成")
            log_info(f"拍照完成: {width}x{height}")
        else:
            QMessageBox.warning(self, "拍照失败", "获取图像超时或失败，请重试")
            self.status_message.emit("拍照失败")
            log_error("拍照失败")

    def is_camera_open(self):
        return self.cam_mgr.is_open
