# -*- coding: utf-8 -*-
import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import cv2
import numpy as np
import json
from datetime import datetime

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QFont, QIcon

from camera_manager import CameraManager, raw_to_opencv
from core.config_manager import ConfigManager
from core.log_manager import log_info, log_error, log_warning
from vision.vision_engine import VisionEngine
from vision.pipeline import Pipeline

from .widgets.camera_panel import CameraPanel
from core.paths import SCHEME_DIR
from .widgets.pipeline_editor import PipelineEditor
from .widgets.result_panel import ResultPanel


class StepLogPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("执行日志")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #d4d4d4; padding: 2px 0;")

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1a1a1a; color: #c8c8c8;
                border: 1px solid #444; border-radius: 3px;
                font-family: Consolas, "Courier New", monospace;
                font-size: 15px; padding: 4px;
            }
        """)
        self.log_text.setMinimumHeight(120)

        layout.addWidget(title)
        layout.addWidget(self.log_text, 1)

    def append_log(self, timestamp: str, step_index: int, tool_name: str,
                   status: str, message: str, elapsed_ms: float):
        color = "#8bc34a" if status == "✓" else "#ff5252"
        line = (
            f'<span style="color:#888;">[{timestamp}]</span> '
            f'<span style="color:#4fc3f7;">步骤{step_index}:</span> '
            f'<span style="color:#e0e0e0;">{tool_name}</span> - '
            f'<span style="color:{color};">{status}</span> '
            f'<span style="color:#b0b0b0;">{message}</span> '
            f'<span style="color:#888;">({elapsed_ms:.1f}ms)</span>'
        )
        self.log_text.append(line)

    def append_info(self, text: str, color: str = "#888"):
        line = f'<span style="color:{color};">{text}</span>'
        self.log_text.append(line)

    def append_separator(self):
        self.log_text.append('<hr style="border: none; border-top: 1px solid #555;">')

    def clear_log(self):
        self.log_text.clear()


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.camera_mgr = CameraManager()
        self.vision_engine = VisionEngine()

        self._raw_image = None
        self._raw_width = 0
        self._raw_height = 0

        self._schemes = {}
        self._current_scheme_name = None

        self._setup_ui()
        self._load_schemes()
        self._auto_load_default_scheme()
        self._init_sdk()

    def _setup_ui(self):
        self.setWindowTitle("视觉检测系统")
        self.setMinimumSize(1400, 850)

        self._setup_menu_bar()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._setup_mode_toolbar(main_layout)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, 1)

        self._build_worker_page()

        self._build_engineer_page()

        self.stack.setCurrentIndex(0)

        self.status_label = QLabel("就绪")
        self.scheme_status_label = QLabel("当前方案: 未选择")
        self.scheme_status_label.setStyleSheet("color: #d4d4d4; font-weight: bold;")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.scheme_status_label)

    def _setup_mode_toolbar(self, parent_layout):
        toolbar = QWidget()
        toolbar.setStyleSheet("""
            background-color: #1e1e1e; border-bottom: 1px solid #444;
        """)
        toolbar.setFixedHeight(40)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(8)

        self.btn_worker_mode = QPushButton("🔧 工人模式")
        self.btn_worker_mode.setCheckable(True)
        self.btn_worker_mode.setChecked(True)
        self.btn_worker_mode.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4; padding: 4px 16px;
                border: 1px solid #555; border-radius: 3px; font-size: 16px;
                font-weight: bold;
            }
            QPushButton:checked {
                background-color: #1a3a5c; border: 1px solid #4A90D9;
                color: #4A90D9;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)

        self.btn_engineer_mode = QPushButton("⚙ 工程师模式")
        self.btn_engineer_mode.setCheckable(True)
        self.btn_engineer_mode.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4; padding: 4px 16px;
                border: 1px solid #555; border-radius: 3px; font-size: 16px;
                font-weight: bold;
            }
            QPushButton:checked {
                background-color: #3a2a1a; border: 1px solid #E65100;
                color: #E65100;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)

        layout.addWidget(self.btn_worker_mode)
        layout.addWidget(self.btn_engineer_mode)
        layout.addStretch()

        self.mode_scheme_label = QLabel("当前方案: 未选择")
        self.mode_scheme_label.setStyleSheet("color: #999; font-size: 15px;")

        layout.addWidget(self.mode_scheme_label)

        self.btn_worker_mode.clicked.connect(lambda: self._switch_mode(0))
        self.btn_engineer_mode.clicked.connect(lambda: self._switch_mode(1))

        parent_layout.addWidget(toolbar)

    def _switch_mode(self, index: int):
        self.stack.setCurrentIndex(index)
        self.btn_worker_mode.setChecked(index == 0)
        self.btn_engineer_mode.setChecked(index == 1)

        if index == 0:
            self.status_label.setText("工人模式")
        else:
            self.status_label.setText("工程师模式")

    def _build_worker_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px;")
        top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 4, 12, 4)

        self.worker_judge = QLabel("就绪")
        self.worker_judge.setAlignment(Qt.AlignCenter)
        self.worker_judge.setStyleSheet("""
            font-size: 26px; font-weight: bold; padding: 6px 28px;
            background-color: #1e1e1e; color: #666;
            border: 2px solid #444; border-radius: 6px;
            min-width: 160px;
        """)
        top_layout.addWidget(self.worker_judge)

        top_layout.addSpacing(20)

        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        self.worker_scheme_label = QLabel("当前方案: 未选择")
        self.worker_scheme_label.setStyleSheet("font-size: 18px; color: #d4d4d4; font-weight: bold;")
        self.worker_status_label = QLabel("就绪 - 请加载图像或拍照")
        self.worker_status_label.setStyleSheet("font-size: 16px; color: #999;")

        info_layout.addWidget(self.worker_scheme_label)
        info_layout.addWidget(self.worker_status_label)

        top_layout.addWidget(info_widget, 1)

        layout.addWidget(top_bar)

        middle_splitter = QSplitter(Qt.Horizontal)

        image_panel = QWidget()
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(4)

        image_title = QLabel("检测画面")
        image_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #d4d4d4; padding: 2px 0;")

        self.worker_display = QLabel()
        self.worker_display.setStyleSheet("""
            QLabel {
                background-color: #0d0d0d; border: 2px solid #444;
                border-radius: 4px;
            }
        """)
        self.worker_display.setMinimumSize(640, 480)
        self.worker_display.setAlignment(Qt.AlignCenter)
        self.worker_display.setText("请加载图像或拍照")

        image_layout.addWidget(image_title)
        image_layout.addWidget(self.worker_display, 1)

        right_panel = QWidget()
        right_panel.setMinimumWidth(320)
        right_panel.setMaximumWidth(400)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 6px; background: #2d2d2d; }
            QScrollBar::handle:vertical { background: #555; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 4, 0)
        scroll_layout.setSpacing(8)

        btn_group = QWidget()
        btn_group.setStyleSheet("background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px;")
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setContentsMargins(12, 12, 12, 12)
        btn_layout.setSpacing(10)

        self.worker_btn_capture = QPushButton("📷 拍照")
        self.worker_btn_capture.setMinimumHeight(56)
        self.worker_btn_capture.setEnabled(False)
        self.worker_btn_capture.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4; font-size: 20px;
                font-weight: bold; padding: 8px 16px;
                border: 2px solid #555; border-radius: 6px;
            }
            QPushButton:hover { background-color: #4a4a4a; border-color: #777; }
            QPushButton:disabled { background-color: #2d2d2d; color: #555; border-color: #3a3a3a; }
        """)

        self.worker_btn_load = QPushButton("🖼 导入图像")
        self.worker_btn_load.setMinimumHeight(48)
        self.worker_btn_load.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #b0b0b0; font-size: 17px;
                padding: 6px 16px; border: 1px solid #555; border-radius: 4px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)

        self.worker_btn_detect = QPushButton("▶ 开始检测")
        self.worker_btn_detect.setMinimumHeight(64)
        self.worker_btn_detect.setEnabled(False)
        self.worker_btn_detect.setStyleSheet("""
            QPushButton {
                background-color: #388E3C; color: #fff; font-size: 22px;
                font-weight: bold; padding: 8px 16px;
                border: 2px solid #4CAF50; border-radius: 8px;
            }
            QPushButton:hover { background-color: #2E7D32; border-color: #66BB6A; }
            QPushButton:disabled { background-color: #2d2d2d; color: #555; border-color: #3a3a3a; }
        """)

        btn_layout.addWidget(self.worker_btn_capture)
        btn_layout.addWidget(self.worker_btn_load)
        btn_layout.addWidget(self.worker_btn_detect)

        scheme_group = QWidget()
        scheme_group.setStyleSheet("background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px;")
        scheme_layout = QVBoxLayout(scheme_group)
        scheme_layout.setContentsMargins(12, 8, 12, 8)
        scheme_layout.setSpacing(6)

        scheme_title = QLabel("📂 方案选择")
        scheme_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #d4d4d4; border: none;")

        self.worker_scheme_list = QListWidget()
        self.worker_scheme_list.setStyleSheet("""
            QListWidget {
                background-color: #2d2d2d; color: #d4d4d4;
                border: 1px solid #444; border-radius: 3px;
                font-size: 15px; padding: 2px;
            }
            QListWidget::item {
                padding: 8px 10px; border-bottom: 1px solid #3a3a3a;
            }
            QListWidget::item:selected {
                background-color: #1a3a5c; color: #4A90D9;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
        """)
        self.worker_scheme_list.setMinimumHeight(120)
        self.worker_scheme_list.setMaximumHeight(180)

        self.worker_btn_import_scheme = QPushButton("📥 导入方案")
        self.worker_btn_import_scheme.setMinimumHeight(36)
        self.worker_btn_import_scheme.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #b0b0b0; font-size: 16px;
                padding: 4px 16px; border: 1px solid #555; border-radius: 4px;
            }
            QPushButton:hover { background-color: #4a4a4a; border-color: #777; }
        """)

        scheme_layout.addWidget(scheme_title)
        scheme_layout.addWidget(self.worker_scheme_list, 1)
        scheme_layout.addWidget(self.worker_btn_import_scheme)

        self.worker_log = StepLogPanel()

        scroll_layout.addWidget(btn_group)
        scroll_layout.addWidget(scheme_group)
        scroll_layout.addWidget(self.worker_log, 1)

        scroll.setWidget(scroll_content)
        right_layout.addWidget(scroll, 1)

        middle_splitter.addWidget(image_panel)
        middle_splitter.addWidget(right_panel)
        middle_splitter.setStretchFactor(0, 3)
        middle_splitter.setStretchFactor(1, 1)

        layout.addWidget(middle_splitter, 1)

        self.worker_btn_capture.clicked.connect(self._capture)
        self.worker_btn_load.clicked.connect(self._load_image)
        self.worker_btn_detect.clicked.connect(self._do_detect)
        self.worker_btn_import_scheme.clicked.connect(self._import_worker_scheme)

        self.stack.addWidget(page)

    def _refresh_worker_scheme_list(self):
        self.worker_scheme_list.clear()
        os.makedirs(SCHEME_DIR, exist_ok=True)
        for filename in sorted(os.listdir(SCHEME_DIR)):
            if filename.endswith(".json"):
                filepath = os.path.join(SCHEME_DIR, filename)
                name = os.path.splitext(filename)[0]
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, filepath)
                self.worker_scheme_list.addItem(item)

    def _import_worker_scheme(self):
        current_item = self.worker_scheme_list.currentItem()
        if current_item is None:
            QMessageBox.warning(self, "提示", "请先在列表中选择一个方案")
            return

        name = current_item.text()
        filepath = current_item.data(Qt.UserRole)

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            pipeline = Pipeline.from_dict(data)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载方案文件失败:\n{e}")
            log_error(f"工人模式导入方案失败: {e}")
            return

        self.vision_engine.set_pipeline(pipeline)

        self.worker_scheme_label.setText(f"当前方案: {name}")
        self.worker_status_label.setText(f"已导入方案: {name}")
        self.worker_status_label.setStyleSheet("font-size: 16px; color: #66BB6A;")
        self.worker_btn_detect.setEnabled(True)

        if name in self._schemes:
            self.eng_scheme_combo.setCurrentText(name)
        self._current_scheme_name = name
        self.scheme_status_label.setText(f"当前方案: {name}")
        self.mode_scheme_label.setText(f"当前方案: {name}")

        log_info(f"工人模式导入方案: {name}")
        QMessageBox.information(self, "成功", f"方案「{name}」已导入并应用")

    def _build_engineer_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        scheme_bar = QWidget()
        scheme_bar.setStyleSheet("background-color: #252525; border: 1px solid #444; border-radius: 3px;")
        scheme_bar_layout = QHBoxLayout(scheme_bar)
        scheme_bar_layout.setContentsMargins(8, 4, 8, 4)

        lbl_scheme = QLabel("方案:")
        lbl_scheme.setStyleSheet("color: #d4d4d4;")
        scheme_bar_layout.addWidget(lbl_scheme)
        self.eng_scheme_combo = QComboBox()
        self.eng_scheme_combo.setMinimumWidth(180)
        self.eng_scheme_combo.setEditable(True)
        self.eng_scheme_combo.setInsertPolicy(QComboBox.NoInsert)
        self.eng_scheme_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555;
                padding: 4px 8px; border-radius: 3px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #2d2d2d; color: #d4d4d4; selection-background-color: #1a3a5c;
            }
        """)
        self.eng_scheme_combo.currentTextChanged.connect(self._on_scheme_combo_changed)
        self.eng_scheme_combo.lineEdit().editingFinished.connect(self._on_scheme_rename)

        self.eng_btn_new = QPushButton("新建")
        self.eng_btn_save = QPushButton("保存")
        self.eng_btn_apply = QPushButton("应用")
        self.eng_btn_rename = QPushButton("重命名")
        self.eng_btn_delete = QPushButton("删除")

        for btn in [self.eng_btn_new, self.eng_btn_save, self.eng_btn_apply, self.eng_btn_rename, self.eng_btn_delete]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #3c3c3c; color: #d4d4d4; padding: 4px 12px;
                    border: 1px solid #555; border-radius: 3px; font-size: 15px;
                }
                QPushButton:hover { background-color: #4a4a4a; }
            """)

        self.eng_btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #1a3a5c; color: #4A90D9; padding: 4px 16px;
                border: 1px solid #2a5a8c; border-radius: 3px; font-size: 15px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2a4a7c; }
        """)

        scheme_bar_layout.addWidget(self.eng_scheme_combo)
        scheme_bar_layout.addWidget(self.eng_btn_new)
        scheme_bar_layout.addWidget(self.eng_btn_save)
        scheme_bar_layout.addWidget(self.eng_btn_apply)
        scheme_bar_layout.addWidget(self.eng_btn_rename)
        scheme_bar_layout.addWidget(self.eng_btn_delete)
        scheme_bar_layout.addStretch()

        eng_splitter = QSplitter(Qt.Horizontal)

        left_eng_panel = QWidget()
        left_eng_layout = QVBoxLayout(left_eng_panel)
        left_eng_layout.setContentsMargins(0, 0, 0, 0)
        left_eng_layout.setSpacing(6)

        test_group = QGroupBox("测试图像")
        test_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold; font-size: 16px; border: 1px solid #444;
                border-radius: 4px; margin-top: 10px; padding-top: 16px; color: #d4d4d4;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #d4d4d4; }
        """)
        test_layout = QVBoxLayout(test_group)
        test_layout.setContentsMargins(4, 8, 4, 4)
        test_layout.setSpacing(4)

        test_toolbar = QHBoxLayout()
        self.eng_btn_load_test = QPushButton("加载测试图像")
        self.eng_btn_load_test.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4; padding: 4px 12px;
                border: 1px solid #555; border-radius: 3px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
        """)
        self.eng_btn_run_preview = QPushButton("▶ 预览流水线")
        self.eng_btn_run_preview.setStyleSheet("""
            QPushButton {
                background-color: #1a3a5c; color: #4A90D9; padding: 4px 16px;
                border: 1px solid #2a5a8c; border-radius: 3px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2a4a7c; }
        """)
        test_toolbar.addWidget(self.eng_btn_load_test)
        test_toolbar.addWidget(self.eng_btn_run_preview)
        test_toolbar.addStretch()

        self.eng_test_display = QLabel()
        self.eng_test_display.setStyleSheet("""
            QLabel {
                background-color: #0d0d0d; border: 1px solid #444;
                border-radius: 4px;
            }
        """)
        self.eng_test_display.setMinimumSize(320, 240)
        self.eng_test_display.setAlignment(Qt.AlignCenter)
        self.eng_test_display.setText("点击「加载测试图像」选择图片")

        test_layout.addLayout(test_toolbar)
        test_layout.addWidget(self.eng_test_display, 1)

        self.eng_result_panel = ResultPanel()
        self.eng_result_panel.setMaximumHeight(220)

        left_eng_layout.addWidget(test_group, 3)
        left_eng_layout.addWidget(self.eng_result_panel, 1)

        right_eng_panel = QWidget()
        right_eng_layout = QVBoxLayout(right_eng_panel)
        right_eng_layout.setContentsMargins(8, 0, 0, 0)
        right_eng_layout.setSpacing(4)

        self.eng_log = StepLogPanel()
        self.eng_log.setMaximumHeight(100)

        self.pipeline_editor = PipelineEditor()

        right_eng_layout.addWidget(self.eng_log)
        right_eng_layout.addWidget(self.pipeline_editor, 1)

        eng_splitter.addWidget(left_eng_panel)
        eng_splitter.addWidget(right_eng_panel)
        eng_splitter.setStretchFactor(0, 2)
        eng_splitter.setStretchFactor(1, 3)

        layout.addWidget(scheme_bar)
        layout.addWidget(eng_splitter, 1)

        self.eng_btn_new.clicked.connect(self._new_scheme)
        self.eng_btn_save.clicked.connect(self._save_current_scheme)
        self.eng_btn_apply.clicked.connect(self._apply_selected_scheme)
        self.eng_btn_rename.clicked.connect(self._rename_scheme)
        self.eng_btn_delete.clicked.connect(self._delete_scheme)
        self.eng_btn_load_test.clicked.connect(self._load_test_image)
        self.eng_btn_run_preview.clicked.connect(self._run_preview)
        self.pipeline_editor.pipeline_changed.connect(self._on_editor_changed)

        self.stack.addWidget(page)

    def _setup_menu_bar(self):
        menubar = self.menuBar()

        device_menu = menubar.addMenu("设备")
        self.act_open_camera = QAction("打开相机", self)
        self.act_open_camera.triggered.connect(self._open_camera_dialog)
        self.act_close_camera = QAction("关闭相机", self)
        self.act_close_camera.setEnabled(False)
        self.act_close_camera.triggered.connect(self._close_camera)
        self.act_capture = QAction("拍照", self)
        self.act_capture.setShortcut(QKeySequence("F5"))
        self.act_capture.setEnabled(False)
        self.act_capture.triggered.connect(self._capture)
        self.act_load_image = QAction("导入图像", self)
        self.act_load_image.setShortcut(QKeySequence("Ctrl+O"))
        self.act_load_image.triggered.connect(self._load_image)

        device_menu.addAction(self.act_open_camera)
        device_menu.addAction(self.act_close_camera)
        device_menu.addSeparator()
        device_menu.addAction(self.act_capture)
        device_menu.addAction(self.act_load_image)

        scheme_menu = menubar.addMenu("方案")
        self.act_new_scheme = QAction("新建方案", self)
        self.act_new_scheme.triggered.connect(self._new_scheme)
        self.act_save_scheme = QAction("保存方案", self)
        self.act_save_scheme.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save_scheme.triggered.connect(self._save_current_scheme)
        self.act_apply_scheme = QAction("应用方案", self)
        self.act_apply_scheme.triggered.connect(self._apply_selected_scheme)
        scheme_menu.addAction(self.act_new_scheme)
        scheme_menu.addAction(self.act_save_scheme)
        scheme_menu.addAction(self.act_apply_scheme)
        scheme_menu.addSeparator()

        self.act_import_scheme = QAction("导入方案", self)
        self.act_import_scheme.triggered.connect(self._import_scheme)
        self.act_export_scheme = QAction("导出方案", self)
        self.act_export_scheme.triggered.connect(self._export_scheme)
        scheme_menu.addAction(self.act_import_scheme)
        scheme_menu.addAction(self.act_export_scheme)

        view_menu = menubar.addMenu("视图")
        self.act_switch_worker = QAction("工人模式", self)
        self.act_switch_worker.triggered.connect(lambda: self._switch_mode(0))
        self.act_switch_engineer = QAction("工程师模式", self)
        self.act_switch_engineer.triggered.connect(lambda: self._switch_mode(1))
        view_menu.addAction(self.act_switch_worker)
        view_menu.addAction(self.act_switch_engineer)

        help_menu = menubar.addMenu("帮助")
        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(self._show_about)
        help_menu.addAction(self.act_about)

    def _load_schemes(self):
        os.makedirs(SCHEME_DIR, exist_ok=True)
        self._schemes = {}
        self.eng_scheme_combo.clear()

        for filename in sorted(os.listdir(SCHEME_DIR)):
            if filename.endswith(".json"):
                filepath = os.path.join(SCHEME_DIR, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    pipeline = Pipeline.from_dict(data)
                    name = pipeline.name or os.path.splitext(filename)[0]
                    self._schemes[name] = (pipeline, filepath)
                    self.eng_scheme_combo.addItem(name)
                except Exception as e:
                    log_error(f"加载方案失败 {filename}: {e}")

        self._refresh_worker_scheme_list()

    def _auto_load_default_scheme(self):
        """启动时自动加载名为'默认方案'的方案"""
        default_name = "默认方案"
        if default_name in self._schemes:
            # 直接设置 combo box 选中项，触发 _on_scheme_combo_changed
            idx = self.eng_scheme_combo.findText(default_name)
            if idx >= 0:
                self.eng_scheme_combo.setCurrentIndex(idx)
            # 同时应用到引擎
            pipeline, _ = self._schemes[default_name]
            self.vision_engine.set_pipeline(pipeline)
            self._current_scheme_name = default_name
            self.scheme_status_label.setText(f"当前方案: {default_name}")
            self.worker_scheme_label.setText(f"当前方案: {default_name}")
            self.mode_scheme_label.setText(f"当前方案: {default_name}")
            self.status_label.setText(f"已自动加载方案: {default_name}")
            log_info(f"自动加载默认方案: {default_name}")

    def _on_scheme_combo_changed(self, name):
        if not name:
            return
        self._current_scheme_name = name
        pipeline, _ = self._schemes.get(name, (None, None))
        if pipeline is not None:
            self.pipeline_editor.set_pipeline(pipeline)
            self.scheme_status_label.setText(f"当前方案: {name}")
            self.worker_scheme_label.setText(f"当前方案: {name}")
            self.mode_scheme_label.setText(f"当前方案: {name}")

    def _apply_selected_scheme(self):
        if not self._current_scheme_name:
            QMessageBox.warning(self, "提示", "请先选择一个方案")
            return

        pipeline, _ = self._schemes.get(self._current_scheme_name, (None, None))
        if pipeline is None:
            QMessageBox.warning(self, "错误", "方案数据异常")
            return

        self.vision_engine.set_pipeline(pipeline)
        self.scheme_status_label.setText(f"当前方案: {self._current_scheme_name}")
        self.worker_scheme_label.setText(f"当前方案: {self._current_scheme_name}")
        self.mode_scheme_label.setText(f"当前方案: {self._current_scheme_name}")
        self.status_label.setText(f"已应用方案: {self._current_scheme_name}")
        log_info(f"应用方案: {self._current_scheme_name}")

    def _new_scheme(self):
        name, ok = QInputDialog.getText(self, "新建方案", "请输入方案名称:")
        if ok and name.strip():
            if name in self._schemes:
                QMessageBox.warning(self, "提示", "方案已存在")
                return
            pipeline = Pipeline(name=name.strip())
            self._schemes[name] = (pipeline, None)
            self.eng_scheme_combo.addItem(name)
            self.eng_scheme_combo.setCurrentText(name)
            self._current_scheme_name = name
            self.pipeline_editor.set_pipeline(pipeline)
            log_info(f"新建方案: {name}")
            self._refresh_worker_scheme_list()

    def _delete_scheme(self):
        if not self._current_scheme_name:
            QMessageBox.warning(self, "提示", "请先选择一个方案")
            return

        name = self._current_scheme_name
        reply = QMessageBox.question(self, "确认删除",
                                     f"确定删除方案 '{name}' 吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            pipeline, filepath = self._schemes.get(name, (None, None))
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
            del self._schemes[name]
            idx = self.eng_scheme_combo.findText(name)
            if idx >= 0:
                self.eng_scheme_combo.removeItem(idx)
            self._current_scheme_name = None
            log_info(f"删除方案: {name}")
            self._refresh_worker_scheme_list()

    def _rename_scheme(self):
        if not self._current_scheme_name:
            QMessageBox.warning(self, "提示", "请先选择一个方案")
            return

        old_name = self._current_scheme_name
        new_name, ok = QInputDialog.getText(self, "重命名方案", "请输入新名称:",
                                             text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            self._do_rename_scheme(old_name, new_name.strip())

    def _on_scheme_rename(self):
        if not self._current_scheme_name:
            return
        new_name = self.eng_scheme_combo.currentText().strip()
        if not new_name or new_name == self._current_scheme_name:
            self.eng_scheme_combo.blockSignals(True)
            self.eng_scheme_combo.setCurrentText(self._current_scheme_name)
            self.eng_scheme_combo.blockSignals(False)
            return
        self._do_rename_scheme(self._current_scheme_name, new_name)

    def _do_rename_scheme(self, old_name: str, new_name: str):
        if new_name in self._schemes and new_name != old_name:
            QMessageBox.warning(self, "提示", "方案名已存在")
            self.eng_scheme_combo.blockSignals(True)
            self.eng_scheme_combo.setCurrentText(old_name)
            self.eng_scheme_combo.blockSignals(False)
            return

        pipeline, filepath = self._schemes.pop(old_name)
        pipeline.name = new_name

        if filepath and os.path.exists(filepath):
            try:
                new_filepath = os.path.join(os.path.dirname(filepath), f"{new_name}.json")
                os.rename(filepath, new_filepath)
                filepath = new_filepath
            except Exception:
                pass

        self._schemes[new_name] = (pipeline, filepath)

        idx = self.eng_scheme_combo.findText(old_name)
        if idx >= 0:
            self.eng_scheme_combo.blockSignals(True)
            self.eng_scheme_combo.setItemText(idx, new_name)
            self.eng_scheme_combo.setCurrentText(new_name)
            self.eng_scheme_combo.blockSignals(False)

        self._current_scheme_name = new_name
        self.scheme_status_label.setText(f"当前方案: {new_name}")
        self.worker_scheme_label.setText(f"当前方案: {new_name}")
        self.mode_scheme_label.setText(f"当前方案: {new_name}")
        log_info(f"重命名方案: {old_name} -> {new_name}")
        self._refresh_worker_scheme_list()

    def _import_scheme(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入方案", "", "方案文件 (*.json)")
        if not filepath:
            return
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            pipeline = Pipeline.from_dict(data)
            name = pipeline.name or os.path.splitext(os.path.basename(filepath))[0]

            dest_path = os.path.join(SCHEME_DIR, f"{name}.json")
            with open(dest_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            existing_idx = self.eng_scheme_combo.findText(name)
            if existing_idx >= 0:
                self.eng_scheme_combo.removeItem(existing_idx)

            self._schemes[name] = (pipeline, dest_path)
            self.eng_scheme_combo.addItem(name)
            self.eng_scheme_combo.setCurrentText(name)
            QMessageBox.information(self, "成功", f"方案 '{name}' 导入成功")
            log_info(f"导入方案: {name}")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _export_scheme(self):
        if not self._current_scheme_name:
            QMessageBox.warning(self, "提示", "请先选择一个方案")
            return
        pipeline, _ = self._schemes.get(self._current_scheme_name, (None, None))
        if pipeline is None:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出方案", f"{self._current_scheme_name}.json", "方案文件 (*.json)")
        if not filepath:
            return
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(pipeline.to_dict(), f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "成功", f"方案已导出到: {filepath}")
            log_info(f"导出方案: {self._current_scheme_name}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _save_current_scheme(self):
        if not self._current_scheme_name:
            QMessageBox.warning(self, "提示", "请先选择一个方案")
            return

        pipeline = self.pipeline_editor.get_pipeline()
        pipeline.name = self._current_scheme_name
        filepath = self._schemes.get(self._current_scheme_name, (None, None))[1]
        self._schemes[self._current_scheme_name] = (pipeline, filepath)

        os.makedirs(SCHEME_DIR, exist_ok=True)
        if filepath is None:
            filepath = os.path.join(SCHEME_DIR, f"{self._current_scheme_name}.json")
            self._schemes[self._current_scheme_name] = (pipeline, filepath)

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(pipeline.to_dict(), f, indent=2, ensure_ascii=False)
            self.status_label.setText(f"方案已保存: {self._current_scheme_name}")
            log_info(f"保存方案: {self._current_scheme_name}")
            QMessageBox.information(self, "成功", f"方案 '{self._current_scheme_name}' 保存成功")
        except Exception as e:
            log_error(f"保存方案失败: {e}")
            QMessageBox.critical(self, "保存失败", str(e))

        self._refresh_worker_scheme_list()

    def _on_editor_changed(self):
        if self._current_scheme_name:
            pipeline = self.pipeline_editor.get_pipeline()
            filepath = self._schemes.get(self._current_scheme_name, (None, None))[1]
            self._schemes[self._current_scheme_name] = (pipeline, filepath)
            if self.vision_engine.pipeline is not None:
                self.vision_engine.set_pipeline(pipeline)

    def _init_sdk(self):
        try:
            CameraManager.initialize_sdk()
        except Exception as e:
            log_error(f"SDK初始化失败: {e}")

    def _open_camera_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("相机控制")
        dialog.setMinimumWidth(700)
        dialog.setMinimumHeight(550)

        layout = QVBoxLayout(dialog)
        self._camera_panel = CameraPanel()
        self._camera_panel.frame_received.connect(self._on_frame_received)
        self._camera_panel.capture_completed.connect(self._on_capture_completed)
        self._camera_panel.status_message.connect(self.statusBar().showMessage)
        layout.addWidget(self._camera_panel)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        self._camera_panel.enumerate_devices()
        dialog.exec_()

    def _close_camera(self):
        try:
            if hasattr(self, '_camera_panel') and self._camera_panel.is_camera_open():
                self._camera_panel.close_camera()
        except RuntimeError:
            # Qt 对象已被删除，忽略
            pass
        self.act_open_camera.setEnabled(True)
        self.act_close_camera.setEnabled(False)
        self.act_capture.setEnabled(False)
        self.worker_btn_capture.setEnabled(False)
        self.worker_btn_detect.setEnabled(False)
        self.worker_display.clear()
        self.worker_display.setText("相机已关闭")
        self._raw_image = None
        self.status_label.setText("相机已关闭")

    def _capture(self):
        if hasattr(self, '_camera_panel'):
            self._camera_panel.capture_once()

    def _load_image(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "导入图像", "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;所有文件 (*.*)")
        if not filepath:
            return
        try:
            img = cv2.imread(filepath)
            if img is None:
                QMessageBox.warning(self, "导入失败", f"无法读取图像: {filepath}")
                return
            self._raw_image = img
            self._raw_height, self._raw_width = img.shape[:2]
            self._show_cv_image(img)
            self.worker_btn_detect.setEnabled(True)
            self.worker_btn_capture.setEnabled(True)
            self.act_capture.setEnabled(True)
            self.status_label.setText(f"已导入图像: {os.path.basename(filepath)}")
            self.worker_status_label.setText(f"已导入图像: {os.path.basename(filepath)}")
            log_info(f"导入图像: {filepath} ({self._raw_width}x{self._raw_height})")
        except Exception as e:
            log_error(f"导入图像失败: {e}")
            QMessageBox.critical(self, "导入失败", str(e))

    def _on_frame_received(self, width, height, pixel_type, img_bytes):
        self._raw_width = width
        self._raw_height = height
        self._raw_image = self._convert_to_cv(width, height, pixel_type, img_bytes)
        if self._raw_image is not None:
            self._show_cv_image(self._raw_image)

    def _on_capture_completed(self, width, height, pixel_type, img_bytes):
        self._raw_width = width
        self._raw_height = height
        self._raw_image = self._convert_to_cv(width, height, pixel_type, img_bytes)
        self.worker_btn_detect.setEnabled(True)
        self.worker_btn_capture.setEnabled(True)
        self.act_capture.setEnabled(True)
        self.act_open_camera.setEnabled(False)
        self.act_close_camera.setEnabled(True)
        if self._raw_image is not None:
            self._show_cv_image(self._raw_image)
        self.status_label.setText("拍照完成，可开始检测")
        self.worker_status_label.setText("拍照完成，可开始检测")

    def _show_cv_image(self, cv_img):
        if cv_img is None:
            return
        try:
            if len(cv_img.shape) == 2:
                h, w = cv_img.shape
                q_img = QImage(cv_img.data, w, h, w, QImage.Format_Grayscale8)
            else:
                h, w, ch = cv_img.shape
                rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                q_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
            pix = QPixmap.fromImage(q_img)

            scaled_worker = pix.scaled(self.worker_display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.worker_display.setPixmap(scaled_worker)

            scaled_eng = pix.scaled(self.eng_test_display.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.eng_test_display.setPixmap(scaled_eng)
        except Exception as e:
            self.worker_display.setText(f"图像显示错误: {e}")

    def _convert_to_cv(self, width, height, pixel_type, img_bytes):
        """将相机原始帧数据转换为 OpenCV BGR 图像"""
        try:
            img = raw_to_opencv(img_bytes, width, height, pixel_type)
            if img is None:
                return np.zeros((height, width, 3), dtype=np.uint8)
            # 确保是 3 通道 BGR
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
            return img
        except Exception as e:
            log_error(f"图像转换失败: {e}")
            return np.zeros((height, width, 3), dtype=np.uint8)

    def _load_test_image(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "加载测试图像", "",
            "图像文件 (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;所有文件 (*.*)")
        if not filepath:
            return
        try:
            img = cv2.imread(filepath)
            if img is None:
                QMessageBox.warning(self, "加载失败", f"无法读取图像: {filepath}")
                return
            self._raw_image = img
            self._raw_height, self._raw_width = img.shape[:2]
            self._show_cv_image(img)
            self.worker_btn_detect.setEnabled(True)
            self.status_label.setText(f"已加载测试图像: {os.path.basename(filepath)}")
            self.worker_status_label.setText(f"已加载测试图像: {os.path.basename(filepath)}")
            log_info(f"加载测试图像: {filepath}")
        except Exception as e:
            log_error(f"加载测试图像失败: {e}")
            QMessageBox.critical(self, "加载失败", str(e))

    def _run_preview(self):
        if self._raw_image is None:
            QMessageBox.warning(self, "提示", "请先加载测试图像")
            return

        if self.vision_engine.pipeline is None:
            QMessageBox.warning(self, "提示", "请先选择并应用一个方案")
            return

        self.eng_btn_run_preview.setEnabled(False)
        self.eng_btn_run_preview.setText("执行中...")
        QApplication.processEvents()

        self.eng_log.clear_log()
        self.eng_log.append_info(f"══════ 流水线预览开始 ══════", "#4fc3f7")
        self.eng_log.append_info(f"方案: {self._current_scheme_name or '未命名'}", "#888")

        try:
            scheme_name = self._current_scheme_name or "未命名"
            passed, message, annotated = self.vision_engine.execute(
                self._raw_image, scheme_name=scheme_name
            )

            results = self.vision_engine.get_last_results()

            tool_results = None
            if results:
                total_ms = sum(r.elapsed_ms for r in results)
                tool_results = {
                    "total_elapsed_ms": total_ms,
                    "steps": [
                        {
                            "tool_name": r.tool_name or r.tool_type,
                            "status": "✓" if r.passed else "✗",
                            "elapsed_ms": r.elapsed_ms,
                            "message": r.message,
                        }
                        for r in results
                    ]
                }

            self.eng_result_panel.show_result(passed, message, annotated, tool_results)

            if annotated is not None:
                self._show_cv_image(annotated)

            for i, r in enumerate(results):
                ts = datetime.now().strftime("%H:%M:%S")
                status = "✓" if r.passed else "✗"
                self.eng_log.append_log(ts, i + 1, r.tool_type, status,
                                        r.message, r.elapsed_ms)

            self.eng_log.append_separator()
            total_ms = sum(r.elapsed_ms for r in results)
            if passed:
                self.eng_log.append_info(
                    f"✓ 检测通过 (OK) | 总耗时: {total_ms:.1f}ms", "#8bc34a")
            else:
                self.eng_log.append_info(
                    f"✗ 检测不通过 (NG) | 总耗时: {total_ms:.1f}ms", "#ff5252")

            status = "OK" if passed else "NG"
            self.status_label.setText(f"预览完成: {status}")
            log_info(f"预览完成: {status} | 方案={scheme_name}")

        except Exception as e:
            log_error(f"预览异常: {e}")
            self.eng_result_panel.show_result(False, f"预览异常: {str(e)}")
            self.eng_log.append_info(f"✗ 执行异常: {str(e)}", "#ff5252")
            self.status_label.setText("预览异常")
        finally:
            self.eng_btn_run_preview.setEnabled(True)
            self.eng_btn_run_preview.setText("▶ 预览流水线")

    def _do_detect(self):
        if self._raw_image is None:
            QMessageBox.warning(self, "提示", "请先拍照获取图像")
            return

        if self.vision_engine.pipeline is None:
            QMessageBox.warning(self, "提示", "请先选择并应用一个方案")
            return

        self.worker_btn_detect.setEnabled(False)
        self.worker_btn_detect.setText("检测中...")
        self.status_label.setText("检测中...")
        self.worker_status_label.setText("检测中...")
        QApplication.processEvents()

        self.worker_log.clear_log()
        self.worker_log.append_info(f"══════ 检测开始 ══════", "#4fc3f7")

        try:
            scheme_name = self._current_scheme_name or "未命名"
            passed, message, annotated = self.vision_engine.execute(
                self._raw_image, scheme_name=scheme_name
            )

            results = self.vision_engine.get_last_results()

            if passed:
                self.worker_judge.setText("✓ OK")
                self.worker_judge.setStyleSheet("""
                    font-size: 32px; font-weight: bold; padding: 6px 28px;
                    background-color: #E8F5E9; color: #2E7D32;
                    border: 2px solid #4CAF50; border-radius: 6px;
                    min-width: 160px;
                """)
                self.worker_status_label.setText("检测通过 (OK)")
            else:
                self.worker_judge.setText("✗ NG")
                self.worker_judge.setStyleSheet("""
                    font-size: 32px; font-weight: bold; padding: 6px 28px;
                    background-color: #FFEBEE; color: #C62828;
                    border: 2px solid #EF5350; border-radius: 6px;
                    min-width: 160px;
                """)
                self.worker_status_label.setText("检测不通过 (NG)")

            if annotated is not None:
                self._show_cv_image(annotated)

            for i, r in enumerate(results):
                ts = datetime.now().strftime("%H:%M:%S")
                status = "✓" if r.passed else "✗"
                self.worker_log.append_log(ts, i + 1, r.tool_type, status,
                                           r.message, r.elapsed_ms)

            self.worker_log.append_separator()
            total_ms = sum(r.elapsed_ms for r in results)
            if passed:
                self.worker_log.append_info(
                    f"✓ 检测通过 (OK) | 总耗时: {total_ms:.1f}ms", "#8bc34a")
            else:
                self.worker_log.append_info(
                    f"✗ 检测不通过 (NG) | 总耗时: {total_ms:.1f}ms", "#ff5252")

            status = "OK" if passed else "NG"
            self.status_label.setText(f"检测完成: {status}")
            log_info(f"检测完成: {status} | 方案={scheme_name}")

        except Exception as e:
            log_error(f"检测异常: {e}")
            self.worker_judge.setText("✗ 异常")
            self.worker_judge.setStyleSheet("""
                font-size: 32px; font-weight: bold; padding: 6px 28px;
                background-color: #FFEBEE; color: #C62828;
                border: 2px solid #EF5350; border-radius: 6px;
                min-width: 160px;
            """)
            self.worker_log.append_info(f"✗ 执行异常: {str(e)}", "#ff5252")
            self.status_label.setText("检测异常")
            self.worker_status_label.setText("检测异常")
        finally:
            self.worker_btn_detect.setEnabled(True)
            self.worker_btn_detect.setText("▶ 开始检测")

    def _show_about(self):
        QMessageBox.about(self, "关于",
                          "<h3>视觉检测系统</h3>"
                          "<p>版本: 2.0</p>"
                          "<p>基于 OpenCV + PyQt5 的视觉识别系统</p>"
                          "<p>支持流水线式视觉工具链设计</p>")

    def closeEvent(self, event):
        log_info("系统关闭")
        try:
            if hasattr(self, '_camera_panel'):
                self._camera_panel.close_camera()
        except RuntimeError:
            # Qt 对象已被删除，忽略
            pass
        CameraManager.finalize_sdk()
        event.accept()
