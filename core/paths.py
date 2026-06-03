# -*- coding: utf-8 -*-

import os
import sys


def _get_data_dir() -> str:
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, 'data')


DATA_DIR = _get_data_dir()
SCHEME_DIR = os.path.join(DATA_DIR, 'schemes')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
ERRORS_DIR = os.path.join(DATA_DIR, 'errors')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')


def ensure_dirs():
    for d in [DATA_DIR, SCHEME_DIR, ERRORS_DIR, LOGS_DIR]:
        os.makedirs(d, exist_ok=True)
