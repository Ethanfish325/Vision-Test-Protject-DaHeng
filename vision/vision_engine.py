# -*- coding: utf-8 -*-
import os
import json
import time
from typing import Optional, Tuple, List, Any
import numpy as np
import cv2

from .pipeline import Pipeline
from .tools.base_tool import ToolResult
from core.paths import ERRORS_DIR
from core.log_manager import log_error, log_info


class VisionEngine:
    def __init__(self):
        self._pipeline: Optional[Pipeline] = None
        self._last_results: List[ToolResult] = []

    @property
    def pipeline(self) -> Optional[Pipeline]:
        return self._pipeline

    def set_pipeline(self, pipeline: Pipeline):
        self._pipeline = pipeline

    def clear_pipeline(self):
        self._pipeline = None

    def execute(self, cv_image: np.ndarray, scheme_name: str = "",
                product_id: str = "") -> Tuple[bool, str, np.ndarray]:
        if self._pipeline is None:
            return False, "未设置流水线", cv_image

        try:
            passed, results, current_image = self._pipeline.execute(cv_image)
            self._last_results = results

            annotated = current_image.copy()
            for r in results:
                if r.processed_image is not None:
                    annotated = r.processed_image.copy()

            if passed:
                message = "检测通过 (OK)"
                log_info(f"检测OK | 方案={scheme_name} | 产品={product_id}")
            else:
                message = "检测失败 (NG)"
                log_info(f"检测NG | 方案={scheme_name} | 产品={product_id}")
                self._save_error_data(scheme_name, product_id, cv_image,
                                      annotated, results)

            return passed, message, annotated

        except Exception as e:
            error_msg = f"检测执行异常: {str(e)}"
            log_error(error_msg)
            self._last_results = []
            return False, error_msg, cv_image

    def get_last_results(self) -> List[ToolResult]:
        return self._last_results

    def _save_error_data(self, scheme_name, product_id, raw_image,
                         annotated_image, results):
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            date_str = time.strftime("%Y-%m-%d")
            date_dir = os.path.join(ERRORS_DIR, date_str)
            os.makedirs(date_dir, exist_ok=True)

            safe_name = scheme_name.replace("/", "_").replace("\\", "_") or "未命名"
            prefix = f"{safe_name}_{timestamp}"

            raw_path = os.path.join(date_dir, f"{prefix}_raw.jpg")
            cv2.imwrite(raw_path, raw_image)

            result_path = os.path.join(date_dir, f"{prefix}_result.jpg")
            cv2.imwrite(result_path, annotated_image)

            json_path = os.path.join(date_dir, f"{prefix}.json")
            error_data = {
                "scheme": scheme_name,
                "product_id": product_id,
                "timestamp": timestamp,
                "results": []
            }
            for r in results:
                error_data["results"].append({
                    "success": r.success,
                    "passed": r.passed,
                    "message": r.message,
                    "data": {k: (float(v) if isinstance(v, (np.floating,)) else
                                 int(v) if isinstance(v, (np.integer,)) else v)
                             for k, v in r.data.items()}
                })
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(error_data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            log_error(f"保存错误数据失败: {e}")
