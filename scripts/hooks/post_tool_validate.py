#!/usr/bin/env python3
"""PostToolUse: 既知の中間成果物（runs/<id>/ai/*.json）が更新されたときだけ、軽量なスキーマ検証を返す。"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from _common import ROOT, active_run_dir, emit, read_input  # noqa: E402

KNOWN = {"normalized_cases.json": "normalized_cases", "common_design.json": "common_design",
         "assessments.json": "assessments", "questions.json": "questions"}


def main() -> int:
    rd = active_run_dir()
    if rd is None:
        return 0
    data = read_input()
    ti = data.get("tool_input") or {}
    target = ti.get("file_path")
    if not target:
        return 0
    p = Path(target).resolve()
    if p.parent != rd / "ai" or p.name not in KNOWN:
        return 0
    sys.path.insert(0, str(ROOT / "src"))
    from estimator.schemas import schema_errors

    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        errs = schema_errors(KNOWN[p.name], doc)
    except ValueError as e:
        errs = [{"path": "/", "message": f"JSONとして読めません: {e}"}]
    if not errs:
        return 0
    msg = "\n".join(f"{e['path']}: {e['message']}" for e in errs[:15])
    emit({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                 "additionalContext": f"{p.name} のスキーマエラー（{len(errs)}件）:\n{msg}\n"
                                                      f"validate-stage で詳細を確認してください。"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
