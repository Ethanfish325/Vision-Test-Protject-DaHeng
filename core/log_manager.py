# -*- coding: utf-8 -*-

import logging
import os
from logging.handlers import TimedRotatingFileHandler

from core.paths import LOGS_DIR


class LogManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._logger = None
        self._setup_logger()

    def _setup_logger(self):
        os.makedirs(LOGS_DIR, exist_ok=True)

        self._logger = logging.getLogger('VisionSystem')
        self._logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        log_file = os.path.join(LOGS_DIR, 'vision_system.log')
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        return self._logger


_log_manager = LogManager()


def init_logger():
    pass


def get_logger() -> logging.Logger:
    return _log_manager.get_logger()


def log_debug(msg: str):
    get_logger().debug(msg)


def log_info(msg: str):
    get_logger().info(msg)


def log_warning(msg: str):
    get_logger().warning(msg)


def log_error(msg: str):
    get_logger().error(msg)


def log_critical(msg: str):
    get_logger().critical(msg)


def log_exception(msg: str):
    get_logger().exception(msg)
