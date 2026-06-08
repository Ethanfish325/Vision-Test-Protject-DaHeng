# -*- coding: utf-8 -*-
"""
海康工业相机管理模块
====================
基于 MVS SDK 的相机操作封装，参考官方 Python DEMO 实现。

功能：
  - 枚举 GigE/USB 相机设备
  - 连接/断开相机
  - 实时取流（工作线程模式）
  - 参数调节（曝光时间、增益、帧率）
  - 触发模式切换（连续/软触发）
  - 单次拍照（软触发模式）
  - 图像格式转换（Bayer/Mono/YUV -> BGR）
  - GigE 网络优化（自动设置包大小）
"""

import os
import sys
import time
import ctypes
import threading
from typing import Optional, Callable, List, Dict, Any, Tuple

import cv2
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap

from core.log_manager import log_error, log_info, log_warning


# ============================================================
#  SDK 导入与路径配置
# ============================================================
# 搜索顺序：
#   1. 本地 MvImport 目录（打包后或开发环境项目目录下的）
#   2. MVS 官方 SDK 安装目录（D:\MVS\Development\Samples\Python\MvImport）
#
# MvCameraControl_class.py 内部使用相对导入 (from PixelType_header import *)
# 所以需要将 MvImport 目录本身加入 path
# 同时 MvCameraControl_class.py 在模块加载时立即调用
# check_sys_and_update_dll() -> WinDLL("MvCameraControl.dll")，
# 因此还需要将 MvImport 目录设为当前工作目录，或将其加入 DLL 搜索路径。

def _find_mvimport_dir() -> str:
    """查找可用的 MvImport 目录"""
    # 1. 检查本地项目目录下的 MvImport（打包后或开发环境）
    local_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'MvImport')
    if os.path.isdir(local_dir):
        return local_dir

    # 2. 检查 MVS 官方 SDK 安装目录
    mvs_dir = os.path.join(os.getenv("MVCAM_COMMON_RUNENV", "D:\\MVS\\Development"),
                           "Samples", "Python", "MvImport")
    if os.path.isdir(mvs_dir):
        return mvs_dir

    return local_dir  # 返回默认值，让 import 失败时走异常处理


MVS_MVIMPORT = _find_mvimport_dir()
if MVS_MVIMPORT not in sys.path:
    sys.path.insert(0, MVS_MVIMPORT)

# 重要：将 MvImport 目录添加到 DLL 搜索路径
# MvCameraControl_class.py 在模块加载时立即调用
# check_sys_and_update_dll() -> WinDLL("MvCameraControl.dll")
# 该 DLL 及其依赖的所有 DLL 都在 MvImport 目录下
if os.path.isdir(MVS_MVIMPORT):
    # Windows 7+ 支持 AddDllDirectory (KB2533623)
    try:
        import ctypes
        # 使用 os.add_dll_directory (Python 3.8+, Windows 8.1+)
        os.add_dll_directory(MVS_MVIMPORT)
    except (AttributeError, OSError):
        # 回退：将目录加入 PATH
        os.environ['PATH'] = MVS_MVIMPORT + os.pathsep + os.environ.get('PATH', '')

# 导入 SDK 模块
try:
    from MvCameraControl_class import MvCamera
    from CameraParams_header import (
        MV_CC_DEVICE_INFO_LIST, MV_CC_DEVICE_INFO,
        MV_FRAME_OUT, MV_FRAME_OUT_INFO_EX,
        MVCC_FLOATVALUE, MVCC_INTVALUE, MVCC_ENUMVALUE,
        MV_GIGE_DEVICE, MV_USB_DEVICE,
    )
    from MvErrorDefine_const import MV_E_CALLORDER, MV_OK
    from PixelType_header import (
        PixelType_Gvsp_Mono8,
        PixelType_Gvsp_Mono10, PixelType_Gvsp_Mono10_Packed,
        PixelType_Gvsp_Mono12, PixelType_Gvsp_Mono12_Packed,
        PixelType_Gvsp_BayerGR8, PixelType_Gvsp_BayerRG8,
        PixelType_Gvsp_BayerGB8, PixelType_Gvsp_BayerBG8,
        PixelType_Gvsp_BayerGR10, PixelType_Gvsp_BayerRG10,
        PixelType_Gvsp_BayerGB10, PixelType_Gvsp_BayerBG10,
        PixelType_Gvsp_BayerGR12, PixelType_Gvsp_BayerRG12,
        PixelType_Gvsp_BayerGB12, PixelType_Gvsp_BayerBG12,
        PixelType_Gvsp_BayerGR10_Packed, PixelType_Gvsp_BayerRG10_Packed,
        PixelType_Gvsp_BayerGB10_Packed, PixelType_Gvsp_BayerBG10_Packed,
        PixelType_Gvsp_BayerGR12_Packed, PixelType_Gvsp_BayerRG12_Packed,
        PixelType_Gvsp_BayerGB12_Packed, PixelType_Gvsp_BayerBG12_Packed,
        PixelType_Gvsp_BayerRBGG8,
        PixelType_Gvsp_BayerGR16, PixelType_Gvsp_BayerRG16,
        PixelType_Gvsp_BayerGB16, PixelType_Gvsp_BayerBG16,
        PixelType_Gvsp_YUV422_Packed, PixelType_Gvsp_YUV422_YUYV_Packed,
    )
    SDK_AVAILABLE = True
except ImportError as e:
    MvCamera = None
    SDK_AVAILABLE = False
    log_info(f"相机 SDK 未加载，相机功能不可用: {e}")


# ============================================================
#  工具函数
# ============================================================

def error_code_to_hex(error_num) -> str:
    """将错误码转为十六进制字符串"""
    if error_num < 0:
        return f"-0x{abs(error_num):08X}"
    return f"0x{error_num:08X}"


def decode_char(ctypes_char_array) -> str:
    """安全地从 ctypes 字符数组中解码出字符串"""
    byte_str = memoryview(ctypes_char_array).tobytes()
    null_idx = byte_str.find(b'\x00')
    if null_idx != -1:
        byte_str = byte_str[:null_idx]
    for encoding in ['gbk', 'utf-8', 'latin-1']:
        try:
            return byte_str.decode(encoding)
        except UnicodeDecodeError:
            continue
    return byte_str.decode('latin-1', errors='replace')


def is_mono_data(pixel_type: int) -> bool:
    """判断是否为 Mono 图像"""
    mono_types = [
        PixelType_Gvsp_Mono8, PixelType_Gvsp_Mono10,
        PixelType_Gvsp_Mono10_Packed, PixelType_Gvsp_Mono12,
        PixelType_Gvsp_Mono12_Packed
    ]
    return pixel_type in mono_types


def is_color_data(pixel_type: int) -> bool:
    """判断是否为彩色/Bayer 图像"""
    color_types = [
        PixelType_Gvsp_BayerGR8, PixelType_Gvsp_BayerRG8,
        PixelType_Gvsp_BayerGB8, PixelType_Gvsp_BayerBG8,
        PixelType_Gvsp_BayerGR10, PixelType_Gvsp_BayerRG10,
        PixelType_Gvsp_BayerGB10, PixelType_Gvsp_BayerBG10,
        PixelType_Gvsp_BayerGR12, PixelType_Gvsp_BayerRG12,
        PixelType_Gvsp_BayerGB12, PixelType_Gvsp_BayerBG12,
        PixelType_Gvsp_BayerGR10_Packed, PixelType_Gvsp_BayerRG10_Packed,
        PixelType_Gvsp_BayerGB10_Packed, PixelType_Gvsp_BayerBG10_Packed,
        PixelType_Gvsp_BayerGR12_Packed, PixelType_Gvsp_BayerRG12_Packed,
        PixelType_Gvsp_BayerGB12_Packed, PixelType_Gvsp_BayerBG12_Packed,
        PixelType_Gvsp_BayerRBGG8,
        PixelType_Gvsp_BayerGR16, PixelType_Gvsp_BayerRG16,
        PixelType_Gvsp_BayerGB16, PixelType_Gvsp_BayerBG16,
        PixelType_Gvsp_YUV422_Packed, PixelType_Gvsp_YUV422_YUYV_Packed,
    ]
    return pixel_type in color_types


def pixel_type_to_opencv(pixel_type: int) -> Tuple[Optional[int], bool]:
    """
    将海康像素格式映射到 OpenCV 转换标志。

    Returns:
        (cv2_color_conversion_flag_or_None, is_color)
    """
    mapping = {
        PixelType_Gvsp_Mono8: (None, False),
        PixelType_Gvsp_BayerGR8: (cv2.COLOR_BayerGR2BGR, True),
        PixelType_Gvsp_BayerRG8: (cv2.COLOR_BayerRG2BGR, True),
        PixelType_Gvsp_BayerGB8: (cv2.COLOR_BayerGB2BGR, True),
        PixelType_Gvsp_BayerBG8: (cv2.COLOR_BayerBG2BGR, True),
    }
    bayer_gr_10_12 = [
        PixelType_Gvsp_BayerGR10, PixelType_Gvsp_BayerGR10_Packed,
        PixelType_Gvsp_BayerGR12, PixelType_Gvsp_BayerGR12_Packed,
    ]
    bayer_rg_10_12 = [
        PixelType_Gvsp_BayerRG10, PixelType_Gvsp_BayerRG10_Packed,
        PixelType_Gvsp_BayerRG12, PixelType_Gvsp_BayerRG12_Packed,
    ]
    bayer_gb_10_12 = [
        PixelType_Gvsp_BayerGB10, PixelType_Gvsp_BayerGB10_Packed,
        PixelType_Gvsp_BayerGB12, PixelType_Gvsp_BayerGB12_Packed,
    ]
    bayer_bg_10_12 = [
        PixelType_Gvsp_BayerBG10, PixelType_Gvsp_BayerBG10_Packed,
        PixelType_Gvsp_BayerBG12, PixelType_Gvsp_BayerBG12_Packed,
    ]

    if pixel_type in mapping:
        return mapping[pixel_type]
    elif pixel_type in bayer_gr_10_12:
        return (cv2.COLOR_BayerGR2BGR, True)
    elif pixel_type in bayer_rg_10_12:
        return (cv2.COLOR_BayerRG2BGR, True)
    elif pixel_type in bayer_gb_10_12:
        return (cv2.COLOR_BayerGB2BGR, True)
    elif pixel_type in bayer_bg_10_12:
        return (cv2.COLOR_BayerBG2BGR, True)
    elif pixel_type in (PixelType_Gvsp_YUV422_Packed, PixelType_Gvsp_YUV422_YUYV_Packed):
        return (cv2.COLOR_YUV2BGR_YUYV, True)
    else:
        return (None, False)


def raw_to_opencv(frame_data: bytes, width: int, height: int,
                  pixel_type: int) -> Optional[np.ndarray]:
    """
    将 SDK 原始帧数据转换为 OpenCV BGR 图像。

    Args:
        frame_data: 原始帧字节数据
        width: 图像宽度
        height: 图像高度
        pixel_type: 海康像素格式枚举值

    Returns:
        BGR 格式的 numpy 数组，失败返回 None
    """
    try:
        img_data = np.frombuffer(frame_data, dtype=np.uint8)

        if pixel_type == PixelType_Gvsp_Mono8:
            return img_data.reshape((height, width)).copy()

        elif is_color_data(pixel_type):
            bayer_img = img_data.reshape((height, width)).copy()
            cv_color, _ = pixel_type_to_opencv(pixel_type)
            if cv_color is not None:
                return cv2.cvtColor(bayer_img, cv_color)
            return cv2.cvtColor(bayer_img, cv2.COLOR_BayerBG2BGR)

        elif pixel_type in (PixelType_Gvsp_YUV422_Packed,
                            PixelType_Gvsp_YUV422_YUYV_Packed):
            yuv_img = img_data.reshape((height, width, 2)).copy()
            return cv2.cvtColor(yuv_img, cv2.COLOR_YUV2BGR_YUYV)

        else:
            try:
                return img_data.reshape((height, width, 3)).copy()
            except Exception:
                return img_data.reshape((height, width)).copy()

    except Exception as e:
        log_error(f"图像格式转换失败: {e}")
        return None


# ============================================================
#  取流线程（QThread 版本，用于 UI 集成）
# ============================================================

class CameraGrabbingThread(QThread):
    """
    相机取流线程。
    在后台循环调用 MV_CC_GetImageBuffer 获取图像，
    并通过信号将帧数据发送到主线程。
    """

    frame_received = pyqtSignal(int, int, int, bytes)  # width, height, pixel_type, data

    def __init__(self, camera_obj):
        super().__init__()
        self._camera = camera_obj
        self._running = False

    def run(self):
        self._running = True
        st_frame = MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(st_frame), 0, ctypes.sizeof(MV_FRAME_OUT))

        while self._running:
            try:
                ret = self._camera.MV_CC_GetImageBuffer(st_frame, 200)
                if ret == MV_OK:
                    frame_info = st_frame.stFrameInfo
                    width = frame_info.nWidth
                    height = frame_info.nHeight
                    pixel_type = frame_info.enPixelType
                    frame_len = frame_info.nFrameLen

                    if st_frame.pBufAddr and frame_len > 0:
                        buf = (ctypes.c_ubyte * frame_len).from_address(
                            ctypes.addressof(st_frame.pBufAddr.contents))
                        img_bytes = bytes(buf)
                    else:
                        img_bytes = b""

                    self._camera.MV_CC_FreeImageBuffer(st_frame)

                    if img_bytes:
                        self.frame_received.emit(width, height, pixel_type, img_bytes)
                else:
                    self.msleep(5)

            except Exception as e:
                log_error(f"取流线程异常: {e}")
                self.msleep(50)

    def stop(self):
        self._running = False
        self.wait(2000)


# ============================================================
#  相机管理器（主类）
# ============================================================

class CameraManager:
    """
    海康工业相机管理器。

    封装了相机的枚举、连接、取流、参数调节、触发控制等完整操作。
    参考官方 Python DEMO 中的 HikCamera 类实现。

    用法:
        mgr = CameraManager()
        devices = mgr.enumerate_devices()
        if devices:
            mgr.open_camera(devices[0]["dev_info"])
            mgr.start_grabbing(callback)
            ...
            mgr.close_camera()
    """

    _MvCamera = MvCamera
    _sdk_initialized = False

    def __init__(self):
        self._camera = None
        self._grabbing_thread = None
        self._is_grabbing = False
        self._lock = threading.Lock()
        self._device_info = None
        self._is_trigger_mode = False

    # ---------- SDK 初始化 ----------

    @staticmethod
    def initialize_sdk():
        """初始化相机 SDK（应用启动时调用一次）"""
        if not SDK_AVAILABLE:
            log_info("相机 SDK 不可用，跳过初始化")
            return

        try:
            ret = MvCamera.MV_CC_Initialize()
            if ret == MV_OK:
                CameraManager._sdk_initialized = True
                log_info("相机 SDK 初始化成功")
            else:
                log_error(f"相机 SDK 初始化失败: {error_code_to_hex(ret)}")
        except Exception as e:
            log_error(f"相机 SDK 初始化异常: {e}")

    @staticmethod
    def finalize_sdk():
        """反初始化相机 SDK（应用退出时调用一次）"""
        if not SDK_AVAILABLE:
            return
        try:
            MvCamera.MV_CC_Finalize()
        except Exception:
            pass
        CameraManager._sdk_initialized = False
        log_info("相机 SDK 反初始化完成")

    def _ensure_sdk_initialized(self):
        if not CameraManager._sdk_initialized:
            self.initialize_sdk()

    # ---------- 设备枚举 ----------

    def enumerate_devices(self, timeout_ms: int = 200) -> List[Dict[str, Any]]:
        """
        枚举所有可用的相机设备。

        Args:
            timeout_ms: GigE 设备枚举超时时间（毫秒）

        Returns:
            list of dict, 每个 dict 包含:
                - index: 设备索引
                - name: 设备显示名称
                - model: 设备型号
                - serial: 序列号
                - ip: IP 地址（GigE）
                - type: 设备类型 (GigE/USB)
                - tlayer_type: 传输层类型枚举值
                - dev_info: 深度拷贝的 MV_CC_DEVICE_INFO 结构体
        """
        devices = []
        if not SDK_AVAILABLE:
            log_info("相机 SDK 不可用，无法枚举设备")
            return devices

        try:
            self._ensure_sdk_initialized()

            try:
                MvCamera.MV_GIGE_SetEnumDevTimeout(timeout_ms)
            except Exception:
                pass

            device_list = MV_CC_DEVICE_INFO_LIST()
            n_layer_type = MV_GIGE_DEVICE | MV_USB_DEVICE
            ret = MvCamera.MV_CC_EnumDevices(n_layer_type, device_list)

            if ret == MV_OK and device_list.nDeviceNum > 0:
                for i in range(device_list.nDeviceNum):
                    dev_info = ctypes.cast(
                        device_list.pDeviceInfo[i],
                        ctypes.POINTER(MV_CC_DEVICE_INFO)
                    ).contents
                    dev_info_copy = self._deep_copy_device_info(dev_info)
                    info = self._parse_device_info(dev_info_copy, i)
                    if info:
                        devices.append(info)

            log_info(f"枚举到 {len(devices)} 个相机设备")

        except Exception as e:
            log_error(f"枚举相机失败: {e}")

        return devices

    def _deep_copy_device_info(self, src) -> MV_CC_DEVICE_INFO:
        dst = MV_CC_DEVICE_INFO()
        ctypes.memmove(ctypes.byref(dst), ctypes.byref(src),
                       ctypes.sizeof(MV_CC_DEVICE_INFO))
        return dst

    def _parse_device_info(self, dev_info, index: int) -> Optional[Dict[str, Any]]:
        try:
            n_layer = dev_info.nTLayerType
            result = {
                "index": index,
                "tlayer_type": n_layer,
                "dev_info": dev_info,
            }

            if n_layer == MV_GIGE_DEVICE:
                gige = dev_info.SpecialInfo.stGigEInfo
                result["type"] = "GigE"
                result["name"] = decode_char(gige.chUserDefinedName)
                result["model"] = decode_char(gige.chModelName)
                result["serial"] = decode_char(gige.chSerialNumber)
                ip = gige.nCurrentIp
                result["ip"] = f"{(ip >> 24) & 0xff}.{(ip >> 16) & 0xff}.{(ip >> 8) & 0xff}.{ip & 0xff}"
            elif n_layer == MV_USB_DEVICE:
                usb = dev_info.SpecialInfo.stUsb3VInfo
                result["type"] = "USB"
                result["name"] = decode_char(usb.chUserDefinedName)
                result["model"] = decode_char(usb.chModelName)
                result["serial"] = decode_char(usb.chSerialNumber)
                result["ip"] = "N/A"
            else:
                result["type"] = "Unknown"
                result["name"] = "Unknown"
                result["model"] = "Unknown"
                result["serial"] = "Unknown"
                result["ip"] = "N/A"

            return result

        except Exception as e:
            log_error(f"解析设备信息失败: {e}")
            return None

    # ---------- 连接与打开 ----------

    def open_camera(self, dev_info) -> bool:
        """
        打开相机设备。

        Args:
            dev_info: MV_CC_DEVICE_INFO 结构体（来自 enumerate_devices 返回的 dev_info）

        Returns:
            bool: 是否成功打开
        """
        if not SDK_AVAILABLE:
            log_error("相机 SDK 不可用")
            return False

        if self._camera is not None:
            log_info("相机已打开，请先关闭")
            return False

        try:
            self._ensure_sdk_initialized()

            dev_info_parsed = self._parse_device_info(dev_info, 0)
            if dev_info_parsed:
                log_info(f"正在打开相机: {dev_info_parsed['model']} ({dev_info_parsed['serial']})")

            self._camera = MvCamera()
            ret = self._camera.MV_CC_CreateHandle(dev_info)
            if ret != MV_OK:
                log_error(f"创建相机句柄失败: {error_code_to_hex(ret)}")
                self._camera = MvCamera()
                ret = self._camera.MV_CC_CreateHandleWithoutLog(dev_info)
                if ret != MV_OK:
                    log_error(f"CreateHandleWithoutLog 也失败: {error_code_to_hex(ret)}")
                    self._camera = None
                    return False

            ret = self._camera.MV_CC_OpenDevice()
            if ret != MV_OK:
                log_error(f"打开设备失败: {error_code_to_hex(ret)}")
                self._camera.MV_CC_DestroyHandle()
                self._camera = None
                return False

            self._device_info = dev_info_parsed
            log_info(f"相机打开成功: {dev_info_parsed['model']}")

            if dev_info_parsed and dev_info_parsed["tlayer_type"] == MV_GIGE_DEVICE:
                self._optimize_gige()

            self.set_trigger_mode(False)

            return True

        except Exception as e:
            log_error(f"打开相机异常: {e}")
            self._camera = None
            return False

    def _optimize_gige(self):
        try:
            n_packet_size = self._camera.MV_CC_GetOptimalPacketSize()
            if n_packet_size > 0:
                ret = self._camera.MV_CC_SetIntValue("GevSCPSPacketSize", n_packet_size)
                if ret == MV_OK:
                    log_info(f"GigE 包大小已优化: {n_packet_size}")
                else:
                    log_warning(f"设置包大小失败: {error_code_to_hex(ret)}")
            else:
                log_warning(f"获取最优包大小失败: {error_code_to_hex(n_packet_size)}")
        except Exception as e:
            log_error(f"GigE 优化异常: {e}")

    # ---------- 关闭 ----------

    def close_camera(self):
        try:
            self.stop_grabbing()

            if self._camera is not None:
                self._camera.MV_CC_CloseDevice()
                self._camera.MV_CC_DestroyHandle()
                self._camera = None
                self._device_info = None
                self._is_trigger_mode = False
                log_info("相机关闭成功")
        except Exception as e:
            log_error(f"关闭相机异常: {e}")

    # ---------- 触发模式 ----------

    def set_trigger_mode(self, enable: bool) -> bool:
        """
        设置触发模式。

        Args:
            enable: True=触发模式, False=连续采集模式

        Returns:
            bool: 是否成功
        """
        if self._camera is None:
            return False

        try:
            if enable:
                ret = self._camera.MV_CC_SetEnumValue("TriggerMode", 1)
                if ret != MV_OK:
                    log_error(f"设置触发模式失败: {error_code_to_hex(ret)}")
                    return False
                ret = self._camera.MV_CC_SetEnumValue("TriggerSource", 7)
                if ret != MV_OK:
                    log_error(f"设置触发源失败: {error_code_to_hex(ret)}")
                    return False
                self._is_trigger_mode = True
                log_info("已切换为触发模式（软触发）")
            else:
                ret = self._camera.MV_CC_SetEnumValue("TriggerMode", 0)
                if ret != MV_OK:
                    log_error(f"设置连续模式失败: {error_code_to_hex(ret)}")
                    return False
                self._is_trigger_mode = False
                log_info("已切换为连续采集模式")

            return True

        except Exception as e:
            log_error(f"设置触发模式异常: {e}")
            return False

    def trigger_once(self) -> bool:
        """软触发一次（仅在触发模式下有效）"""
        if self._camera is None or not self._is_trigger_mode:
            return False
        try:
            ret = self._camera.MV_CC_SetCommandValue("TriggerSoftware")
            return ret == MV_OK
        except Exception as e:
            log_error(f"软触发异常: {e}")
            return False

    @property
    def is_trigger_mode(self) -> bool:
        return self._is_trigger_mode

    # ---------- 参数读写 ----------

    def get_float_param(self, name: str) -> Optional[float]:
        if self._camera is None:
            return None
        try:
            st_param = MVCC_FLOATVALUE()
            ctypes.memset(ctypes.byref(st_param), 0, ctypes.sizeof(MVCC_FLOATVALUE))
            ret = self._camera.MV_CC_GetFloatValue(name, st_param)
            if ret == MV_OK:
                return st_param.fCurValue
            return None
        except Exception as e:
            log_error(f"获取参数 {name} 异常: {e}")
            return None

    def set_float_param(self, name: str, value: float) -> bool:
        if self._camera is None:
            return False
        try:
            ret = self._camera.MV_CC_SetFloatValue(name, float(value))
            return ret == MV_OK
        except Exception as e:
            log_error(f"设置参数 {name} 异常: {e}")
            return False

    def get_int_param(self, name: str) -> Optional[int]:
        if self._camera is None:
            return None
        try:
            st_param = MVCC_INTVALUE()
            ctypes.memset(ctypes.byref(st_param), 0, ctypes.sizeof(MVCC_INTVALUE))
            ret = self._camera.MV_CC_GetIntValue(name, st_param)
            if ret == MV_OK:
                return st_param.nCurValue
            return None
        except Exception as e:
            log_error(f"获取参数 {name} 异常: {e}")
            return None

    def set_int_param(self, name: str, value: int) -> bool:
        if self._camera is None:
            return False
        try:
            ret = self._camera.MV_CC_SetIntValue(name, value)
            return ret == MV_OK
        except Exception as e:
            log_error(f"设置参数 {name} 异常: {e}")
            return False

    def get_enum_param(self, name: str) -> Optional[int]:
        if self._camera is None:
            return None
        try:
            st_param = MVCC_ENUMVALUE()
            ctypes.memset(ctypes.byref(st_param), 0, ctypes.sizeof(MVCC_ENUMVALUE))
            ret = self._camera.MV_CC_GetEnumValue(name, st_param)
            if ret == MV_OK:
                return st_param.nCurValue
            return None
        except Exception as e:
            log_error(f"获取枚举参数 {name} 异常: {e}")
            return None

    def set_enum_param(self, name: str, value: int) -> bool:
        if self._camera is None:
            return False
        try:
            ret = self._camera.MV_CC_SetEnumValue(name, value)
            return ret == MV_OK
        except Exception as e:
            log_error(f"设置枚举参数 {name} 异常: {e}")
            return False

    # ---------- 常用参数快捷方法 ----------

    def get_exposure_time(self) -> Optional[float]:
        return self.get_float_param("ExposureTime")

    def set_exposure_time(self, value_us: float) -> bool:
        if self._camera is None:
            return False
        self.set_enum_param("ExposureAuto", 0)
        time.sleep(0.05)
        return self.set_float_param("ExposureTime", value_us)

    def get_gain(self) -> Optional[float]:
        return self.get_float_param("Gain")

    def set_gain(self, value_db: float) -> bool:
        if self._camera is None:
            return False
        self.set_enum_param("GainAuto", 0)
        time.sleep(0.05)
        return self.set_float_param("Gain", value_db)

    def get_frame_rate(self) -> Optional[float]:
        return self.get_float_param("AcquisitionFrameRate")

    def set_frame_rate(self, value_fps: float) -> bool:
        return self.set_float_param("AcquisitionFrameRate", value_fps)

    # ---------- 取流控制 ----------

    def start_grabbing(self, frame_callback: Callable = None) -> bool:
        """
        开始采集图像。

        Args:
            frame_callback: 可选的回调函数，接收 (width, height, pixel_type, img_bytes)

        Returns:
            bool: 是否成功开始采集
        """
        if self._camera is None:
            log_error("相机未打开，无法开始采集")
            return False

        if self._is_grabbing:
            log_info("已在采集中")
            return True

        try:
            ret = self._camera.MV_CC_StartGrabbing()
            if ret != MV_OK:
                log_error(f"开始采集失败: {error_code_to_hex(ret)}")
                return False

            self._grabbing_thread = CameraGrabbingThread(self._camera)
            if frame_callback is not None:
                self._grabbing_thread.frame_received.connect(frame_callback)
            self._grabbing_thread.start()
            self._is_grabbing = True

            log_info("开始采集图像")
            return True

        except Exception as e:
            log_error(f"开始采集异常: {e}")
            return False

    def stop_grabbing(self):
        try:
            if self._grabbing_thread is not None:
                self._grabbing_thread.stop()
                self._grabbing_thread = None

            if self._camera is not None and self._is_grabbing:
                self._camera.MV_CC_StopGrabbing()
                self._is_grabbing = False
                log_info("停止采集图像")
        except Exception as e:
            log_error(f"停止采集异常: {e}")

    # ---------- 单次拍照 ----------

    def capture_once(self, timeout_ms: int = 3000) -> Optional[Tuple[int, int, int, bytes]]:
        """
        单次拍照（软触发模式）。

        Args:
            timeout_ms: 等待图像的超时时间（毫秒）

        Returns:
            (width, height, pixel_type, img_bytes) 或 None
        """
        if self._camera is None:
            return None

        try:
            was_continuous = not self._is_trigger_mode
            if was_continuous:
                was_grabbing = self._is_grabbing
                if was_grabbing:
                    self.stop_grabbing()
                self.set_trigger_mode(True)
                self._camera.MV_CC_StartGrabbing()
                time.sleep(0.1)

            ret = self._camera.MV_CC_SetCommandValue("TriggerSoftware")
            if ret != MV_OK:
                log_error(f"软触发失败: {error_code_to_hex(ret)}")
                if was_continuous:
                    self.stop_grabbing()
                    self.set_trigger_mode(False)
                return None

            st_frame = MV_FRAME_OUT()
            ctypes.memset(ctypes.byref(st_frame), 0, ctypes.sizeof(MV_FRAME_OUT))
            ret = self._camera.MV_CC_GetImageBuffer(st_frame, timeout_ms)

            if ret == MV_OK:
                frame_info = st_frame.stFrameInfo
                width = frame_info.nWidth
                height = frame_info.nHeight
                pixel_type = frame_info.enPixelType
                frame_len = frame_info.nFrameLen

                if st_frame.pBufAddr and frame_len > 0:
                    buf = (ctypes.c_ubyte * frame_len).from_address(
                        ctypes.addressof(st_frame.pBufAddr.contents))
                    img_bytes = bytes(buf)
                else:
                    img_bytes = b""

                self._camera.MV_CC_FreeImageBuffer(st_frame)

                if was_continuous:
                    self.stop_grabbing()
                    self.set_trigger_mode(False)
                    self._camera.MV_CC_StartGrabbing()
                    self._is_grabbing = True

                return (width, height, pixel_type, img_bytes)
            else:
                log_error(f"获取图像超时或失败: {error_code_to_hex(ret)}")
                if was_continuous:
                    self.stop_grabbing()
                    self.set_trigger_mode(False)
                return None

        except Exception as e:
            log_error(f"单次拍照异常: {e}")
            return None

    # ---------- 图像显示辅助 ----------

    @staticmethod
    def convert_to_qimage(width: int, height: int, pixel_type: int,
                          img_bytes: bytes) -> Optional[QImage]:
        """
        将相机帧数据转换为 QImage。

        Args:
            width: 图像宽度
            height: 图像高度
            pixel_type: 像素格式枚举值
            img_bytes: 原始帧字节数据

        Returns:
            QImage 对象，失败返回 None
        """
        try:
            if pixel_type == PixelType_Gvsp_Mono8:
                return QImage(img_bytes, width, height, width, QImage.Format_Grayscale8)
            else:
                cv_img = raw_to_opencv(img_bytes, width, height, pixel_type)
                if cv_img is None:
                    return None
                if len(cv_img.shape) == 2:
                    h, w = cv_img.shape
                    return QImage(cv_img.data, w, h, w, QImage.Format_Grayscale8)
                else:
                    h, w, ch = cv_img.shape
                    rgb_img = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
                    return QImage(rgb_img.data, w, h, ch * w, QImage.Format_RGB888)
        except Exception as e:
            log_error(f"转换为 QImage 失败: {e}")
            return None

    @staticmethod
    def display_on_label(label, width: int, height: int, pixel_type: int,
                         img_bytes: bytes):
        """
        将相机帧数据显示在 QLabel 上（自动缩放）。

        Args:
            label: QLabel 控件
            width: 图像宽度
            height: 图像高度
            pixel_type: 像素格式枚举值
            img_bytes: 原始帧字节数据
        """
        try:
            qimg = CameraManager.convert_to_qimage(width, height, pixel_type, img_bytes)
            if qimg is None:
                return
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(label.size(), aspectRatioMode=True,
                                   transformMode=True)
            label.setPixmap(scaled)
        except Exception as e:
            log_error(f"显示图像失败: {e}")

    # ---------- 属性 ----------

    @property
    def is_open(self) -> bool:
        return self._camera is not None

    @property
    def is_grabbing(self) -> bool:
        return self._is_grabbing

    @property
    def device_info(self) -> Optional[Dict[str, Any]]:
        return self._device_info

    @property
    def camera_handle(self):
        return self._camera
