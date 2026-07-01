# -*- coding: utf-8 -*-
"""
自动化检测工作流模块
=================
实现由 DI 信号触发的多位置自动化检测工作流。

工作流状态机:
    IDLE -> MONITORING -> MOVING -> CAPTURING -> TESTING
    -> (循环: MOVING -> CAPTURING -> TESTING 直到所有位置完成)
    -> RETURNING -> SHOW_RESULT -> MONITORING

依赖:
    - NMC SDK: 运动控制和 DI 读取
    - CameraManager: 相机拍照
    - VisionEngine: 视觉检测

使用方式:
    workflow = InspectionWorkflow(nmc_sdk, camera_mgr, vision_engine)
    workflow.load_product(product_config)
    workflow.state_changed.connect(on_state_changed)
    workflow.start_monitoring()
    # ... 工作流自动运行 ...
    workflow.stop_monitoring()
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field

import numpy as np

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from core.nmc_sdk import NMCSDK, Axis_Stop_IMD, Axis_Stop_DEC, Position_Absolute, Position_Opposite, Profile_S
from core.log_manager import log_info, log_error, log_warning


# ============================================================================
# 配置
# ============================================================================

@dataclass
class WorkflowConfig:
    """工作流配置"""
    di_bit: int = 3                    # DI 输入位号
    poll_interval_ms: int = 50         # DI 轮询间隔（毫秒）
    axis: int = 1                      # 运动轴号
    v_max: float = 50000.0             # 最大速度
    a_max: float = 100000.0            # 加速度
    origin_position: int = 0           # 原点位置
    move_timeout_ms: int = 10000       # 运动超时（毫秒）
    arrive_check_interval_ms: int = 50 # 到位检测轮询间隔


# ============================================================================
# 位置检测结果
# ============================================================================

@dataclass
class PositionResult:
    """单个位置的检测结果"""
    name: str                          # 位置名称
    position: int                      # 位置坐标
    passed: bool = False               # 是否通过
    message: str = ""                  # 结果消息
    annotated: Optional[np.ndarray] = None  # 标注图
    raw_image: Optional[np.ndarray] = None  # 原始图
    tool_results: list = field(default_factory=list)  # 工具检测结果
    elapsed_ms: float = 0.0            # 检测耗时


# ============================================================================
# 工作流管理器
# ============================================================================

class InspectionWorkflow(QObject):
    """自动化检测工作流管理器"""

    class State(Enum):
        IDLE = "空闲"
        MONITORING = "等待DI触发"
        WAITING = "等待工件放稳"
        MOVING = "移动中"
        CAPTURING = "拍照中"
        TESTING = "检测中"
        RETURNING = "退回原点"
        SHOW_RESULT = "显示结果"
        ERROR = "错误"

    # ── 信号 ──

    state_changed = pyqtSignal(object)  # State 枚举
    """工作流状态变化信号"""

    position_result_ready = pyqtSignal(int, object)
    """单个位置检测完成信号 (位置索引, PositionResult)"""

    all_results_ready = pyqtSignal(bool, list)
    """所有位置检测完成信号 (最终OK/NG, List[PositionResult])"""

    error_occurred = pyqtSignal(str)
    """错误信号"""

    trigger_count_changed = pyqtSignal(int)
    """触发次数变化信号"""

    ok_count_changed = pyqtSignal(int)
    """OK次数变化信号"""

    ng_count_changed = pyqtSignal(int)
    """NG次数变化信号"""

    # ── NG 手工确认信号 ──

    ng_confirm_requested = pyqtSignal(object)
    """NG 手工确认请求信号 (List[PositionResult]) - 发射所有检测结果，等待 UI 层弹窗确认"""

    def __init__(self, nmc_sdk: Optional[NMCSDK] = None,
                 camera_mgr=None, vision_engine=None,
                 config: Optional[WorkflowConfig] = None,
                 parent=None):
        """
        初始化工作流

        Args:
            nmc_sdk: NMC SDK 实例（可为 None，无控制卡时仅做模拟）
            camera_mgr: CameraManager 实例
            vision_engine: VisionEngine 实例
            config: 工作流配置
            parent: QObject 父对象
        """
        super().__init__(parent)
        self._nmc_sdk = nmc_sdk
        self._camera_mgr = camera_mgr
        self._vision_engine = vision_engine
        self._config = config or WorkflowConfig()

        # 产品配置
        self._product_config: Optional[Dict[str, Any]] = None
        self._pipelines: List = []  # 每个位置对应的 Pipeline

        # 状态
        self._state = self.State.IDLE
        self._running = False

        # DI 轮询
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_di)
        self._last_di_state = 0

        # 到位检测
        self._arrive_timer = QTimer(self)
        self._arrive_timer.timeout.connect(self._check_arrival)
        self._arrive_start_time = 0

        # DI 触发后延时启动（等待工件放稳）
        self._start_delay_timer = QTimer(self)
        self._start_delay_timer.setSingleShot(True)
        self._start_delay_timer.timeout.connect(self._on_start_delay_elapsed)

        # 当前执行状态
        self._current_pos_index = 0
        self._results: List[PositionResult] = []
        self._move_target = 0

        # 统计
        self._trigger_count = 0
        self._ok_count = 0
        self._ng_count = 0

    # ── 属性 ──

    @property
    def state(self) -> State:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def trigger_count(self) -> int:
        return self._trigger_count

    @property
    def ok_count(self) -> int:
        return self._ok_count

    @property
    def ng_count(self) -> int:
        return self._ng_count

    @property
    def product_config(self) -> Optional[Dict]:
        return self._product_config

    # ── 产品配置加载 ──

    def load_product(self, product_config: Dict[str, Any]) -> bool:
        """加载产品配置

        Args:
            product_config: 产品配置字典

        Returns:
            bool: 是否加载成功
        """
        if self._running:
            log_warning("工作流运行中，无法加载产品配置")
            return False

        self._product_config = product_config
        positions = product_config.get("positions", [])

        # 加载每个位置的视觉方案
        from vision.pipeline import Pipeline
        from core.paths import SCHEME_DIR
        import os

        self._pipelines = []
        for pos in positions:
            scheme_name = pos.get("scheme", "")
            if scheme_name:
                scheme_path = os.path.join(SCHEME_DIR, f"{scheme_name}.json")
                if os.path.exists(scheme_path):
                    try:
                        with open(scheme_path, 'r', encoding='utf-8') as f:
                            import json
                            data = json.load(f)
                        pipeline = Pipeline.from_dict(data)
                        self._pipelines.append(pipeline)
                        log_info(f"加载方案 [{scheme_name}] 成功")
                    except Exception as e:
                        log_error(f"加载方案 [{scheme_name}] 失败: {e}")
                        self._pipelines.append(None)
                else:
                    log_warning(f"方案文件不存在: {scheme_path}")
                    self._pipelines.append(None)
            else:
                self._pipelines.append(None)

        # 更新配置
        motion = product_config.get("motion", {})
        self._config.axis = motion.get("axis", self._config.axis)
        self._config.v_max = motion.get("v_max", self._config.v_max)
        self._config.a_max = motion.get("a_max", self._config.a_max)
        self._config.origin_position = motion.get("origin_position", self._config.origin_position)
        self._config.move_timeout_ms = motion.get("move_timeout_s", 10) * 1000
        self._config.di_bit = product_config.get("di_bit", self._config.di_bit)
        self._config.poll_interval_ms = product_config.get("poll_interval_ms", self._config.poll_interval_ms)

        log_info(f"产品配置已加载: {product_config.get('name', '未知')} "
                 f"({len(positions)}个位置)")
        return True

    # ── 生命周期控制 ──

    def start_monitoring(self):
        """开始监听 DI 信号"""
        if self._running:
            log_warning("工作流已在运行中")
            return

        if self._product_config is None:
            self.error_occurred.emit("未加载产品配置")
            return

        if self._nmc_sdk is None or not self._nmc_sdk.is_open():
            self.error_occurred.emit("NMC控制卡未连接")
            return

        self._running = True
        self._trigger_count = 0
        self._ok_count = 0
        self._ng_count = 0
        self._last_di_state = 0

        # 读取当前 DI 状态作为初始值
        try:
            self._last_di_state = self._nmc_sdk.get_input_bit(self._config.di_bit)
        except Exception:
            self._last_di_state = 0

        self._set_state(self.State.MONITORING)
        self._poll_timer.start(self._config.poll_interval_ms)
        log_info(f"开始监听 DI{self._config.di_bit} (轮询间隔: {self._config.poll_interval_ms}ms)")

    def stop_monitoring(self):
        """停止监听 DI 信号"""
        self._poll_timer.stop()
        self._arrive_timer.stop()
        self._start_delay_timer.stop()
        self._running = False
        self._set_state(self.State.IDLE)
        log_info("停止监听 DI 信号")

    def emergency_stop(self):
        """紧急停止"""
        self._poll_timer.stop()
        self._arrive_timer.stop()
        self._start_delay_timer.stop()

        if self._nmc_sdk and self._nmc_sdk.is_open():
            try:
                self._nmc_sdk.emergency_stop_all()
                log_info("紧急停止所有轴")
            except Exception as e:
                log_error(f"紧急停止失败: {e}")

        self._running = False
        self._set_state(self.State.IDLE)
        log_info("紧急停止")

    def reset_error(self):
        """复位错误状态"""
        if self._state == self.State.ERROR:
            self._running = False
            self._set_state(self.State.IDLE)
            log_info("错误已复位")

    # ── 状态管理 ──

    def _set_state(self, new_state: State):
        """安全切换状态"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            log_info(f"工作流: {old_state.value} -> {new_state.value}")
            self.state_changed.emit(new_state)

    # ── DI 轮询 ──

    def _poll_di(self):
        """轮询 DI 状态，检测下降沿（工件放入时触发）"""
        if self._state != self.State.MONITORING:
            return

        try:
            current = self._nmc_sdk.get_input_bit(self._config.di_bit)
            # 检测下降沿: 1 -> 0（工件放入时 DI 从高变低）
            if current == 0 and self._last_di_state == 1:
                log_info(f"DI{self._config.di_bit} 下降沿触发 (工件放入)")
                self._on_di_triggered()
            self._last_di_state = current
        except Exception as e:
            log_error(f"读取 DI 失败: {e}")

    def _on_di_triggered(self):
        """DI 触发 - 延时后开始执行检测流程"""
        self._trigger_count += 1
        self.trigger_count_changed.emit(self._trigger_count)

        # 重置当前执行状态
        self._current_pos_index = 0
        self._results = []

        # 延时 1 秒再开始移动，等待工件放稳
        log_info("DI 触发，等待 1 秒后开始检测...")
        self._set_state(self.State.WAITING)
        self._start_delay_timer.start(1000)  # 1 秒

    def _on_start_delay_elapsed(self):
        """延时结束 - 开始移动到第一个位置"""
        log_info("延时结束，开始执行检测流程")
        self._execute_current_position()

    # ── 位置执行 ──

    def _execute_current_position(self):
        """执行当前位置的检测"""
        positions = self._product_config.get("positions", [])
        if self._current_pos_index >= len(positions):
            # 所有位置已完成，退回原点
            self._return_to_origin()
            return

        pos = positions[self._current_pos_index]
        target = pos.get("position", 0)

        log_info(f"移动到位置 {self._current_pos_index + 1}: {pos.get('name', '')} (坐标: {target})")
        self._move_to(target)

    def _move_to(self, target_pos: int):
        """移动到目标位置"""
        self._set_state(self.State.MOVING)
        self._move_target = target_pos

        try:
            axis = self._config.axis

            # 1) 确保轴已使能
            try:
                self._nmc_sdk.set_servo_enable(axis, 1)
            except Exception as e:
                log_warning(f"轴{axis + 1} 使能失败(可忽略): {e}")

            # 2) 清除轴状态（清除可能的停止/报警状态）
            try:
                self._nmc_sdk.clear_axis_state(axis)
            except Exception as e:
                log_warning(f"清除轴{axis + 1} 状态失败(可忽略): {e}")

            # 3) 读取当前位置，计算相对位移（与 main_window.py 手动移动逻辑一致）
            try:
                current_pos = self._nmc_sdk.get_position(axis)
            except Exception:
                current_pos = 0
            diff = target_pos - current_pos
            log_info(f"轴{axis + 1} 当前位置: {current_pos}, 目标: {target_pos}, 相对位移: {diff}")

            # 4) 设置速度参数
            ret_profile = self._nmc_sdk.set_axis_profile(
                axis,
                0,                      # v_ini
                self._config.v_max,     # v_max
                self._config.a_max,     # a_max
                0,                      # jerk
                0,                      # v_end
                Profile_S               # S曲线
            )
            log_info(f"轴{axis + 1} set_axis_profile 返回值: {ret_profile}")

            # 5) 发送相对位置运动指令（使用 uniaxial_long 避免 c_double/c_long 冲突）
            ret_move = self._nmc_sdk.uniaxial_long(axis, diff, Position_Opposite)
            log_info(f"轴{axis + 1} uniaxial_long(相对, dist={diff}) 返回值: {ret_move}")

            if ret_move != 0:
                error_msg = f"轴{axis + 1} 移动失败，返回值: {ret_move}"
                log_error(error_msg)
                self._on_error(error_msg)
                return

            # 6) 启动到位检测
            import time
            self._arrive_start_time = int(time.time() * 1000)
            self._arrive_timer.start(self._config.arrive_check_interval_ms)

        except Exception as e:
            error_msg = f"运动失败: {e}"
            log_error(error_msg)
            self._on_error(error_msg)

    def _check_arrival(self):
        """检查轴是否到位"""
        try:
            state = self._nmc_sdk.get_axis_state(self._config.axis)
            if state == 0:  # 空闲 = 到位
                self._arrive_timer.stop()
                log_info(f"轴已到位 (位置: {self._move_target})")
                # 根据当前状态决定到位后的处理
                if self._state == self.State.RETURNING:
                    self._on_returned_to_origin()
                else:
                    self._on_arrived()
                return

            # 超时检查
            import time
            elapsed = int(time.time() * 1000) - self._arrive_start_time
            if elapsed > self._config.move_timeout_ms:
                self._arrive_timer.stop()
                error_msg = f"运动超时 ({self._config.move_timeout_ms}ms)"
                log_error(error_msg)
                self._nmc_sdk.axis_stop(self._config.axis, Axis_Stop_DEC)
                self._on_error(error_msg)

        except Exception as e:
            log_error(f"到位检测失败: {e}")

    def _on_arrived(self):
        """到位后的处理 - 拍照"""
        self._capture()

    # ── 拍照 ──

    def _capture(self):
        """拍照"""
        self._set_state(self.State.CAPTURING)

        if self._camera_mgr is None:
            self._on_error("相机管理器未初始化")
            return

        try:
            # 先设置相机参数（从产品配置读取）
            camera_cfg = self._product_config.get("camera", {})
            if camera_cfg:
                try:
                    if hasattr(self._camera_mgr, 'set_exposure_time'):
                        self._camera_mgr.set_exposure_time(camera_cfg.get("exposure_time", 18000))
                    if hasattr(self._camera_mgr, 'set_gain'):
                        self._camera_mgr.set_gain(camera_cfg.get("gain", 0))
                except Exception as e:
                    log_warning(f"设置相机参数失败: {e}")

            # 触发拍照
            if hasattr(self._camera_mgr, 'capture_once'):
                raw = self._camera_mgr.capture_once()
                # capture_once() 返回 (width, height, pixel_type, data) 元组
                # 需要转换为 OpenCV 图像
                if isinstance(raw, tuple) and len(raw) == 4:
                    from camera_manager import raw_to_opencv
                    width, height, pixel_type, frame_data = raw
                    image = raw_to_opencv(frame_data, width, height, pixel_type)
                else:
                    # 兼容：如果返回的已经是 numpy 数组
                    image = raw
            else:
                # 兼容：从实时流中获取当前帧
                image = getattr(self._camera_mgr, 'get_current_frame', lambda: None)()

            if image is None:
                self._on_error("拍照失败: 图像为空")
                return

            log_info(f"拍照成功 (位置 {self._current_pos_index + 1})")
            self._start_test(image)

        except Exception as e:
            self._on_error(f"拍照失败: {e}")

    # ── 检测 ──

    def _start_test(self, image: np.ndarray):
        """开始检测"""
        self._set_state(self.State.TESTING)

        # 获取当前位置对应的流水线
        pipeline = None
        if self._current_pos_index < len(self._pipelines):
            pipeline = self._pipelines[self._current_pos_index]

        if pipeline is None:
            # 没有流水线，直接标记为通过（占位）
            log_warning(f"位置 {self._current_pos_index + 1} 未设置视觉方案，标记为通过")
            self._on_test_completed(True, "未设置方案，默认通过", image, image, [])
            return

        # 设置流水线并执行检测
        self._vision_engine.set_pipeline(pipeline)
        try:
            passed, message, annotated = self._vision_engine.execute(
                image,
                scheme_name=self._product_config.get("name", "未知")
            )
            results = self._vision_engine.get_last_results()
            self._on_test_completed(passed, message, annotated, image, results)
        except Exception as e:
            log_error(f"检测异常: {e}")
            self._on_test_completed(False, f"检测异常: {e}", image, image, [])

    def _on_test_completed(self, passed: bool, message: str,
                           annotated: np.ndarray, raw_image: np.ndarray,
                           tool_results: list):
        """检测完成回调"""
        positions = self._product_config.get("positions", [])
        pos = positions[self._current_pos_index] if self._current_pos_index < len(positions) else {"name": f"位置{self._current_pos_index + 1}"}

        # 记录结果
        import time
        result = PositionResult(
            name=pos.get("name", f"位置{self._current_pos_index + 1}"),
            position=pos.get("position", 0),
            passed=passed,
            message=message,
            annotated=annotated,
            raw_image=raw_image,
            tool_results=tool_results,
            elapsed_ms=0.0  # TODO: 计算实际耗时
        )
        self._results.append(result)

        log_info(f"位置 {self._current_pos_index + 1} [{result.name}]: {'OK' if passed else 'NG'} | {message}")

        # 发射单个位置结果信号
        self.position_result_ready.emit(self._current_pos_index, result)

        # 移动到下一个位置
        self._current_pos_index += 1
        self._execute_current_position()

    # ── 退回原点 ──

    def _return_to_origin(self):
        """退回原点"""
        self._set_state(self.State.RETURNING)
        log_info(f"退回原点 (坐标: {self._config.origin_position})")

        # 先停止到位检测计时器，防止轴已到位时误触发 _on_arrived
        self._arrive_timer.stop()

        # 发送回原点运动指令
        self._move_target = self._config.origin_position
        try:
            axis = self._config.axis

            # 1) 确保轴已使能
            try:
                self._nmc_sdk.set_servo_enable(axis, 1)
            except Exception as e:
                log_warning(f"轴{axis + 1} 使能失败(可忽略): {e}")

            # 2) 清除轴状态（清除可能的停止/报警状态）
            try:
                self._nmc_sdk.clear_axis_state(axis)
            except Exception as e:
                log_warning(f"清除轴{axis + 1} 状态失败(可忽略): {e}")

            # 3) 读取当前位置，计算相对位移（与 _move_to 逻辑一致）
            try:
                current_pos = self._nmc_sdk.get_position(axis)
            except Exception:
                current_pos = 0
            diff = self._config.origin_position - current_pos
            log_info(f"轴{axis + 1} 当前位置: {current_pos}, 原点目标: {self._config.origin_position}, 相对位移: {diff}")

            # 4) 设置速度参数
            ret_profile = self._nmc_sdk.set_axis_profile(
                axis,
                0,                      # v_ini
                self._config.v_max,     # v_max
                self._config.a_max,     # a_max
                0,                      # jerk
                0,                      # v_end
                Profile_S               # S曲线
            )
            log_info(f"轴{axis + 1} set_axis_profile 返回值: {ret_profile}")

            # 5) 发送相对位置运动指令（使用 uniaxial_long 避免 c_double/c_long 冲突）
            ret_move = self._nmc_sdk.uniaxial_long(axis, diff, Position_Opposite)
            log_info(f"轴{axis + 1} uniaxial_long(相对, dist={diff}) 返回值: {ret_move}")

            if ret_move != 0:
                error_msg = f"轴{axis + 1} 退回原点失败，返回值: {ret_move}"
                log_error(error_msg)
                self._on_error(error_msg)
                return

            # 6) 启动到位检测（用于回原点）
            import time
            self._arrive_start_time = int(time.time() * 1000)
            self._arrive_timer.start(self._config.arrive_check_interval_ms)
        except Exception as e:
            log_error(f"退回原点运动失败: {e}")
            # 运动失败也直接显示结果
            self._show_final_result()

    def _on_returned_to_origin(self):
        """回到原点后的处理 - 显示结果"""
        self._show_final_result()

    # ── 显示结果 ──

    def _show_final_result(self):
        """显示最终结果"""
        self._set_state(self.State.SHOW_RESULT)

        # 计算最终结果（所有位置都通过才算 OK）
        all_passed = all(r.passed for r in self._results)

        if all_passed:
            # OK：直接更新统计并继续
            self._ok_count += 1
            self.ok_count_changed.emit(self._ok_count)
            # 发射最终结果信号
            self.all_results_ready.emit(True, self._results)
            log_info(f"最终结果: OK "
                     f"(触发: {self._trigger_count}, OK: {self._ok_count}, NG: {self._ng_count})")
            # 自动继续监听
            self._set_state(self.State.MONITORING)
        else:
            # NG：发射手工确认请求信号，等待 UI 层弹窗确认
            log_info("检测结果为 NG，请求手工确认...")
            self._set_state(self.State.WAITING)  # 进入等待确认状态
            self.ng_confirm_requested.emit(self._results)

    def confirm_ng_result(self, confirmed_ok: bool):
        """
        NG 手工确认结果回调 - 由 UI 层在弹窗确认后调用。

        Args:
            confirmed_ok: True 表示操作员确认为 OK，False 表示确认为 NG
        """
        if self._state != self.State.WAITING:
            log_warning(f"工作流状态不是 WAITING，忽略确认回调 (当前: {self._state.value})")
            return

        if confirmed_ok:
            # 操作员确认为 OK
            self._ok_count += 1
            self.ok_count_changed.emit(self._ok_count)
            log_info("手工确认: OK")
            self.all_results_ready.emit(True, self._results)
        else:
            # 操作员确认为 NG
            self._ng_count += 1
            self.ng_count_changed.emit(self._ng_count)
            log_info("手工确认: NG")
            self.all_results_ready.emit(False, self._results)

        log_info(f"最终结果: {'OK' if confirmed_ok else 'NG'} "
                 f"(触发: {self._trigger_count}, OK: {self._ok_count}, NG: {self._ng_count})")

        # 自动继续监听
        self._set_state(self.State.MONITORING)

    # ── 错误处理 ──

    def _on_error(self, error_msg: str):
        """错误处理"""
        log_error(error_msg)
        self.error_occurred.emit(error_msg)
        self._set_state(self.State.ERROR)

        # 尝试停止轴
        if self._nmc_sdk and self._nmc_sdk.is_open():
            try:
                self._nmc_sdk.axis_stop(self._config.axis, Axis_Stop_DEC)
            except Exception:
                pass

    # ── 资源清理 ──

    def cleanup(self):
        """清理资源"""
        self.stop_monitoring()
        self._poll_timer.stop()
        self._arrive_timer.stop()
        self._pipelines = []
        self._product_config = None
        self._results = []
        log_info("工作流资源已清理")
