"""Hooks共通処理。見積もりモード（ESTIMATOR_MODE=estimate）かつ進行中runがある場合だけ動作する。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def active_run_dir() -> Path | None:
    if os.environ.get("ESTIMATOR_MODE") != "estimate":
        return None
    rd = os.environ.get("ESTIMATOR_RUN_DIR")
    if not rd:
        return None
    p = Path(rd).resolve()
    return p if p.is_dir() else None


def read_input() -> dict:
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))
