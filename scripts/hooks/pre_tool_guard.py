#!/usr/bin/env python3
"""PreToolUse: 見積もりモードで、現在のrun以外へのファイル編集ツールの書込みを拒否する補助。

permissionsのdenyルールが主たる防御。本フックは多重防御で、Bashの書込みは扱わない（Bashは許可リストで scripts/estimator のみ。--sandbox 時はsandboxも担当）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from _common import active_run_dir, emit, read_input  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def main() -> int:
    rd = active_run_dir()
    if rd is None:
        return 0
    data = read_input()
    if data.get("tool_name") not in EDIT_TOOLS:
        return 0
    ti = data.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("notebook_path")
    if not target:
        return 0
    p = Path(target)
    if not p.is_absolute():
        p = Path(data.get("cwd") or os.getcwd()) / p
    p = p.resolve()
    if p == rd or rd in p.parents:
        return 0
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"見積もりモードでは現在のrun ({rd}) 以外は書込み禁止です: {p}",
    }})
    return 0


if __name__ == "__main__":
    sys.exit(main())
