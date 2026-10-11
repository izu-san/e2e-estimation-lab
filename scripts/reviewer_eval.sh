#!/usr/bin/env bash
# estimate-reviewer のライブ評価。claude -p を（baseline＋シナリオ数）回呼ぶ。モデル利用が発生する。
#   scripts/reviewer_eval.sh [--only RV-03,baseline] [--model MODEL] [--keep]
# 設計: docs/reviewer_agent_test_design.md
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/.venv/bin/python" -B "$ROOT/scripts/reviewer_eval.py" "$@"
