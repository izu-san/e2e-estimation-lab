#!/usr/bin/env python3
"""PreToolUse(Bash): 見積もりモードで許可されない Bash を、代わりの手段つきで拒否する。

権限ルール（Bash は scripts/estimator のみ）が主たる防御。dontAsk の拒否文は理由を示さないため、
エージェントが「Bash全体が使えない」と誤解して工程を止めることがあった（2026-10-10 の保護モード初回実行で6件とも停止）。
本フックは許可されない形のコマンドに、使える形と代替ツールを返す。許可の判断は広げない。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from _common import ROOT, active_run_dir, emit, read_input  # noqa: E402

# 先頭が scripts/estimator（相対または絶対）で、複合・置換・パイプを含まないもの
_ESTIMATOR = re.compile(r"^(?:" + re.escape(str(ROOT)) + r"/)?scripts/estimator(?:\s|$)")
_COMPOUND = re.compile(r"&&|\|\||;|\||`|\$\(|\n")

GUIDE = ("見積もりモードで使える Bash は `scripts/estimator <サブコマンド> ...` の単独実行だけです"
         "（`&&`・`;`・パイプ・変数代入・ls/cat 等は不可）。scripts/estimator は使えます。"
         "ファイルの一覧は Glob、内容は Read、検索は Grep を使ってください。"
         "例: scripts/estimator status --run {run} / scripts/estimator render --run {run} --sheet <名> --rows 1-80")


def main() -> int:
    rd = active_run_dir()
    if rd is None:
        return 0
    data = read_input()
    if data.get("tool_name") != "Bash":
        return 0
    cmd = ((data.get("tool_input") or {}).get("command") or "").strip()
    if _ESTIMATOR.match(cmd) and not _COMPOUND.search(cmd):
        return 0  # 許可するかは権限ルールが決める
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": GUIDE.format(run=rd.name),
    }})
    return 0


if __name__ == "__main__":
    sys.exit(main())
