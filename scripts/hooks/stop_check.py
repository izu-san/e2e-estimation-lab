#!/usr/bin/env python3
"""Stop: 見積もりモードで必須成果物が欠けていれば1回だけ通知する。無限ループ防止のため
stop_hook_active が立っている場合と、通知上限（2回）到達後は止めない。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import active_run_dir, emit, read_input  # noqa: E402

REQUIRED = ["estimate.json", "validation.json", "estimate.xlsx", "summary.md", "ai/questions.json"]
MAX_NOTIFY = 2


def main() -> int:
    rd = active_run_dir()
    if rd is None:
        return 0
    data = read_input()
    if data.get("stop_hook_active"):
        return 0
    missing = [r for r in REQUIRED if not (rd / r).exists()]
    if not missing:
        return 0
    counter = rd / "logs" / "stop_hook_count"
    try:
        n = int(counter.read_text()) if counter.exists() else 0
    except ValueError:
        n = MAX_NOTIFY
    if n >= MAX_NOTIFY:
        return 0
    counter.parent.mkdir(exist_ok=True)
    counter.write_text(str(n + 1))
    emit({"decision": "block",
          "reason": f"必須成果物が未作成です: {missing}。工程を続けてください。"
                    "Bash は scripts/estimator <サブコマンド> の単独実行なら使えます（ls/cat・&&・パイプは不可。"
                    "ファイルは Read/Glob/Grep で読む）。scripts/estimator を実際に試しても進めない場合だけ、"
                    f"理由を ai/questions.json と最終報告に記録して終えてください（この通知は最大{MAX_NOTIFY}回）。"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
