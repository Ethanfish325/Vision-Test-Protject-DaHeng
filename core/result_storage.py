# -*- coding: utf-8 -*-

import csv
import json
import os
from datetime import datetime, timedelta
from typing import List, Optional

from core.paths import ERRORS_DIR, LOGS_DIR


class ResultStorage:
    def __init__(self):
        self._error_dir = ERRORS_DIR
        os.makedirs(self._error_dir, exist_ok=True)

    def save_error_data(self, scheme_name: str, product_id: str,
                        raw_image, result_image,
                        tool_results: List[dict], judge_result: bool):
        date_str = datetime.now().strftime('%Y-%m-%d')
        date_dir = os.path.join(self._error_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)

        prefix = f"{scheme_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        raw_path = os.path.join(date_dir, f"{prefix}_raw.jpg")
        import cv2
        cv2.imwrite(raw_path, raw_image)

        result_path = os.path.join(date_dir, f"{prefix}_result.jpg")
        cv2.imwrite(result_path, result_image)

        json_data = {
            'scheme_name': scheme_name,
            'product_id': product_id,
            'timestamp': datetime.now().isoformat(),
            'judge_result': judge_result,
            'tool_results': tool_results
        }
        json_path = os.path.join(date_dir, f"{prefix}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        self._append_to_csv(date_dir, date_str, {
            '时间': datetime.now().strftime('%H:%M:%S'),
            '方案': scheme_name,
            '产品ID': product_id,
            '判定': 'NG',
            '备注': ''
        })

    def _append_to_csv(self, date_dir: str, date_str: str, data: dict):
        csv_path = os.path.join(date_dir, f"{date_str}.csv")
        file_exists = os.path.exists(csv_path)
        with open(csv_path, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=list(data.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)

    def save_ok_log(self, scheme_name: str, product_id: str,
                    tool_results: List[dict], judge_result: bool):
        date_str = datetime.now().strftime('%Y-%m-%d')
        log_path = os.path.join(LOGS_DIR, f"ok_log_{date_str}.csv")
        file_exists = os.path.exists(log_path)

        with open(log_path, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(['时间', '方案', '产品ID', '判定', '工具结果'])
            writer.writerow([
                datetime.now().strftime('%H:%M:%S'),
                scheme_name,
                product_id,
                'OK',
                json.dumps(tool_results, ensure_ascii=False)
            ])

    def clean_old_data(self, retention_days: int = 90):
        cutoff = datetime.now() - timedelta(days=retention_days)
        if not os.path.exists(self._error_dir):
            return
        for dir_name in os.listdir(self._error_dir):
            dir_path = os.path.join(self._error_dir, dir_name)
            if not os.path.isdir(dir_path):
                continue
            try:
                dir_date = datetime.strptime(dir_name, '%Y-%m-%d')
                if dir_date < cutoff:
                    import shutil
                    shutil.rmtree(dir_path)
            except ValueError:
                continue
