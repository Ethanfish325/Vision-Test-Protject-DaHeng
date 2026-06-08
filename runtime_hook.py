# -*- coding: utf-8 -*-
"""
PyInstaller Runtime Hook
========================
在打包后的程序启动时执行，用于设置 DLL 搜索路径，
确保 MvCameraControl.dll 能被正确加载。
"""
import os
import sys


def _setup_mv_dll_path():
    """
    将 MvImport 目录（包含 MvCameraControl.dll）添加到 DLL 搜索路径中。
    
    打包后目录结构：
        dist/VisionSystem/
            VisionSystem.exe
            _internal/
                MvImport/          <-- MvCameraControl.dll 在这里
                    MvCameraControl_class.py
                    ...
    """
    # 获取当前可执行文件所在目录
    if getattr(sys, 'frozen', False):
        # 打包后的环境
        base_dir = os.path.dirname(sys.executable)
        # DLL 在 _internal/MvImport/ 下
        dll_dir = os.path.join(base_dir, '_internal', 'MvImport')
    else:
        # 开发环境
        dll_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'MvImport')

    if os.path.isdir(dll_dir):
        # 将目录添加到 PATH 环境变量中，使 WinDLL 能搜索到
        os.environ['PATH'] = dll_dir + os.pathsep + os.environ.get('PATH', '')
        print(f"[RuntimeHook] 已添加 DLL 搜索路径: {dll_dir}")
    else:
        print(f"[RuntimeHook] 警告: MvImport 目录不存在: {dll_dir}")


_setup_mv_dll_path()
