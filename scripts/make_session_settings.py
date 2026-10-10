#!/usr/bin/env python3
"""見積もりモード用のClaude Code設定を、runごとに絶対パスで生成する。

生成先は runs/.sessions/<run_id>.settings.json（Edit権限で書込み禁止の領域）。
既定は権限ルール＋Hookのみ（OS非依存）。--sandbox でOSサンドボックスの設定を追加する。
ユーザー設定・既存の .claude/settings.json は変更しない。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render(template: str, root: Path, run_dir: Path, sessions: Path) -> dict:
    # JSON文字列として安全に置換するため、パスはJSONエスケープ済みの値で埋める
    def esc(p: Path) -> str:
        return json.dumps(str(p))[1:-1]
    text = (template.replace("{ROOT}", esc(root)).replace("{RUN_DIR}", esc(run_dir))
            .replace("{SESSIONS_DIR}", esc(sessions)))
    data = json.loads(text)
    data.pop("$comment", None)
    return data


def merge(base: dict, extra: dict) -> dict:
    """extra を base に重ねる。permissions の配列は連結し、それ以外のキーは追加する。"""
    out = json.loads(json.dumps(base))
    for k, v in extra.items():
        if k == "permissions":
            for pk, pv in v.items():
                cur = out.setdefault("permissions", {}).setdefault(pk, [])
                cur += [x for x in pv if x not in cur]
        elif not k.startswith("$"):
            out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--template", default=str(ROOT / "config" / "claude-estimate.settings.json"))
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--sandbox", action="store_true", help="OSサンドボックスの設定を追加する（要: 対応OSと依存）")
    ap.add_argument("--sandbox-template", default=str(ROOT / "config" / "claude-estimate.sandbox.json"))
    a = ap.parse_args()
    root = Path(a.root).resolve()
    run_dir = Path(a.run_dir).resolve()
    if root not in run_dir.parents:
        print(f"run_dir はリポジトリ配下である必要があります: {run_dir}", file=sys.stderr)
        return 2
    sessions = run_dir.parent / ".sessions"
    sessions.mkdir(exist_ok=True)
    data = render(Path(a.template).read_text(encoding="utf-8"), root, run_dir, sessions)
    if a.sandbox:
        data = merge(data, render(Path(a.sandbox_template).read_text(encoding="utf-8"), root, run_dir, sessions))
    out = sessions / f"{run_dir.name}.settings.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
