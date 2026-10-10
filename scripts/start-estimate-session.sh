#!/usr/bin/env bash
# 見積もりモードの起動（外側のランナー）。
#   1. 前提の確認（claude。--sandbox のときは bwrap/socat も。不足なら起動しない）
#   2. init-run / extract（決定的処理）
#   3. run専用の権限設定を生成
#   4. claude をその設定・dontAskで起動し /estimate-e2e --run <id> を実行
# 使い方:
#   scripts/start-estimate-session.sh --input inputs/foo.xlsx --config config/estimate.yaml [--print] [--headless] [--sandbox]
#   既定は権限ルール＋Hook（OS非依存）。--sandbox でOSサンドボックスを追加（Linux/WSL2: bubblewrap+socat）
#   scripts/start-estimate-session.sh --project inputs/project.yaml --config config/estimate.yaml
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

INPUT_ARGS=(); CONFIG=""; PRINT_ONLY=0; HEADLESS=0; SANDBOX=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --input|--project) INPUT_ARGS=("$1" "$2"); shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --print) PRINT_ONLY=1; shift ;;
    --headless) HEADLESS=1; shift ;;
    --sandbox) SANDBOX=1; shift ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done
[[ ${#INPUT_ARGS[@]} -eq 2 && -n "$CONFIG" ]] || { echo "--input/--project と --config が必要です" >&2; exit 2; }

missing=()
need=(claude); [[ $SANDBOX -eq 1 ]] && need+=(bwrap socat)
for bin in "${need[@]}"; do command -v "$bin" >/dev/null 2>&1 || missing+=("$bin"); done
if [[ ${#missing[@]} -gt 0 && $PRINT_ONLY -eq 0 ]]; then
  echo "見積もりモードに必要なコマンドがありません: ${missing[*]}" >&2
  echo "--sandbox にはLinux/WSL2で 'sudo apt-get install bubblewrap socat' が必要です（README参照）。" >&2
  exit 3
fi

out="$(scripts/estimator init-run "${INPUT_ARGS[@]}" --config "$CONFIG")" || { echo "$out"; echo "init-runで問題がありました（上記を確認）" >&2; }
run_id="$(printf '%s' "$out" | .venv/bin/python -B -c 'import json,sys; print(json.load(sys.stdin).get("run_id",""))')"
[[ -n "$run_id" ]] || { echo "$out" >&2; exit 2; }
run_dir="$("$ROOT/.venv/bin/python" -B -c 'import os,sys; print(os.path.join(os.environ.get("ESTIMATOR_RUNS_DIR", "runs"), sys.argv[1]))' "$run_id")"
scripts/estimator extract --run "$run_id" >/dev/null
sb_args=(); [[ $SANDBOX -eq 1 ]] && sb_args=(--sandbox)
settings="$(.venv/bin/python -B scripts/make_session_settings.py --run-dir "$run_dir" ${sb_args[@]+"${sb_args[@]}"})"

echo "run_id:   $run_id"
echo "settings: $settings"
CMD=(claude --settings "$settings" --permission-mode dontAsk)
PROMPT="/estimate-e2e --run $run_id"
if [[ $PRINT_ONLY -eq 1 ]]; then
  printf '起動コマンド: '; printf '%q ' "${CMD[@]}" "$PROMPT"; echo
  exit 0
fi
export ESTIMATOR_CLAUDE_VERSION="$(claude --version 2>/dev/null | head -1)"
if [[ $HEADLESS -eq 1 ]]; then
  exec "${CMD[@]}" -p "$PROMPT"
fi
exec "${CMD[@]}" "$PROMPT"
