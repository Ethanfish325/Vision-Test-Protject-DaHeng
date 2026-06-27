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
from typing import Optional

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QPixmap, QImage, QKeySequence, QFont, QIcon

from camera_manager import CameraManager, raw_to_opencv
from .widgets.zoomable_label import ZoomableLabel, ZoomableImageWidget
from core.config_manager import ConfigManager
from core.log_manager import log_info, log_error, log_warning, LogManager
from vision.vision_engine import VisionEngine
from vision.pipeline import Pipeline

from .widgets.camera_panel import CameraPanel
from core.paths import SCHEME_DIR
from .widgets.pipeline_editor import PipelineEditor
from .widgets.result_panel import ResultPanel

from core.serial_comm import SerialCommManager
from core.serial_test_workflow import SerialTestWorkflow, WorkflowConfig
from core.nmc_sdk import NMCSDK

import hashlib
from core.paths import USERS_FILE


def _verify_password(input_password: str, stored_hash: str) -> bool:
    """验证密码：对输入密码进行 SHA256 哈希，与存储的哈希值比对"""
    return hashlib.sha256(input_password.encode('utf-8')).hexdigest() == stored_hash


def _load_users() -> dict:
    """加载 users.json 中的用户数据"""
    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


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


class DetectWorker(QThread):
    """后台检测工作线程，避免阻塞UI"""
    finished = pyqtSignal(bool, str, np.ndarray, object)  # passed, message, annotated, results

    def __init__(self, vision_engine, raw_image, scheme_name):
        super().__init__()
        self._vision_engine = vision_engine
        self._raw_image = raw_image
        self._scheme_name = scheme_name

    def run(self):
        try:
            passed, message, annotated = self._vision_engine.execute(
                self._raw_image, scheme_name=self._scheme_name
            )
            results = self._vision_engine.get_last_results()
            self.finished.emit(passed, message, annotated, results)
        except Exception as e:
            self.finished.emit(False, f"检测异常: {str(e)}", self._raw_image, [])


class EngineerTestWorker(QThread):
    """后台工程师测试工作线程，避免阻塞UI"""
    finished = pyqtSignal(bool, str, np.ndarray, object)  # passed, message, annotated, results

    def __init__(self, vision_engine, raw_image, scheme_name):
        super().__init__()
        self._vision_engine = vision_engine
        self._raw_image = raw_image
        self._scheme_name = scheme_name

    def run(self):
        try:
            passed, message, annotated = self._vision_engine.execute(
                self._raw_image, scheme_name=self._scheme_name
            )
            results = self._vision_engine.get_last_results()
            self.finished.emit(passed, message, annotated, results)
        except Exception as e:
            self.finished.emit(False, f"测试异常: {str(e)}", self._raw_image, [])


class WorkflowTestWorker(QThread):
    """后台工作流测试工作线程，避免阻塞UI"""
    finished = pyqtSignal(bool, str, np.ndarray, object)  # passed, message, annotated, results

    def __init__(self, vision_engine, image, scheme_name):
        super().__init__()
        self._vision_engine = vision_engine
        self._image = image
        self._scheme_name = scheme_name

    def run(self):
        try:
            passed, message, annotated = self._vision_engine.execute(
                self._image, scheme_name=self._scheme_name
            )
            results = self._vision_engine.get_last_results()
            self.finished.emit(passed, message, annotated, results)
        except Exception as e:
            self.finished.emit(False, f"自动测试异常: {str(e)}", self._image, [])


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.camera_mgr = CameraManager()
        self.vision_engine = VisionEngine()
        self._detect_worker = None  # 后台检测线程
        self._eng_test_worker = None  # 后台工程师测试线程
        self._workflow_test_worker = None  # 后台工作流测试线程

        self._raw_image = None
        self._raw_width = 0
        self._raw_height = 0

        self._schemes = {}
        self._current_scheme_name = None

        # 步骤导航相关
        self._step_results = []       # List[ToolResult]，流水线各步骤结果
        self._current_step_index = -1  # -1 表示显示最终标注结果
        self._annotated_image = None   # 最终标注结果图（原始图 + 所有 overlay 叠加）

        self._camera_panel = None      # 相机面板，延迟创建
        self._pending_engineer_test = False  # 设计模式测试标记：拍照后自动执行流水线
        self._pending_detect = False    # 生产模式标记：拍照后自动执行检测

        # 生产模式最近一次检测的标注结果，用于实时预览时保持显示检测结果
        self._last_annotated = None

        # 用户角色与权限控制
        self._current_user_role = "engineer"   # 当前用户角色: operator / engineer / admin
        self._current_user_name = "工程师"      # 当前用户显示名称
        '''
        # 用户角色与权限控制
        self._current_user_role = "operator"   # 当前用户角色: operator / engineer / admin
        self._current_user_name = "操作员"      # 当前用户显示名称
        '''
        # 串口通信与自动测试
        self._serial_comm: Optional[SerialCommManager] = None
        self._serial_workflow: Optional[SerialTestWorkflow] = None

        # 运动控制卡
        self._nmc_sdk: Optional[NMCSDK] = None

        self._setup_ui()
        self._load_schemes()
        self._auto_load_default_scheme()
        self._init_sdk()

        # 启动后延迟自动连接相机（等待 UI 完全渲染）
        QTimer.singleShot(500, self._auto_connect_camera)

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

        self.btn_worker_mode = QPushButton("🔧 生产模式")
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

        self.btn_engineer_mode = QPushButton("⚙ 设计模式")
        self.btn_engineer_mode.setCheckable(True)
        self.btn_engineer_mode.setEnabled(True)  # 默认操作员模式，禁用设计模式
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
            QPushButton:disabled {
                background-color: #252525; color: #555555;
                border: 1px solid #3a3a3a;
            }
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
        # 如果尝试切换到设计模式但当前用户不是工程师/管理员，阻止切换
        if index == 1 and self._current_user_role not in ("engineer", "admin"):
            QMessageBox.warning(self, "权限不足", "请先通过「用户」菜单登录工程师账号")
            self.btn_worker_mode.setChecked(True)
            self.btn_engineer_mode.setChecked(False)
            return

        self.stack.setCurrentIndex(index)
        self.btn_worker_mode.setChecked(index == 0)
        self.btn_engineer_mode.setChecked(index == 1)

        if index == 0:
            self.status_label.setText("生产模式")
        else:
            self.status_label.setText("设计模式")

    # ──────────────── 用户登录 / 权限控制 ────────────────

    def _show_login_dialog(self):
        """弹出登录对话框，选择角色并输入密码"""
        dialog = QDialog(self)
        dialog.setWindowTitle("登录")
        dialog.setFixedSize(360, 220)
        dialog.setStyleSheet("""
            QDialog { background-color: #2d2d2d; }
            QLabel { color: #d4d4d4; font-size: 14px; }
            QComboBox, QLineEdit {
                background-color: #3c3c3c; color: #d4d4d4;
                border: 1px solid #555; border-radius: 3px;
                padding: 6px 10px; font-size: 14px;
            }
            QPushButton {
                background-color: #1a3a5c; color: #4A90D9;
                border: 1px solid #2a5a8c; border-radius: 3px;
                padding: 8px 24px; font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #2a4a7c; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 角色选择
        role_layout = QHBoxLayout()
        role_layout.addWidget(QLabel("登录为："))
        role_combo = QComboBox()
        role_combo.addItem("工程师", "engineer")
        role_combo.addItem("管理员", "admin")
        role_layout.addWidget(role_combo, 1)
        layout.addLayout(role_layout)

        # 密码输入
        pwd_layout = QHBoxLayout()
        pwd_layout.addWidget(QLabel("密  码："))
        pwd_input = QLineEdit()
        pwd_input.setEchoMode(QLineEdit.Password)
        pwd_layout.addWidget(pwd_input, 1)
        layout.addLayout(pwd_layout)

        # 错误提示
        error_label = QLabel("")
        error_label.setStyleSheet("color: #ff5252; font-size: 12px;")
        error_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(error_label)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_login = QPushButton("登录")
        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet("""
            QPushButton { background-color: #3c3c3c; color: #d4d4d4;
                           border: 1px solid #555; }
            QPushButton:hover { background-color: #4a4a4a; }
        """)
        btn_layout.addWidget(btn_login)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        def _do_login():
            role_key = role_combo.currentData()
            password = pwd_input.text()
            if not password:
                error_label.setText("请输入密码")
                return

            users = _load_users()
            user_info = users.get(role_key)
            if user_info and _verify_password(password, user_info["password_hash"]):
                self._set_user_role(role_key, user_info["display_name"])
                dialog.accept()
            else:
                error_label.setText("密码错误，请重试")
                pwd_input.clear()
                pwd_input.setFocus()

        pwd_input.returnPressed.connect(_do_login)
        btn_login.clicked.connect(_do_login)
        btn_cancel.clicked.connect(dialog.reject)

        dialog.exec_()

    def _set_user_role(self, role: str, display_name: str):
        """设置当前用户角色，更新 UI 状态"""
        self._current_user_role = role
        self._current_user_name = display_name

        # 更新菜单显示
        self.act_current_user.setText(f"当前用户：{display_name}")

        # 工程师或管理员可以访问设计模式
        is_engineer = role in ("engineer", "admin")
        self.btn_engineer_mode.setEnabled(is_engineer)
        self.act_logout.setEnabled(is_engineer)

        # 如果当前在设计模式但角色不是工程师，自动切回生产模式
        if not is_engineer and self.stack.currentIndex() == 1:
            self._switch_mode(0)

        log_info(f"用户切换: {display_name}({role})")

    def _logout(self):
        """退出登录，回到操作员模式"""
        self._set_user_role("operator", "操作员")
        self.status_label.setText("生产模式")

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

        # 总测试时间显示
        self.worker_time_label = QLabel("")
        self.worker_time_label.setAlignment(Qt.AlignCenter)
        self.worker_time_label.setStyleSheet("""
            font-size: 18px; font-weight: bold; color: #4fc3f7;
            background-color: #1e1e1e; border: 1px solid #444;
            border-radius: 4px; padding: 4px 12px;
            min-width: 100px;
        """)
        top_layout.addWidget(self.worker_time_label)

        top_layout.addSpacing(20)

        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        self.worker_scheme_label = QLabel("当前方案: 未选择")
        self.worker_scheme_label.setStyleSheet("font-size: 18px; color: #d4d4d4; font-weight: bold;")
        self.worker_status_label = QLabel("就绪 - 请加载图像或点击「开始检测」")
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

        self.worker_display = ZoomableImageWidget("请加载图像或点击「开始检测」")
        self.worker_display.setMinimumSize(640, 480)
        self.worker_display.label.setStyleSheet("""
            ZoomableLabel {
                background-color: #0d0d0d; border: 2px solid #444;
                border-radius: 4px;
            }
        """)

        image_layout.addWidget(image_title)
        image_layout.addWidget(self.worker_display, 1)

        right_panel = QWidget()
        right_panel.setMinimumWidth(240)
        right_panel.setMaximumWidth(280)
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

        self.worker_btn_detect = QPushButton("📷 开始检测")
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

        btn_layout.addWidget(self.worker_btn_detect)

        # ── 串口自动测试按钮 ──
        self.worker_btn_auto_test = QPushButton("🔌 启动自动测试")
        self.worker_btn_auto_test.setMinimumHeight(48)
        self.worker_btn_auto_test.setEnabled(False)
        self.worker_btn_auto_test.setCheckable(True)
        self.worker_btn_auto_test.setStyleSheet("""
            QPushButton {
                background-color: #E65100; color: #fff; font-size: 18px;
                font-weight: bold; padding: 6px 16px;
                border: 2px solid #FF6D00; border-radius: 8px;
            }
            QPushButton:hover { background-color: #BF360C; border-color: #FF9100; }
            QPushButton:disabled { background-color: #2d2d2d; color: #555; border-color: #3a3a3a; }
            QPushButton:checked {
                background-color: #C62828; color: #fff;
                border: 2px solid #EF5350;
            }
        """)
        self.worker_btn_auto_test.setToolTip("通过串口接收下位机信号自动触发拍照检测")
        btn_layout.addWidget(self.worker_btn_auto_test)

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
        middle_splitter.setStretchFactor(0, 4)
        middle_splitter.setStretchFactor(1, 1)

        layout.addWidget(middle_splitter, 1)

        self.worker_btn_detect.clicked.connect(self._do_detect)
        self.worker_btn_import_scheme.clicked.connect(self._import_worker_scheme)
        self.worker_btn_auto_test.clicked.connect(self._toggle_auto_test)

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
            log_error(f"生产模式导入方案失败: {e}")
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

        log_info(f"生产模式导入方案: {name}")
        QMessageBox.information(self, "成功", f"方案「{name}」已导入并应用")
        self._update_auto_test_btn_state()

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
        self.eng_btn_run_preview = QPushButton("📷 测试")
        self.eng_btn_run_preview.setStyleSheet("""
            QPushButton {
                background-color: #1a3a5c; color: #4A90D9; padding: 4px 16px;
                border: 1px solid #2a5a8c; border-radius: 3px; font-weight: bold;
                font-size: 16px;
            }
            QPushButton:hover { background-color: #2a4a7c; }
        """)
        test_toolbar.addWidget(self.eng_btn_run_preview)

        # 设计模式总测试时间显示
        self.eng_time_label = QLabel("")
        self.eng_time_label.setAlignment(Qt.AlignCenter)
        self.eng_time_label.setStyleSheet("""
            font-size: 16px; font-weight: bold; color: #4fc3f7;
            background-color: #1e1e1e; border: 1px solid #444;
            border-radius: 4px; padding: 2px 10px;
            min-width: 80px;
        """)
        test_toolbar.addWidget(self.eng_time_label)

        test_toolbar.addStretch()

        # 步骤导航栏
        step_nav_bar = QWidget()
        step_nav_bar.setStyleSheet("background-color: #252525; border: 1px solid #444; border-radius: 3px;")
        step_nav_layout = QHBoxLayout(step_nav_bar)
        step_nav_layout.setContentsMargins(6, 2, 6, 2)
        step_nav_layout.setSpacing(6)

        self.eng_btn_prev_step = QPushButton("◀ 上一步")
        self.eng_btn_prev_step.setEnabled(False)
        self.eng_btn_prev_step.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4; padding: 3px 10px;
                border: 1px solid #555; border-radius: 3px; font-size: 13px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:disabled { background-color: #2d2d2d; color: #555; border-color: #3a3a3a; }
        """)

        self.eng_step_label = QLabel("最终结果")
        self.eng_step_label.setAlignment(Qt.AlignCenter)
        self.eng_step_label.setStyleSheet("""
            font-size: 14px; font-weight: bold; color: #4A90D9;
            padding: 3px 8px; min-width: 120px;
        """)

        self.eng_btn_next_step = QPushButton("下一步 ▶")
        self.eng_btn_next_step.setEnabled(False)
        self.eng_btn_next_step.setStyleSheet("""
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4; padding: 3px 10px;
                border: 1px solid #555; border-radius: 3px; font-size: 13px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton:disabled { background-color: #2d2d2d; color: #555; border-color: #3a3a3a; }
        """)

        step_nav_layout.addWidget(self.eng_btn_prev_step)
        step_nav_layout.addWidget(self.eng_step_label, 1)
        step_nav_layout.addWidget(self.eng_btn_next_step)

        self.eng_test_display = ZoomableImageWidget("点击「测试」按钮拍照并执行流水线")
        self.eng_test_display.setMinimumSize(320, 240)
        self.eng_test_display.label.setStyleSheet("""
            ZoomableLabel {
                background-color: #0d0d0d; border: 1px solid #444;
                border-radius: 4px;
            }
        """)

        test_layout.addLayout(test_toolbar)
        test_layout.addWidget(step_nav_bar)
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
        eng_splitter.setStretchFactor(0, 3)
        eng_splitter.setStretchFactor(1, 2)

        layout.addWidget(scheme_bar)
        layout.addWidget(eng_splitter, 1)

        self.eng_btn_new.clicked.connect(self._new_scheme)
        self.eng_btn_save.clicked.connect(self._save_current_scheme)
        self.eng_btn_apply.clicked.connect(self._apply_selected_scheme)
        self.eng_btn_rename.clicked.connect(self._rename_scheme)
        self.eng_btn_delete.clicked.connect(self._delete_scheme)
        self.eng_btn_run_preview.clicked.connect(self._run_preview)
        self.eng_btn_prev_step.clicked.connect(self._on_prev_step)
        self.eng_btn_next_step.clicked.connect(self._on_next_step)
        self.pipeline_editor.pipeline_changed.connect(self._on_editor_changed)

        self.stack.addWidget(page)

    def _setup_menu_bar(self):
        menubar = self.menuBar()

        device_menu = menubar.addMenu("设备")
        self.act_open_camera = QAction("相机设置", self)
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

        comm_menu = menubar.addMenu("通信")
        self.act_serial_comm = QAction("串口通信", self)
        self.act_serial_comm.triggered.connect(self._open_serial_dialog)
        comm_menu.addAction(self.act_serial_comm)
        self.act_nmc_control = QAction("运动控制", self)
        self.act_nmc_control.triggered.connect(self._open_nmc_dialog)
        comm_menu.addAction(self.act_nmc_control)

        # ── 用户菜单 ──
        user_menu = menubar.addMenu("用户")
        self.act_current_user = QAction("当前用户：工程师", self)
        self.act_current_user.setEnabled(True)
        self.act_switch_user = QAction("切换用户...", self)
        self.act_switch_user.triggered.connect(self._show_login_dialog)
        self.act_logout = QAction("退出登录", self)
        self.act_logout.setEnabled(True)
        self.act_logout.triggered.connect(self._logout)
        user_menu.addAction(self.act_current_user)
        user_menu.addSeparator()
        user_menu.addAction(self.act_switch_user)
        user_menu.addAction(self.act_logout)

        sys_menu = menubar.addMenu("系统")
        self.act_log_settings = QAction("日志限额设置", self)
        self.act_log_settings.triggered.connect(self._show_log_settings)
        sys_menu.addAction(self.act_log_settings)

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

    def _auto_connect_camera(self):
        """启动时自动搜索并连接相机"""
        self.status_label.setText("正在自动连接相机...")
        log_info("启动自动连接相机...")

        # 创建一个临时的 CameraPanel 用于自动连接，共享 CameraManager 实例
        self._camera_panel = CameraPanel(camera_mgr=self.camera_mgr)
        self._camera_panel.frame_received.connect(self._on_frame_received)
        self._camera_panel.capture_completed.connect(self._on_capture_completed)
        self._camera_panel.status_message.connect(self._on_camera_status_message)

        # 自动枚举并连接
        self._camera_panel.auto_connect_camera()

    def _on_camera_status_message(self, message):
        """相机状态消息回调"""
        self.status_label.setText(message)
        # 如果相机已打开，更新 UI 状态
        if self._camera_panel is not None and self._camera_panel.is_camera_open():
            self.act_open_camera.setEnabled(False)
            self.act_close_camera.setEnabled(True)
            self.act_capture.setEnabled(True)
            self.status_label.setText("相机已自动连接 - " + message)
            log_info("相机自动连接成功")

    def _open_camera_dialog(self):
        # 如果相机已打开，仍然打开设置对话框以允许用户调节参数
        if self._camera_panel is not None and self._camera_panel.is_camera_open():
            dialog = QDialog(self)
            dialog.setWindowTitle("相机设置 - 参数调节")
            dialog.setMinimumWidth(700)
            dialog.setMinimumHeight(550)

            layout = QVBoxLayout(dialog)
            # 创建新的 CameraPanel 共享 camera_mgr，用于参数调节界面
            # 不重新连接 frame_received/capture_completed 信号，避免干扰主界面取流
            settings_panel = CameraPanel(camera_mgr=self.camera_mgr)
            settings_panel.status_message.connect(self._on_camera_status_message)
            layout.addWidget(settings_panel)

            # 更新 settings_panel 的 UI 状态以反映相机已打开
            settings_panel.open_btn.setEnabled(False)
            settings_panel.close_btn.setEnabled(True)
            settings_panel.capture_btn.setEnabled(True)
            settings_panel.trigger_combo.setEnabled(True)
            settings_panel.trigger_btn.setEnabled(self.camera_mgr.is_trigger_mode)
            # 刷新参数显示
            settings_panel._refresh_params()

            btn_close = QPushButton("关闭")
            btn_close.clicked.connect(dialog.accept)
            layout.addWidget(btn_close)

            dialog.exec_()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("相机控制")
        dialog.setMinimumWidth(700)
        dialog.setMinimumHeight(550)

        layout = QVBoxLayout(dialog)
        # 创建一个临时面板用于对话框，不赋值给 self._camera_panel
        # 避免 dialog 关闭后 Qt 自动销毁该面板导致 self._camera_panel 悬空
        panel = CameraPanel(camera_mgr=self.camera_mgr)
        panel.frame_received.connect(self._on_frame_received)
        panel.capture_completed.connect(self._on_capture_completed)
        panel.status_message.connect(self._on_camera_status_message)
        layout.addWidget(panel)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        panel.enumerate_devices()
        dialog.exec_()

    def _close_camera(self):
        try:
            if self._camera_panel is not None and self._camera_panel.is_camera_open():
                self._camera_panel.close_camera()
        except (RuntimeError, AttributeError):
            # Qt 对象已被删除，忽略
            pass
        self.act_open_camera.setEnabled(True)
        self.act_close_camera.setEnabled(False)
        self.act_capture.setEnabled(False)
        self.worker_btn_detect.setEnabled(False)
        self.worker_display.clear_pixmap()
        self.worker_display.label.setText("相机已关闭")
        self._raw_image = None
        self.status_label.setText("相机已关闭")

    def _capture(self):
        if self._camera_panel is not None:
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
            # 导入新图像，清除上一次的检测标注结果
            self._last_annotated = None
            display_img = self._overlay_roi_on_image(img)
            self._show_worker_image(display_img)
            self.worker_btn_detect.setEnabled(True)
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
            # 如果有最近一次检测的标注结果，优先显示它（保持检测结果可见）
            if self._last_annotated is not None:
                self._show_worker_image(self._last_annotated)
            else:
                # 实时预览时，如果已设置流水线，在原始图像上叠加 ROI 框
                display_img = self._overlay_roi_on_image(self._raw_image)
                self._show_worker_image(display_img)

    def _on_capture_completed(self, width, height, pixel_type, img_bytes):
        self._raw_width = width
        self._raw_height = height
        self._raw_image = self._convert_to_cv(width, height, pixel_type, img_bytes)
        # 新拍照，清除上一次的检测标注结果
        self._last_annotated = None
        self.worker_btn_detect.setEnabled(True)
        self.act_capture.setEnabled(True)
        self.act_open_camera.setEnabled(False)
        self.act_close_camera.setEnabled(True)
        if self._raw_image is not None:
            # 拍照完成后，如果已设置流水线，在原始图像上叠加 ROI 框
            display_img = self._overlay_roi_on_image(self._raw_image)
            self._show_worker_image(display_img)
        self.status_label.setText("拍照完成，可开始检测")
        self.worker_status_label.setText("拍照完成，可开始检测")

        # 串口自动测试工作流模式：将图像传递给工作流
        if (self._serial_workflow is not None
                and self._serial_workflow.is_running):
            self._serial_workflow.on_capture_completed(self._raw_image)
            return

        # 设计模式测试：拍照后自动执行流水线
        if self._pending_engineer_test:
            self._pending_engineer_test = False
            self._show_engineer_image(self._raw_image)
            self._execute_engineer_test()

        # 生产模式：拍照后自动执行检测
        if self._pending_detect:
            self._pending_detect = False
            self._do_detect()

    def _overlay_roi_on_image(self, cv_img: np.ndarray) -> np.ndarray:
        """在图像上叠加流水线中 MultiROI 工具定义的 ROI 区域框（绿色边框）。

        用于生产模式实时预览时，让操作员看到检测区域的位置。
        如果未设置流水线或没有 MultiROI 工具，则返回原始图像的副本。
        """
        if cv_img is None:
            return cv_img
        pipeline = self.vision_engine.pipeline
        if pipeline is None:
            return cv_img.copy()

        result_img = cv_img.copy()
        h_img, w_img = result_img.shape[:2]

        for step in pipeline.steps:
            if not step.enabled:
                continue
            tool_type = type(step.tool).__name__
            if tool_type == "MultiROI":
                raw_regions = step.tool.params.get("regions", [])
                use_pct = step.tool.params.get("use_percentage", False)

                for r in raw_regions:
                    if isinstance(r, dict) and r.get("enabled", True):
                        name = r.get("name", "未命名")
                        if use_pct:
                            x = int(r.get("x", 0) / 100.0 * w_img)
                            y = int(r.get("y", 0) / 100.0 * h_img)
                            w = int(r.get("width", r.get("w", 100)) / 100.0 * w_img)
                            h = int(r.get("height", r.get("h", 100)) / 100.0 * h_img)
                        else:
                            x = r.get("x", 0)
                            y = r.get("y", 0)
                            w = r.get("width", r.get("w", 100))
                            h = r.get("height", r.get("h", 100))

                        # 绘制绿色 ROI 框（预览时统一绿色，无检测结果）
                        cv2.rectangle(result_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
                        cv2.putText(result_img, name, (x, y - 5),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        return result_img

    def _cv_to_pixmap(self, cv_img) -> QPixmap:
        """将 OpenCV 图像转换为 QPixmap"""
        if len(cv_img.shape) == 2:
            h, w = cv_img.shape
            q_img = QImage(cv_img.data, w, h, w, QImage.Format_Grayscale8)
        else:
            h, w, ch = cv_img.shape
            rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
            q_img = QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
        return QPixmap.fromImage(q_img)

    def _show_cv_image(self, cv_img):
        """通用图像显示（同时更新 Worker 和 Engineer 显示区）"""
        if cv_img is None:
            return
        try:
            pix = self._cv_to_pixmap(cv_img)
            self.worker_display.update_pixmap(pix)
            self.eng_test_display.update_pixmap(pix)
        except Exception as e:
            self.worker_display.label.setText(f"图像显示错误: {e}")

    def _show_worker_image(self, cv_img):
        """Worker 模式：显示原始图像 + 标注叠加（仅更新 worker_display）"""
        if cv_img is None:
            return
        try:
            pix = self._cv_to_pixmap(cv_img)
            self.worker_display.update_pixmap(pix)
        except Exception as e:
            self.worker_display.label.setText(f"图像显示错误: {e}")

    def _show_engineer_image(self, cv_img):
        """Engineer 模式：显示原始图像 + 标注叠加（仅更新 eng_test_display）"""
        if cv_img is None:
            return
        try:
            pix = self._cv_to_pixmap(cv_img)
            self.eng_test_display.update_pixmap(pix)
        except Exception as e:
            self.eng_test_display.label.setText(f"图像显示错误: {e}")

    # ────────── 步骤导航 ──────────

    def _update_step_nav_buttons(self):
        """根据当前步骤索引更新导航按钮状态和标签"""
        total = len(self._step_results)
        if total == 0:
            self.eng_btn_prev_step.setEnabled(False)
            self.eng_btn_next_step.setEnabled(False)
            self.eng_step_label.setText("最终结果")
            return

        idx = self._current_step_index
        if idx < 0:
            # 显示最终标注结果
            self.eng_step_label.setText(f"最终结果 ({total} 步)")
            self.eng_btn_prev_step.setEnabled(total > 0)
            self.eng_btn_next_step.setEnabled(total > 0)
        else:
            r = self._step_results[idx]
            name = r.tool_name or r.tool_type or f"步骤{idx+1}"
            status = "✓" if r.passed else "✗"
            self.eng_step_label.setText(f"步骤{idx+1}: {name} {status}")
            self.eng_btn_prev_step.setEnabled(idx > 0)
            self.eng_btn_next_step.setEnabled(idx < total - 1)

    def _show_step_image(self, index: int):
        """显示指定步骤的图像：index=-1 显示最终标注结果，否则显示该步骤的 processed_image"""
        if index < 0:
            # 显示最终标注结果（原始图 + 所有 overlay 叠加）
            if self._annotated_image is not None:
                self._show_engineer_image(self._annotated_image)
            elif self._raw_image is not None:
                self._show_engineer_image(self._raw_image)
        elif 0 <= index < len(self._step_results):
            r = self._step_results[index]
            if r.processed_image is not None:
                self._show_engineer_image(r.processed_image)
            elif self._raw_image is not None:
                self._show_engineer_image(self._raw_image)

    def _on_prev_step(self):
        """上一步"""
        if self._current_step_index < 0:
            # 当前显示最终结果，跳到最后一步
            self._current_step_index = len(self._step_results) - 1
        else:
            self._current_step_index -= 1
        self._show_step_image(self._current_step_index)
        self._update_step_nav_buttons()

    def _on_next_step(self):
        """下一步"""
        total = len(self._step_results)
        if self._current_step_index < 0:
            # 从最终结果跳到第一步
            self._current_step_index = 0
        elif self._current_step_index < total - 1:
            self._current_step_index += 1
        else:
            # 已到最后一步，回到最终结果
            self._current_step_index = -1
        self._show_step_image(self._current_step_index)
        self._update_step_nav_buttons()

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

    def _run_preview(self):
        if self.vision_engine.pipeline is None:
            QMessageBox.warning(self, "提示", "请先选择并应用一个方案")
            return

        # 如果没有图像，先拍照
        if self._raw_image is None:
            if self._camera_panel is None or not self._camera_panel.is_camera_open():
                QMessageBox.warning(self, "提示", "请先打开相机")
                return
            self._pending_engineer_test = True
            self.eng_btn_run_preview.setEnabled(False)
            self.eng_btn_run_preview.setText("拍照中...")
            self.status_label.setText("正在拍照...")
            QApplication.processEvents()
            self._capture()
            return

        self._execute_engineer_test()

    def _execute_engineer_test(self):
        """执行设计模式流水线测试（内部方法，_raw_image 必须非空）"""
        # 如果已有测试线程在运行，不重复启动
        if self._eng_test_worker is not None and self._eng_test_worker.isRunning():
            return

        self.eng_btn_run_preview.setEnabled(False)
        self.eng_btn_run_preview.setText("执行中...")

        self.eng_log.clear_log()
        self.eng_time_label.setText("")
        self.eng_result_panel.clear()
        self.eng_log.append_info(f"══════ 流水线测试开始 ══════", "#4fc3f7")
        self.eng_log.append_info(f"方案: {self._current_scheme_name or '未命名'}", "#888")

        # 在后台线程执行检测，避免阻塞UI
        scheme_name = self._current_scheme_name or "未命名"
        self._eng_test_worker = EngineerTestWorker(
            self.vision_engine, self._raw_image.copy(), scheme_name
        )
        self._eng_test_worker.finished.connect(self._on_engineer_test_finished)
        self._eng_test_worker.start()

    def _on_engineer_test_finished(self, passed, message, annotated, results):
        """工程师测试完成回调（主线程执行，安全更新UI）"""
        try:
            # 存储步骤结果用于导航
            self._step_results = list(results) if results else []
            self._annotated_image = annotated
            self._current_step_index = -1  # 默认显示最终结果

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

            self.eng_result_panel.show_result(passed, message, tool_results=tool_results)

            # 显示最终标注结果并更新导航按钮
            if annotated is not None:
                self._show_engineer_image(annotated)
            self._update_step_nav_buttons()

            for i, r in enumerate(results):
                ts = datetime.now().strftime("%H:%M:%S")
                status = "✓" if r.passed else "✗"
                self.eng_log.append_log(ts, i + 1, r.tool_type, status,
                                        r.message, r.elapsed_ms)

            self.eng_log.append_separator()
            total_ms = sum(r.elapsed_ms for r in results)
            # 更新设计模式总测试时间显示
            self.eng_time_label.setText(f"⏱ {total_ms:.0f}ms")
            if passed:
                self.eng_log.append_info(
                    f"✓ 检测通过 (OK) | 总耗时: {total_ms:.1f}ms", "#8bc34a")
            else:
                self.eng_log.append_info(
                    f"✗ 检测不通过 (NG) | 总耗时: {total_ms:.1f}ms", "#ff5252")

            status = "OK" if passed else "NG"
            self.status_label.setText(f"测试完成: {status}")
            log_info(f"工程师测试完成: {status} | 方案={self._current_scheme_name or '未命名'}")

        except Exception as e:
            log_error(f"测试结果处理异常: {e}")
            self.eng_result_panel.show_result(False, f"测试异常: {str(e)}")
            self.eng_log.append_info(f"✗ 执行异常: {str(e)}", "#ff5252")
            self.status_label.setText("测试异常")
        finally:
            self.eng_btn_run_preview.setEnabled(True)
            self.eng_btn_run_preview.setText("📷 测试")
            self._eng_test_worker = None

    def _do_detect(self):
        # 如果没有图像，先自动拍照
        if self._raw_image is None:
            if self._camera_panel is None or not self._camera_panel.is_camera_open():
                QMessageBox.warning(self, "提示", "请先打开相机")
                return
            self.status_label.setText("正在拍照...")
            self.worker_status_label.setText("正在拍照...")
            self.worker_btn_detect.setEnabled(False)
            self.worker_btn_detect.setText("拍照中...")
            self._camera_panel.capture_once()
            # 拍照完成后 _on_capture_completed 会再次调用 _do_detect
            self._pending_detect = True
            return

        if self.vision_engine.pipeline is None:
            QMessageBox.warning(self, "提示", "请先选择并应用一个方案")
            return

        # 如果已有检测线程在运行，不重复启动
        if self._detect_worker is not None and self._detect_worker.isRunning():
            return

        self.worker_btn_detect.setEnabled(False)
        self.worker_btn_detect.setText("检测中...")
        self.status_label.setText("检测中...")
        self.worker_status_label.setText("检测中...")

        self.worker_log.clear_log()
        self.worker_time_label.setText("")
        self.worker_log.append_info(f"══════ 检测开始 ══════", "#4fc3f7")

        # 在后台线程执行检测，避免阻塞UI
        scheme_name = self._current_scheme_name or "未命名"
        self._detect_worker = DetectWorker(
            self.vision_engine, self._raw_image.copy(), scheme_name
        )
        self._detect_worker.finished.connect(self._on_detect_finished)
        self._detect_worker.start()

    def _on_detect_finished(self, passed, message, annotated, results):
        """检测完成回调（主线程执行，安全更新UI）"""
        try:
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
                self._last_annotated = annotated
                self._show_worker_image(annotated)

            for i, r in enumerate(results):
                ts = datetime.now().strftime("%H:%M:%S")
                status = "✓" if r.passed else "✗"
                self.worker_log.append_log(ts, i + 1, r.tool_type, status,
                                           r.message, r.elapsed_ms)

            self.worker_log.append_separator()
            total_ms = sum(r.elapsed_ms for r in results)
            self.worker_time_label.setText(f"⏱ {total_ms:.0f}ms")
            if passed:
                self.worker_log.append_info(
                    f"✓ 检测通过 (OK) | 总耗时: {total_ms:.1f}ms", "#8bc34a")
            else:
                self.worker_log.append_info(
                    f"✗ 检测不通过 (NG) | 总耗时: {total_ms:.1f}ms", "#ff5252")

            status = "OK" if passed else "NG"
            self.status_label.setText(f"检测完成: {status}")
            log_info(f"检测完成: {status} | 方案={self._current_scheme_name or '未命名'}")

        except Exception as e:
            log_error(f"检测结果处理异常: {e}")
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
            self.worker_btn_detect.setText("📷 开始检测")
            # 清除原始图像，确保下次点击"开始检测"时重新拍照
            self._raw_image = None
            self._raw_width = 0
            self._raw_height = 0
            self._detect_worker = None

    def _show_log_settings(self):
        """打开日志限额设置对话框"""
        from core.paths import LOGS_DIR, ERRORS_DIR
        from core.log_manager import _get_dir_size, _CLEANUP_DIRS

        dialog = QDialog(self)
        dialog.setWindowTitle("存储空间限额设置")
        dialog.setMinimumWidth(480)
        dialog.setStyleSheet("""
            QDialog { background-color: #2d2d2d; }
            QLabel { color: #d4d4d4; font-size: 14px; }
            QSpinBox, QDoubleSpinBox {
                background-color: #3c3c3c; color: #d4d4d4;
                border: 1px solid #555; border-radius: 3px;
                padding: 4px 8px; font-size: 14px;
            }
            QPushButton {
                background-color: #3c3c3c; color: #d4d4d4;
                padding: 6px 20px; border: 1px solid #555;
                border-radius: 3px; font-size: 14px;
            }
            QPushButton:hover { background-color: #4a4a4a; }
            QPushButton#btn_apply {
                background-color: #1a3a5c; color: #4A90D9;
                border: 1px solid #2a5a8c; font-weight: bold;
            }
            QPushButton#btn_apply:hover { background-color: #2a4a7c; }
            QPushButton#btn_cleanup {
                background-color: #E65100; color: #fff;
                border: 1px solid #FF6D00; font-weight: bold;
            }
            QPushButton#btn_cleanup:hover { background-color: #BF360C; }
        """)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        # 计算 logs + errors 总大小
        def _calc_total_size():
            total = 0
            for d in _CLEANUP_DIRS:
                total += _get_dir_size(d)
            return total

        try:
            current_size = _calc_total_size()
            size_gb = current_size / (1024 ** 3)
            size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{current_size / (1024 ** 2):.1f} MB"
        except Exception:
            size_str = "未知"

        # 分别显示 logs 和 errors 的大小
        try:
            logs_size = _get_dir_size(LOGS_DIR)
            errs_size = _get_dir_size(ERRORS_DIR)
            logs_str = f"{logs_size / (1024**3):.2f} GB" if logs_size >= 1024**3 else f"{logs_size / (1024**2):.1f} MB"
            errs_str = f"{errs_size / (1024**3):.2f} GB" if errs_size >= 1024**3 else f"{errs_size / (1024**2):.1f} MB"
            detail_str = f"   ├ 日志(logs): {logs_str}\n   └ 错误数据(errors): {errs_str}"
        except Exception:
            detail_str = ""

        size_label = QLabel(f"📂 当前数据大小: {size_str}")
        size_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #4fc3f7;")
        layout.addWidget(size_label)

        detail_label = QLabel(detail_str)
        detail_label.setStyleSheet("color: #999; font-size: 13px; padding-left: 8px;")
        layout.addWidget(detail_label)

        # 日志限额设置
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        form_layout.setLabelAlignment(Qt.AlignRight)

        max_size_spin = QDoubleSpinBox(dialog)
        max_size_spin.setRange(1, 9999)
        max_size_spin.setDecimals(1)
        max_size_spin.setSuffix(" GB")
        max_size_spin.setValue(self.config.get('system.log_max_size_gb', 50))
        max_size_spin.setToolTip("当 logs + errors 总大小超过此限额时自动清理")
        form_layout.addRow("最大限额:", max_size_spin)

        ratio_spin = QDoubleSpinBox(dialog)
        ratio_spin.setRange(0.1, 0.9)
        ratio_spin.setDecimals(1)
        ratio_spin.setSingleStep(0.1)
        ratio_spin.setSuffix(" (× 最大限额)")
        ratio_spin.setValue(self.config.get('system.log_cleanup_ratio', 0.5))
        ratio_spin.setToolTip("超出限额后清理到 最大限额 × 此比例")
        form_layout.addRow("清理目标比例:", ratio_spin)

        layout.addLayout(form_layout)

        # 说明文字
        hint = QLabel(
            "💡 当 logs + errors 总大小超过「最大限额」时，系统会自动\n"
            "   从最早的文件开始删除，直到总大小降到「最大限额 × 比例」以下。\n"
            "   ⚠ 注意：仅清理 logs 和 errors 目录下的文件，不影响方案配置。\n"
            f"   当前设置: 超过 {max_size_spin.value():.0f}GB 时清理到 {max_size_spin.value() * ratio_spin.value():.0f}GB"
        )
        hint.setStyleSheet("color: #999; font-size: 13px; padding: 8px; "
                           "background-color: #252525; border-radius: 4px;")
        layout.addWidget(hint)

        # 更新提示文字
        def _update_hint():
            max_val = max_size_spin.value()
            ratio_val = ratio_spin.value()
            hint.setText(
                "💡 当 logs + errors 总大小超过「最大限额」时，系统会自动\n"
                "   从最早的文件开始删除，直到总大小降到「最大限额 × 比例」以下。\n"
                "   ⚠ 注意：仅清理 logs 和 errors 目录下的文件，不影响方案配置。\n"
                f"   当前设置: 超过 {max_val:.0f}GB 时清理到 {max_val * ratio_val:.0f}GB"
            )
        max_size_spin.valueChanged.connect(_update_hint)
        ratio_spin.valueChanged.connect(_update_hint)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cleanup = QPushButton("🗑 立即清理")
        btn_cleanup.setObjectName("btn_cleanup")
        btn_cleanup.setToolTip("立即按当前设置执行一次清理（删除 logs 和 errors 中最旧的文件）")
        btn_cleanup.clicked.connect(lambda: self._do_manual_cleanup(dialog))
        btn_layout.addWidget(btn_cleanup)

        btn_layout.addStretch()

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_cancel)

        btn_apply = QPushButton("✓ 应用")
        btn_apply.setObjectName("btn_apply")
        btn_apply.clicked.connect(lambda: self._save_log_settings(
            dialog, max_size_spin.value(), ratio_spin.value()))
        btn_layout.addWidget(btn_apply)

        layout.addLayout(btn_layout)

        dialog.exec_()

    def _save_log_settings(self, dialog: QDialog, max_size_gb: float, cleanup_ratio: float):
        """保存日志限额设置"""
        self.config.set('system.log_max_size_gb', max_size_gb)
        self.config.set('system.log_cleanup_ratio', cleanup_ratio)
        self.config.save()
        log_info(f"存储限额设置已更新: 最大={max_size_gb}GB, 清理比例={cleanup_ratio}")
        QMessageBox.information(dialog, "成功", "存储限额设置已保存")
        dialog.accept()

    def _do_manual_cleanup(self, parent: QWidget):
        """立即执行一次清理（清理 logs + errors 中最旧的文件）"""
        from core.log_manager import _get_dir_size, _CLEANUP_DIRS
        max_size_gb = self.config.get('system.log_max_size_gb', 50)
        cleanup_ratio = self.config.get('system.log_cleanup_ratio', 0.5)
        max_size = int(max_size_gb * 1024 ** 3)
        LogManager.cleanup_now(max_size=max_size, cleanup_ratio=cleanup_ratio)
        log_info(f"手动触发存储清理: 最大={max_size_gb}GB, 比例={cleanup_ratio}")

        # 刷新大小显示
        try:
            total = 0
            for d in _CLEANUP_DIRS:
                total += _get_dir_size(d)
            size_gb = total / (1024 ** 3)
            size_str = f"{size_gb:.2f} GB" if size_gb >= 1 else f"{total / (1024 ** 2):.1f} MB"
        except Exception:
            size_str = "未知"

        QMessageBox.information(parent, "清理完成", f"清理完成\n当前 logs + errors 总大小: {size_str}")

    def _show_about(self):
        QMessageBox.about(self, "关于",
                          "<h3>视觉检测系统</h3>"
                          "<p>版本: 2.0</p>"
                          "<p>基于 OpenCV + PyQt5 的视觉识别系统</p>"
                          "<p>支持流水线式视觉工具链设计</p>")

    def _open_serial_dialog(self):
        """打开串口通信窗口（共享 SerialCommManager 实例）。"""
        from .widgets.serial_dialog import SerialDialog
        if self._serial_comm is None:
            self._serial_comm = SerialCommManager()
        dialog = SerialDialog(self, comm_mgr=self._serial_comm)
        dialog.exec_()
        # 对话框关闭后，根据串口状态更新自动测试按钮
        self._update_auto_test_btn_state()

    def _open_nmc_dialog(self):
        """打开运动控制卡窗口（共享 NMCSDK 实例）。"""
        from .widgets.nmc_control_dialog import NMCControlDialog
        if self._nmc_sdk is None:
            self._nmc_sdk = NMCSDK()
        dialog = NMCControlDialog(self, nmc_sdk=self._nmc_sdk)
        dialog.exec_()

    # ──────────────────────────────────────────────
    # 串口自动测试工作流
    # ──────────────────────────────────────────────

    def _update_auto_test_btn_state(self):
        """根据串口和方案状态更新自动测试按钮。"""
        comm_ok = (self._serial_comm is not None and self._serial_comm.is_open)
        pipeline_ok = (self.vision_engine.pipeline is not None)
        workflow_running = (self._serial_workflow is not None
                            and self._serial_workflow.is_running)

        if workflow_running:
            self.worker_btn_auto_test.setEnabled(True)
        else:
            self.worker_btn_auto_test.setEnabled(comm_ok and pipeline_ok)

    def _toggle_auto_test(self, checked: bool):
        """切换自动测试状态。"""
        if checked:
            self._start_auto_test()
        else:
            self._stop_auto_test()

    def _start_auto_test(self):
        """启动串口自动测试工作流。"""
        # 检查串口
        if self._serial_comm is None or not self._serial_comm.is_open:
            QMessageBox.warning(self, "提示",
                                "请先通过「通信 > 串口通信」打开串口连接")
            self.worker_btn_auto_test.setChecked(False)
            return

        # 检查方案
        if self.vision_engine.pipeline is None:
            QMessageBox.warning(self, "提示", "请先导入检测方案")
            self.worker_btn_auto_test.setChecked(False)
            return

        # 创建并启动工作流
        self._serial_workflow = SerialTestWorkflow(
            comm_mgr=self._serial_comm,
            config=WorkflowConfig(),
            parent=self,
        )

        # 连接信号
        self._serial_workflow.state_changed.connect(
            self._on_workflow_state_changed)
        self._serial_workflow.capture_requested.connect(
            self._on_workflow_capture_requested)
        self._serial_workflow.test_requested.connect(
            self._on_workflow_test_requested)
        self._serial_workflow.error_occurred.connect(
            self._on_workflow_error)

        # 启动
        self._serial_workflow.start()

        # 更新 UI
        self.worker_btn_auto_test.setText("⏹ 停止自动测试")
        self.worker_btn_detect.setEnabled(False)
        self.status_label.setText("自动测试已启动 - 等待触发信号...")
        self.worker_status_label.setText("自动测试已启动 - 等待触发信号...")
        log_info("串口自动测试工作流已启动")

    def _stop_auto_test(self):
        """停止串口自动测试工作流。"""
        if self._serial_workflow:
            self._serial_workflow.stop()
            self._serial_workflow.cleanup()
            self._serial_workflow = None

        self.worker_btn_auto_test.setText("🔌 启动自动测试")
        self.worker_btn_auto_test.setChecked(False)
        self.worker_btn_detect.setEnabled(
            self._raw_image is not None
            and self.vision_engine.pipeline is not None
        )
        self.status_label.setText("自动测试已停止")
        self.worker_status_label.setText("自动测试已停止")
        log_info("串口自动测试工作流已停止")

    def _on_workflow_state_changed(self, state):
        """工作流状态变化时更新 UI。"""
        state_names = {
            SerialTestWorkflow.State.IDLE: "空闲",
            SerialTestWorkflow.State.WAITING_TRIGGER: "等待触发信号...",
            SerialTestWorkflow.State.CAPTURING: "拍照中...",
            SerialTestWorkflow.State.TESTING: "检测中...",
            SerialTestWorkflow.State.SENDING_RESULT: "发送结果...",
        }
        name = state_names.get(state, str(state))
        self.worker_status_label.setText(f"自动测试: {name}")
        self.status_label.setText(f"自动测试: {name}")

    def _on_workflow_capture_requested(self):
        """工作流请求拍照。"""
        if self._camera_panel is not None and self._camera_panel.is_camera_open():
            self._capture()
        else:
            self._serial_workflow.on_capture_completed(None)

    def _on_workflow_test_requested(self, image):
        """工作流请求执行检测。"""
        if self.vision_engine.pipeline is None:
            self._serial_workflow.on_test_completed(False, "未设置检测方案")
            return

        # 如果已有工作流测试线程在运行，不重复启动
        if self._workflow_test_worker is not None and self._workflow_test_worker.isRunning():
            return

        scheme_name = self._current_scheme_name or "未命名"
        self._workflow_test_worker = WorkflowTestWorker(
            self.vision_engine, image.copy(), scheme_name
        )
        self._workflow_test_worker.finished.connect(self._on_workflow_test_finished)
        self._workflow_test_worker.start()

    def _on_workflow_test_finished(self, passed, message, annotated, results):
        """工作流测试完成回调（主线程执行，安全更新UI）"""
        try:
            # 更新显示
            if annotated is not None:
                self._last_annotated = annotated
                self._show_worker_image(annotated)

            # 更新 OK/NG 判断
            if passed:
                self.worker_judge.setText("✓ OK")
                self.worker_judge.setStyleSheet("""
                    font-size: 32px; font-weight: bold; padding: 6px 28px;
                    background-color: #E8F5E9; color: #2E7D32;
                    border: 2px solid #4CAF50; border-radius: 6px;
                    min-width: 160px;
                """)
            else:
                self.worker_judge.setText("✗ NG")
                self.worker_judge.setStyleSheet("""
                    font-size: 32px; font-weight: bold; padding: 6px 28px;
                    background-color: #FFEBEE; color: #C62828;
                    border: 2px solid #EF5350; border-radius: 6px;
                    min-width: 160px;
                """)

            # 记录日志
            self.worker_log.clear_log()
            self.worker_time_label.setText("")
            self.worker_log.append_info(
                f"══════ 自动测试触发 #{self._serial_workflow.trigger_count} ══════",
                "#4fc3f7")
            for i, r in enumerate(results):
                ts = datetime.now().strftime("%H:%M:%S")
                status = "✓" if r.passed else "✗"
                self.worker_log.append_log(
                    ts, i + 1, r.tool_type, status,
                    r.message, r.elapsed_ms)
            self.worker_log.append_separator()
            total_ms = sum(r.elapsed_ms for r in results)
            # 更新总测试时间显示
            self.worker_time_label.setText(f"⏱ {total_ms:.0f}ms")
            if passed:
                self.worker_log.append_info(
                    f"✓ 检测通过 (OK) | 总耗时: {total_ms:.1f}ms", "#8bc34a")
            else:
                self.worker_log.append_info(
                    f"✗ 检测不通过 (NG) | 总耗时: {total_ms:.1f}ms", "#ff5252")

            # 回调工作流
            self._serial_workflow.on_test_completed(passed, message)

        except Exception as e:
            log_error(f"自动测试结果处理异常: {e}")
            self._serial_workflow.on_test_completed(False, str(e))
        finally:
            self._workflow_test_worker = None

    def _on_workflow_error(self, error_msg: str):
        """工作流错误处理。"""
        self.worker_status_label.setText(f"自动测试错误: {error_msg}")
        self.status_label.setText(f"自动测试错误: {error_msg}")
        log_error(f"自动测试错误: {error_msg}")

    def closeEvent(self, event):
        log_info("系统关闭")
        # 停止自动测试工作流
        if self._serial_workflow is not None:
            self._serial_workflow.stop()
            self._serial_workflow.cleanup()
            self._serial_workflow = None
        # 关闭串口
        if self._serial_comm is not None:
            self._serial_comm.cleanup()
            self._serial_comm = None
        # 关闭运动控制卡
        if self._nmc_sdk is not None:
            try:
                if self._nmc_sdk._connected:
                    self._nmc_sdk.close_net()
            except Exception:
                pass
            self._nmc_sdk = None
        try:
            if self._camera_panel is not None:
                self._camera_panel.close_camera()
        except (RuntimeError, AttributeError):
            # Qt 对象已被删除，忽略
            pass
        CameraManager.finalize_sdk()
        event.accept()
