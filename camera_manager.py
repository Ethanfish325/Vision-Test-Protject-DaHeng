# -*- coding: utf-8 -*-

import os
import sys
import ctypes
import time
from typing import Optional, Callable, List, Dict, Any
from threading import Lock

from PyQt5.QtCore import QThread, pyqtSignal

from core.paths import DATA_DIR
from core.log_manager import log_error, log_info


PixelType_Gvsp_Mono8 = 0x01000000
PixelType_Gvsp_BayerRG8 = 0x02000000
PixelType_Gvsp_BayerGB8 = 0x02010000
PixelType_Gvsp_BayerBG8 = 0x02020000
PixelType_Gvsp_BayerGR8 = 0x02030000


def _get_mv_import_dir() -> str:
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "MvImport")


def _ensure_mv_dll_path():
    mv_dir = _get_mv_import_dir()
    if os.path.exists(mv_dir) and mv_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = mv_dir + ";" + os.environ.get("PATH", "")


def error_code_to_hex(error_num):
    if error_num < 0:
        return f"-0x{abs(error_num):08X}"
    return f"0x{error_num:08X}"


class CameraGrabbingThread(QThread):

    frame_received = pyqtSignal(int, int, int, bytes)

    def __init__(self, camera_obj):
        super().__init__()
        self._camera = camera_obj
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            try:
                ret, frame_info = self._camera.GetImageBuffer(100)
                if ret == 0 and frame_info:
                    width = frame_info.nWidth
                    height = frame_info.nHeight
                    pixel_type = frame_info.enPixelType
                    img_bytes = bytes(frame_info.pImageBuffer)

                    self.frame_received.emit(width, height, pixel_type, img_bytes)

                    self._camera.FreeImageBuffer(frame_info)
                else:
                    self.msleep(10)
            except Exception as e:
                log_error(f"取流线程异常: {e}")
                self.msleep(100)

    def stop(self):
        self._running = False
        self.wait(2000)


class CameraManager:

    _MvCamera = None

    def __init__(self):
        self._camera = None
        self._device_list = None
        self._grabbing_thread = None
        self._is_grabbing = False
        self._lock = Lock()

    def enumerate_devices(self) -> List[Dict[str, Any]]:
        devices = []
        try:
            if self._MvCamera is None:
                self._load_sdk()

            if self._MvCamera:
                device_list = self._MvCamera.MV_CC_DEVICE_INFO_LIST()
                ret = self._MvCamera.MV_CC_EnumDevices(0x1F, device_list)
                if ret == 0 and device_list.nDeviceNum > 0:
                    for i in range(device_list.nDeviceNum):
                        dev_info = device_list.pDeviceInfo[i]
                        device = {
                            "index": i,
                            "name": self._get_device_name(dev_info),
                            "info": dev_info,
                        }
                        devices.append(device)
        except Exception as e:
            log_error(f"枚举相机失败: {e}")

        return devices

    def _get_device_name(self, dev_info) -> str:
        try:
            if hasattr(dev_info, 'chManufacturerName'):
                return dev_info.chManufacturerName
            elif hasattr(dev_info, 'SpecialInfo'):
                return str(dev_info.SpecialInfo)
            return f"相机 {id(dev_info)}"
        except Exception:
            return "未知设备"

    def open_camera(self, dev_info) -> bool:
        try:
            if self._MvCamera is None:
                self._load_sdk()

            if self._MvCamera:
                self._camera = self._MvCamera()
                ret = self._camera.MV_CC_CreateDevice(dev_info)
                if ret != 0:
                    log_error(f"创建相机设备失败: {error_code_to_hex(ret)}")
                    return False

                ret = self._camera.MV_CC_OpenDevice()
                if ret != 0:
                    log_error(f"打开相机失败: {error_code_to_hex(ret)}")
                    self._camera.MV_CC_DestroyDevice()
                    self._camera = None
                    return False

                log_info("相机打开成功")
                return True
        except Exception as e:
            log_error(f"打开相机异常: {e}")

        return False

    def close_camera(self):
        try:
            self.stop_grabbing()

            if self._camera:
                self._camera.MV_CC_CloseDevice()
                self._camera.MV_CC_DestroyDevice()
                self._camera = None
                log_info("相机关闭成功")
        except Exception as e:
            log_error(f"关闭相机异常: {e}")

    def start_grabbing(self, frame_callback: Callable):
        if self._camera is None or self._is_grabbing:
            return

        try:
            ret = self._camera.MV_CC_StartGrabbing()
            if ret != 0:
                log_error(f"开始取流失败: {error_code_to_hex(ret)}")
                return

            self._grabbing_thread = CameraGrabbingThread(self._camera)
            self._grabbing_thread.frame_received.connect(frame_callback)
            self._grabbing_thread.start()
            self._is_grabbing = True
            log_info("开始取流")
        except Exception as e:
            log_error(f"开始取流异常: {e}")

    def stop_grabbing(self):
        try:
            if self._grabbing_thread:
                self._grabbing_thread.stop()
                self._grabbing_thread = None

            if self._camera and self._is_grabbing:
                self._camera.MV_CC_StopGrabbing()
                self._is_grabbing = False
                log_info("停止取流")
        except Exception as e:
            log_error(f"停止取流异常: {e}")

    def capture_once(self, timeout_ms=3000) -> Optional[tuple]:
        if self._camera is None:
            return None

        try:
            ret = self._camera.MV_CC_SetCommandValue("TriggerSoftware")
            if ret != 0:
                log_error(f"软触发失败: {error_code_to_hex(ret)}")
                return None

            ret, frame_info = self._camera.GetImageBuffer(timeout_ms)
            if ret == 0 and frame_info:
                width = frame_info.nWidth
                height = frame_info.nHeight
                pixel_type = frame_info.enPixelType
                img_bytes = bytes(frame_info.pImageBuffer)

                self._camera.FreeImageBuffer(frame_info)

                return (width, height, pixel_type, img_bytes)
            else:
                log_error(f"获取图像超时或失败: {error_code_to_hex(ret)}")
                return None

        except Exception as e:
            log_error(f"单次拍照异常: {e}")
            return None

    def display_frame(self, widget, width, height, pixel_type, img_bytes):
        try:
            from PyQt5.QtGui import QImage, QPixmap

            if pixel_type == 0x01000000:
                qimg = QImage(img_bytes, width, height, width, QImage.Format_Grayscale8)
            elif pixel_type == 0x02000000:
                import numpy as np
                bayer = np.frombuffer(img_bytes, dtype=np.uint8).reshape((height, width))
                rgb = cv2.cvtColor(bayer, cv2.COLOR_BayerRG2RGB)
                h, w, ch = rgb.shape
                qimg = QImage(rgb.data, w, h, w * ch, QImage.Format_RGB888)
            else:
                qimg = QImage(img_bytes, width, height, width * 3, QImage.Format_RGB888)

            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(widget.size(), aspectRatioMode=True,
                                   transformMode=True)
            widget.setPixmap(scaled)

        except Exception as e:
            log_error(f"显示图像失败: {e}")

    @property
    def is_open(self) -> bool:
        return self._camera is not None

    @staticmethod
    def initialize_sdk():
        _ensure_mv_dll_path()
        log_info("相机SDK初始化完成")

    @staticmethod
    def finalize_sdk():
        log_info("相机SDK反初始化完成")

    def _load_sdk(self):
        try:
            from MvImport.MvCameraControl import MvCamera
            self._MvCamera = MvCamera
            log_info("相机SDK加载成功")
        except ImportError:
            log_info("未找到相机SDK（MvImport），相机功能不可用")
            self._MvCamera = None
