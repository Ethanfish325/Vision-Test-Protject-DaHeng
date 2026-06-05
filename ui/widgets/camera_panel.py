# -*- coding: utf-8 -*-
"""
相机控制面板
============
提供相机设备选择、打开/关闭、实时预览、参数调节（曝光/增益/帧率）、
触发模式切换、拍照等功能。
"""

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QImage

from camera_manager import CameraManager
from core.log_manager import log_info, log_error


class CameraPanel(QWidget):
    """
    相机控制面板。

    信号:
        frame_received(int, int, int, bytes): 实时帧数据信号
        capture_completed(int, int, int, bytes): 拍照完成信号
        status_message(str): 状态消息信号
    """

    frame_received = pyqtSignal(int, int, int, bytes)
    capture_completed = pyqtSignal(int, int, int, bytes)
    status_message = pyqtSignal(str)

    # 参数调节步长
    EXPOSURE_STEP = 500.0      # 微秒
    GAIN_STEP = 1.0            # dB
    FRAME_RATE_STEP = 1.0      # fps

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cam_mgr = CameraManager()
        self._device_data = {}
        self._is_capturing = False

        # 参数范围缓存
        self._exposure_min = 0.0
        self._exposure_max = 100000.0
        self._gain_min = 0.0
        self._gain_max = 24.0

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """构建 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ========== 顶部控制栏 ==========
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(6)

        lbl_camera = QLabel("相机:")
        lbl_camera.setStyleSheet("color: #d4d4d4; font-weight: bold;")

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(280)
        self.device_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c; color: #d4d4d4;
                border: 1px solid #555; border-radius: 3px;
                padding: 4px 8px; min-height: 24px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d; color: #d4d4d4;
                selection-background-color: #1a3a5c;
            }
        """)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4;
                padding: 4px 14px; border: 1px solid #555;
                border-radius: 3px; min-height: 24px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)

        self.open_btn = QPushButton("打开")
        self.open_btn.setEnabled(False)
        self.open_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a3a5c; color: #4A90D9;
                padding: 4px 14px; border: 1px solid #2a5a8c;
                border-radius: 3px; min-height: 24px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2a4a7c; }
            QPushButton:disabled { background-color: #3c3c3c; color: #666; border-color: #555; }
        """)

        self.close_btn = QPushButton("关闭")
        self.close_btn.setEnabled(False)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: #5c1a1a; color: #D94A4A;
                padding: 4px 14px; border: 1px solid #8c2a2a;
                border-radius: 3px; min-height: 24px; font-weight: bold;
            }
            QPushButton:hover { background-color: #7c2a2a; }
            QPushButton:disabled { background-color: #3c3c3c; color: #666; border-color: #555; }
        """)

        self.capture_btn = QPushButton("📷 拍照")
        self.capture_btn.setEnabled(False)
        self.capture_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976D2; color: #fff; font-weight: bold;
                padding: 6px 22px; border: none; border-radius: 3px;
                font-size: 15px; min-height: 28px;
            }
            QPushButton:hover { background-color: #1565C0; }
            QPushButton:disabled { background-color: #3c3c3c; color: #666; }
        """)

        ctrl_layout.addWidget(lbl_camera)
        ctrl_layout.addWidget(self.device_combo, 1)
        ctrl_layout.addWidget(self.refresh_btn)
        ctrl_layout.addWidget(self.open_btn)
        ctrl_layout.addWidget(self.close_btn)
        ctrl_layout.addWidget(self.capture_btn)

        # ========== 主区域（显示 + 参数面板） ==========
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：图像显示
        display_widget = QWidget()
        display_layout = QVBoxLayout(display_widget)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(4)

        display_title = QLabel("实时画面")
        display_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #d4d4d4;")

        self.display_label = QLabel()
        self.display_label.setStyleSheet("""
            background-color: #0d0d0d; border: 1px solid #444;
            border-radius: 3px;
        """)
        self.display_label.setMinimumSize(640, 480)
        self.display_label.setAlignment(Qt.AlignCenter)
        self.display_label.setText("相机未打开")

        display_layout.addWidget(display_title)
        display_layout.addWidget(self.display_label, 1)

        # 右侧：参数面板
        param_widget = QWidget()
        param_widget.setMinimumWidth(280)
        param_widget.setMaximumWidth(320)
        param_layout = QVBoxLayout(param_widget)
        param_layout.setContentsMargins(8, 0, 0, 0)
        param_layout.setSpacing(8)

        # -- 触发模式 --
        trigger_group = QGroupBox("触发模式")
        trigger_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 14px; border: 1px solid #444;
                border-radius: 4px; margin-top: 10px; padding-top: 16px;
                color: #d4d4d4;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
                color: #d4d4d4;
            }
        """)
        trigger_layout = QVBoxLayout(trigger_group)
        trigger_layout.setContentsMargins(8, 8, 8, 8)
        trigger_layout.setSpacing(6)

        self.trigger_combo = QComboBox()
        self.trigger_combo.addItems(["连续采集", "触发模式（软触发）"])
        self.trigger_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c; color: #d4d4d4;
                border: 1px solid #555; border-radius: 3px;
                padding: 4px 8px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d; color: #d4d4d4;
                selection-background-color: #1a3a5c;
            }
        """)

        self.trigger_btn = QPushButton("发送软触发")
        self.trigger_btn.setEnabled(False)
        self.trigger_btn.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4;
                padding: 6px 12px; border: 1px solid #555;
                border-radius: 3px; font-weight: bold;
            }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:disabled { background-color: #2d2d2d; color: #555; }
        """)

        trigger_layout.addWidget(self.trigger_combo)
        trigger_layout.addWidget(self.trigger_btn)

        # -- 曝光时间 --
        exp_group = QGroupBox("曝光时间")
        exp_group.setStyleSheet(trigger_group.styleSheet())
        exp_layout = QVBoxLayout(exp_group)
        exp_layout.setContentsMargins(8, 8, 8, 8)
        exp_layout.setSpacing(4)

        exp_slider_layout = QHBoxLayout()
        self.exp_slider = QSlider(Qt.Horizontal)
        self.exp_slider.setRange(0, 1000)
        self.exp_slider.setValue(500)
        self.exp_value_label = QLabel("-- us")
        self.exp_value_label.setMinimumWidth(80)
        self.exp_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.exp_value_label.setStyleSheet("color: #4fc3f7; font-weight: bold;")

        exp_slider_layout.addWidget(self.exp_slider, 1)
        exp_slider_layout.addWidget(self.exp_value_label)

        exp_btn_layout = QHBoxLayout()
        self.exp_minus_btn = QPushButton("--")
        self.exp_plus_btn = QPushButton("++")
        for btn in [self.exp_minus_btn, self.exp_plus_btn]:
            btn.setFixedWidth(40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3c3c3c; color: #d4d4d4;
                    border: 1px solid #555; border-radius: 3px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #4a4a4a; }
                QPushButton:disabled { background-color: #2d2d2d; color: #555; }
            """)
        self.exp_auto_check = QCheckBox("自动曝光")
        self.exp_auto_check.setStyleSheet("color: #d4d4d4;")
        self.exp_auto_check.setChecked(True)  # 默认开启自动曝光

        exp_btn_layout.addWidget(self.exp_minus_btn)
        exp_btn_layout.addWidget(self.exp_plus_btn)
        exp_btn_layout.addWidget(self.exp_auto_check)
        exp_btn_layout.addStretch()

        exp_layout.addLayout(exp_slider_layout)
        exp_layout.addLayout(exp_btn_layout)

        # -- 增益 --
        gain_group = QGroupBox("增益")
        gain_group.setStyleSheet(trigger_group.styleSheet())
        gain_layout = QVBoxLayout(gain_group)
        gain_layout.setContentsMargins(8, 8, 8, 8)
        gain_layout.setSpacing(4)

        gain_slider_layout = QHBoxLayout()
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(0, 240)  # 0.0 ~ 24.0 dB
        self.gain_slider.setValue(0)
        self.gain_value_label = QLabel("-- dB")
        self.gain_value_label.setMinimumWidth(80)
        self.gain_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.gain_value_label.setStyleSheet("color: #4fc3f7; font-weight: bold;")

        gain_slider_layout.addWidget(self.gain_slider, 1)
        gain_slider_layout.addWidget(self.gain_value_label)

        gain_btn_layout = QHBoxLayout()
        self.gain_minus_btn = QPushButton("--")
        self.gain_plus_btn = QPushButton("++")
        for btn in [self.gain_minus_btn, self.gain_plus_btn]:
            btn.setFixedWidth(40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3c3c3c; color: #d4d4d4;
                    border: 1px solid #555; border-radius: 3px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #4a4a4a; }
                QPushButton:disabled { background-color: #2d2d2d; color: #555; }
            """)
        self.gain_auto_check = QCheckBox("自动增益")
        self.gain_auto_check.setStyleSheet("color: #d4d4d4;")
        self.gain_auto_check.setChecked(True)  # 默认开启自动增益

        gain_btn_layout.addWidget(self.gain_minus_btn)
        gain_btn_layout.addWidget(self.gain_plus_btn)
        gain_btn_layout.addWidget(self.gain_auto_check)
        gain_btn_layout.addStretch()

        gain_layout.addLayout(gain_slider_layout)
        gain_layout.addLayout(gain_btn_layout)

        # -- 帧率 --
        fps_group = QGroupBox("帧率")
        fps_group.setStyleSheet(trigger_group.styleSheet())
        fps_layout = QVBoxLayout(fps_group)
        fps_layout.setContentsMargins(8, 8, 8, 8)
        fps_layout.setSpacing(4)

        fps_slider_layout = QHBoxLayout()
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setRange(0, 300)  # 0 ~ 30.0 fps
        self.fps_slider.setValue(0)
        self.fps_value_label = QLabel("-- fps")
        self.fps_value_label.setMinimumWidth(80)
        self.fps_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.fps_value_label.setStyleSheet("color: #4fc3f7; font-weight: bold;")

        fps_slider_layout.addWidget(self.fps_slider, 1)
        fps_slider_layout.addWidget(self.fps_value_label)

        fps_btn_layout = QHBoxLayout()
        self.fps_minus_btn = QPushButton("--")
        self.fps_plus_btn = QPushButton("++")
        for btn in [self.fps_minus_btn, self.fps_plus_btn]:
            btn.setFixedWidth(40)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3c3c3c; color: #d4d4d4;
                    border: 1px solid #555; border-radius: 3px;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #4a4a4a; }
                QPushButton:disabled { background-color: #2d2d2d; color: #555; }
            """)

        fps_btn_layout.addWidget(self.fps_minus_btn)
        fps_btn_layout.addWidget(self.fps_plus_btn)
        fps_btn_layout.addStretch()

        fps_layout.addLayout(fps_slider_layout)
        fps_layout.addLayout(fps_btn_layout)

        # 组装参数面板
        param_layout.addWidget(trigger_group)
        param_layout.addWidget(exp_group)
        param_layout.addWidget(gain_group)
        param_layout.addWidget(fps_group)
        param_layout.addStretch()

        splitter.addWidget(display_widget)
        splitter.addWidget(param_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        # ========== 底部状态栏 ==========
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #1e1e1e; color: #999;
                border-top: 1px solid #444; padding: 2px 8px;
            }
        """)
        self.status_bar.showMessage("就绪")

        # 组装主布局
        main_layout.addLayout(ctrl_layout)
        main_layout.addWidget(splitter, 1)
        main_layout.addWidget(self.status_bar)

    def _connect_signals(self):
        """连接信号与槽"""
        self.refresh_btn.clicked.connect(self.enumerate_devices)
        self.open_btn.clicked.connect(self.open_camera)
        self.close_btn.clicked.connect(self.close_camera)
        self.capture_btn.clicked.connect(self.capture_once)

        # 触发模式
        self.trigger_combo.currentIndexChanged.connect(self._on_trigger_mode_changed)
        self.trigger_btn.clicked.connect(self._on_soft_trigger)

        # 曝光
        self.exp_slider.valueChanged.connect(self._on_exp_slider_changed)
        self.exp_minus_btn.clicked.connect(lambda: self._adjust_exposure(-self.EXPOSURE_STEP))
        self.exp_plus_btn.clicked.connect(lambda: self._adjust_exposure(self.EXPOSURE_STEP))
        self.exp_auto_check.stateChanged.connect(self._on_exp_auto_changed)

        # 增益
        self.gain_slider.valueChanged.connect(self._on_gain_slider_changed)
        self.gain_minus_btn.clicked.connect(lambda: self._adjust_gain(-self.GAIN_STEP))
        self.gain_plus_btn.clicked.connect(lambda: self._adjust_gain(self.GAIN_STEP))
        self.gain_auto_check.stateChanged.connect(self._on_gain_auto_changed)

        # 帧率
        self.fps_slider.valueChanged.connect(self._on_fps_slider_changed)
        self.fps_minus_btn.clicked.connect(lambda: self._adjust_frame_rate(-self.FRAME_RATE_STEP))
        self.fps_plus_btn.clicked.connect(lambda: self._adjust_frame_rate(self.FRAME_RATE_STEP))

    # ========== 设备枚举 ==========

    def enumerate_devices(self):
        """异步枚举相机设备"""
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("搜索中...")
        self.status_bar.showMessage("正在搜索相机...")
        self.status_message.emit("正在搜索相机...")

        class EnumThread(QThread):
            finished = pyqtSignal(object)

            def __init__(self, cam_mgr):
                super().__init__()
                self.cam_mgr = cam_mgr

            def run(self):
                devices = self.cam_mgr.enumerate_devices(timeout_ms=200)
                self.finished.emit(devices)

        self._enum_thread = EnumThread(self.cam_mgr)
        self._enum_thread.finished.connect(self._on_enum_finished)
        self._enum_thread.start()

    def _on_enum_finished(self, devices):
        try:
            self.device_combo.clear()
            self._device_data = {}
            for device in devices:
                idx = device.get("index", 0)
                name = device.get("name", "未知")
                model = device.get("model", "")
                serial = device.get("serial", "")
                ip = device.get("ip", "")
                dev_info = device.get("dev_info")
                if dev_info is None:
                    continue

                # 显示名称: 型号 + 序列号
                display_name = f"{model} ({serial})" if serial else name
                if ip and ip != "N/A":
                    display_name += f" [{ip}]"

                self.device_combo.addItem(display_name, idx)
                self._device_data[idx] = {
                    "dev_info": dev_info,
                    "info": device,
                }

            self.open_btn.setEnabled(len(devices) > 0)
            msg = f"发现 {len(devices)} 个相机"
            self.status_bar.showMessage(msg)
            self.status_message.emit(msg)
        except RuntimeError:
            pass
        finally:
            try:
                self.refresh_btn.setEnabled(True)
                self.refresh_btn.setText("刷新")
            except RuntimeError:
                pass

    # ========== 打开/关闭 ==========

    def open_camera(self):
        if self.cam_mgr.is_open:
            QMessageBox.warning(self, "提示", "相机已打开")
            return

        idx = self.device_combo.currentData()
        if idx is None:
            QMessageBox.warning(self, "提示", "请先刷新并选择相机")
            return

        device_entry = self._device_data.get(idx)
        if device_entry is None:
            QMessageBox.warning(self, "提示", "设备信息无效，请重新刷新")
            return

        dev_info = device_entry["dev_info"]

        try:
            success = self.cam_mgr.open_camera(dev_info)
            if not success:
                QMessageBox.critical(self, "错误", "打开相机失败，请检查相机连接")
                return

            # 开始实时取流
            self.cam_mgr.start_grabbing(self._on_frame_received)

            # 更新 UI 状态
            self.open_btn.setEnabled(False)
            self.close_btn.setEnabled(True)
            self.capture_btn.setEnabled(True)
            self.trigger_combo.setEnabled(True)
            self.trigger_btn.setEnabled(self.cam_mgr.is_trigger_mode)
            self.display_label.setText("实时画面中...")

            # 默认开启自动曝光和自动增益
            self.cam_mgr.set_enum_param("ExposureAuto", 1)
            self.cam_mgr.set_enum_param("GainAuto", 1)

            # 读取当前参数并更新 UI
            self._refresh_params()

            # 根据自动曝光/增益状态更新滑块可用性
            self.exp_slider.setEnabled(not self.exp_auto_check.isChecked())
            self.exp_minus_btn.setEnabled(not self.exp_auto_check.isChecked())
            self.exp_plus_btn.setEnabled(not self.exp_auto_check.isChecked())
            self.gain_slider.setEnabled(not self.gain_auto_check.isChecked())
            self.gain_minus_btn.setEnabled(not self.gain_auto_check.isChecked())
            self.gain_plus_btn.setEnabled(not self.gain_auto_check.isChecked())

            msg = "相机已打开"
            self.status_bar.showMessage(msg)
            self.status_message.emit(msg)
            log_info("相机已打开")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            log_error(f"打开相机失败: {e}")

    def close_camera(self):
        self.cam_mgr.close_camera()

        if not self.isVisible() and not self.isEnabled():
            return

        try:
            self.open_btn.setEnabled(True)
            self.close_btn.setEnabled(False)
            self.capture_btn.setEnabled(False)
            self.trigger_combo.setEnabled(False)
            self.trigger_btn.setEnabled(False)
            self.display_label.clear()
            self.display_label.setText("相机未打开")

            # 重置参数显示
            self.exp_value_label.setText("-- us")
            self.gain_value_label.setText("-- dB")
            self.fps_value_label.setText("-- fps")

            msg = "相机已关闭"
            self.status_bar.showMessage(msg)
            self.status_message.emit(msg)
            log_info("相机已关闭")
        except RuntimeError:
            pass

    # ========== 参数刷新 ==========

    def _refresh_params(self):
        """从相机读取当前参数并更新 UI"""
        if not self.cam_mgr.is_open:
            return

        # 曝光时间
        exp = self.cam_mgr.get_exposure_time()
        if exp is not None:
            self.exp_slider.blockSignals(True)
            # 映射到滑块范围（假设范围 0~100000us）
            slider_val = int(exp / 100.0) if exp < 100000 else 1000
            self.exp_slider.setValue(min(slider_val, 1000))
            self.exp_slider.blockSignals(False)
            self.exp_value_label.setText(f"{exp:.0f} us")

        # 增益
        gain = self.cam_mgr.get_gain()
        if gain is not None:
            self.gain_slider.blockSignals(True)
            slider_val = int(gain * 10)  # 0.1dB 精度
            self.gain_slider.setValue(min(slider_val, 240))
            self.gain_slider.blockSignals(False)
            self.gain_value_label.setText(f"{gain:.1f} dB")

        # 帧率
        fps = self.cam_mgr.get_frame_rate()
        if fps is not None:
            self.fps_slider.blockSignals(True)
            slider_val = int(fps * 10)  # 0.1fps 精度
            self.fps_slider.setValue(min(slider_val, 300))
            self.fps_slider.blockSignals(False)
            self.fps_value_label.setText(f"{fps:.1f} fps")

        # 触发模式
        self.trigger_combo.blockSignals(True)
        self.trigger_combo.setCurrentIndex(1 if self.cam_mgr.is_trigger_mode else 0)
        self.trigger_combo.blockSignals(False)
        self.trigger_btn.setEnabled(self.cam_mgr.is_trigger_mode)

    # ========== 触发模式 ==========

    def _on_trigger_mode_changed(self, index):
        if not self.cam_mgr.is_open:
            return
        enable = (index == 1)  # 1 = 触发模式
        self.cam_mgr.set_trigger_mode(enable)
        self.trigger_btn.setEnabled(enable)
        mode_str = "触发模式" if enable else "连续采集"
        self.status_bar.showMessage(f"已切换至: {mode_str}")
        self.status_message.emit(f"已切换至: {mode_str}")

    def _on_soft_trigger(self):
        if self.cam_mgr.is_trigger_mode:
            if self.cam_mgr.trigger_once():
                self.status_bar.showMessage("软触发信号已发送")
                self.status_message.emit("软触发信号已发送")
            else:
                self.status_bar.showMessage("软触发失败")
        else:
            self.status_bar.showMessage("当前为连续模式，无需触发")

    # ========== 曝光控制 ==========

    def _on_exp_slider_changed(self, value):
        if not self.cam_mgr.is_open:
            return
        # 滑块值 0~1000 映射到曝光时间
        exp_us = value * 100.0  # 0 ~ 100000 us
        if self.cam_mgr.set_exposure_time(exp_us):
            self.exp_value_label.setText(f"{exp_us:.0f} us")

    def _adjust_exposure(self, delta_us):
        if not self.cam_mgr.is_open:
            return
        current = self.cam_mgr.get_exposure_time()
        if current is None:
            return
        new_val = max(10.0, current + delta_us)
        if self.cam_mgr.set_exposure_time(new_val):
            self._refresh_params()
            self.status_bar.showMessage(f"曝光时间: {new_val:.0f} us")

    def _on_exp_auto_changed(self, state):
        if not self.cam_mgr.is_open:
            return
        if state == Qt.Checked:
            self.cam_mgr.set_enum_param("ExposureAuto", 1)  # 1 = 连续自动
            self.exp_slider.setEnabled(False)
            self.exp_minus_btn.setEnabled(False)
            self.exp_plus_btn.setEnabled(False)
            self.status_bar.showMessage("已开启自动曝光")
        else:
            self.cam_mgr.set_enum_param("ExposureAuto", 0)  # 0 = 关闭
            self.exp_slider.setEnabled(True)
            self.exp_minus_btn.setEnabled(True)
            self.exp_plus_btn.setEnabled(True)
            self.status_bar.showMessage("已关闭自动曝光")
            self._refresh_params()

    # ========== 增益控制 ==========

    def _on_gain_slider_changed(self, value):
        if not self.cam_mgr.is_open:
            return
        gain_db = value / 10.0  # 0.0 ~ 24.0 dB
        if self.cam_mgr.set_gain(gain_db):
            self.gain_value_label.setText(f"{gain_db:.1f} dB")

    def _adjust_gain(self, delta_db):
        if not self.cam_mgr.is_open:
            return
        current = self.cam_mgr.get_gain()
        if current is None:
            return
        new_val = max(0.0, current + delta_db)
        if self.cam_mgr.set_gain(new_val):
            self._refresh_params()
            self.status_bar.showMessage(f"增益: {new_val:.1f} dB")

    def _on_gain_auto_changed(self, state):
        if not self.cam_mgr.is_open:
            return
        if state == Qt.Checked:
            self.cam_mgr.set_enum_param("GainAuto", 1)
            self.gain_slider.setEnabled(False)
            self.gain_minus_btn.setEnabled(False)
            self.gain_plus_btn.setEnabled(False)
            self.status_bar.showMessage("已开启自动增益")
        else:
            self.cam_mgr.set_enum_param("GainAuto", 0)
            self.gain_slider.setEnabled(True)
            self.gain_minus_btn.setEnabled(True)
            self.gain_plus_btn.setEnabled(True)
            self.status_bar.showMessage("已关闭自动增益")
            self._refresh_params()

    # ========== 帧率控制 ==========

    def _on_fps_slider_changed(self, value):
        if not self.cam_mgr.is_open:
            return
        fps = value / 10.0  # 0.0 ~ 30.0 fps
        if fps > 0 and self.cam_mgr.set_frame_rate(fps):
            self.fps_value_label.setText(f"{fps:.1f} fps")

    def _adjust_frame_rate(self, delta_fps):
        if not self.cam_mgr.is_open:
            return
        current = self.cam_mgr.get_frame_rate()
        if current is None:
            return
        new_val = max(1.0, current + delta_fps)
        if self.cam_mgr.set_frame_rate(new_val):
            self._refresh_params()
            self.status_bar.showMessage(f"帧率: {new_val:.1f} fps")

    # ========== 帧回调与拍照 ==========

    def _on_frame_received(self, width, height, pixel_type, img_bytes):
        """实时帧回调"""
        self.frame_received.emit(width, height, pixel_type, img_bytes)
        CameraManager.display_on_label(self.display_label, width, height,
                                       pixel_type, img_bytes)

    def capture_once(self):
        """拍照"""
        if self._is_capturing:
            return

        self._is_capturing = True
        self.capture_btn.setEnabled(False)
        self.capture_btn.setText("拍照中...")
        self.status_bar.showMessage("拍照中...")
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
        self.capture_btn.setText("📷 拍照")

        if result is not None:
            width, height, pixel_type, img_bytes = result
            CameraManager.display_on_label(self.display_label, width, height,
                                           pixel_type, img_bytes)
            self.capture_completed.emit(width, height, pixel_type, img_bytes)
            msg = f"拍照完成: {width}x{height}"
            self.status_bar.showMessage(msg)
            self.status_message.emit(msg)
            log_info(msg)
        else:
            QMessageBox.warning(self, "拍照失败", "获取图像超时或失败，请重试")
            self.status_bar.showMessage("拍照失败")
            self.status_message.emit("拍照失败")
            log_error("拍照失败")

    # ========== 公共接口 ==========

    def is_camera_open(self) -> bool:
        return self.cam_mgr.is_open
