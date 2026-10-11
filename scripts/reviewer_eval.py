#!/usr/bin/env python3
"""estimate-reviewer のライブ評価（claude -p を呼ぶ。モデル利用が発生する）。設計: docs/reviewer_agent_test_design.md

使い捨てディレクトリに本体だけをコピーして実行する。期待値・シナリオ・baseline は置かない
（エージェントは Grep/Glob で答えを読めてしまうため）。run 名もシナリオの内容が分からない名前にする。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

import yaml  # noqa: E402
from helpers import build_cases_standard, build_common_standard, build_customer, write_config  # noqa: E402

from estimator.reviewer_eval import (EVAL_DIR, apply_customer_edits, apply_scenario, extract_json, judge,  # noqa: E402
                                     load_scenarios, summarize)

STAGES = ("normalize", "screens", "common_design", "questions", "assessments")
PROMPT = "{rd} の意味レビューを実施し、JSONで指摘を返してください。"


def sh(args, cwd, timeout=120):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def tree_hash(rd: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(rd.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(rd)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def build_workspace(d: Path) -> Path:
    for name in ("src", "scripts", "schemas", "config", ".claude"):
        shutil.copytree(ROOT / name, d / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("CLAUDE.md", "pyproject.toml"):
        shutil.copy(ROOT / name, d / name)
    (d / ".venv").symlink_to(ROOT / ".venv")
    for sub in ("inputs", "standards", "runs"):
        (d / sub).mkdir()
    ap = d / "config/standards_adapter.yaml"
    ad = yaml.safe_load(ap.read_text(encoding="utf-8"))
    for k in ("cases", "common"):
        ad[k]["approved_text_fingerprint"] = None  # 人工基準なので正本の承認値は外す
    ap.write_text(yaml.safe_dump(ad, allow_unicode=True), encoding="utf-8")
    build_cases_standard(d / "standards/cases_v0.1.xlsx")
    build_common_standard(d / "standards/common_v0.1.xlsx")
    return write_config(d / "config/estimate.yaml", "standards/cases_v0.1.xlsx", "standards/common_v0.1.xlsx",
                        "config/standards_adapter.yaml")


def prepare_run(d: Path, cfg: Path, run_id: str, scenario: dict) -> str | None:
    """run を作り、機械検証まで通す。失敗時は理由を返す。"""
    xlsx = build_customer(d / f"inputs/{run_id}.xlsx")
    apply_customer_edits(xlsx, scenario)
    est = d / "scripts/estimator"
    for args in (["init-run", "--input", str(xlsx), "--config", str(cfg), "--run-id", run_id], ["extract", "--run", run_id]):
        code, out, err = sh([est, *args], d)
        if code:
            return f"{args[0]} 失敗: {out[:300]}{err[:300]}"
    apply_scenario(EVAL_DIR / "baseline", d / "runs" / run_id / "ai", scenario)
    steps = [["validate-stage", "--run", run_id, "--stage", s] for s in STAGES]
    steps += [["calculate", "--run", run_id], ["validate", "--run", run_id]]
    for args in steps:
        code, out, _ = sh([est, *args], d)
        if code:
            return f"{' '.join(args)} 失敗: {out[:300]}"
    return None


def review(d: Path, run_id: str, model: str | None) -> dict:
    rd = d / "runs" / run_id
    cmd = ["claude", "-p", "--agent", "estimate-reviewer", "--output-format", "json", "--permission-mode", "dontAsk",
           "--max-turns", "30"]
    if model:
        cmd += ["--model", model]
    before = tree_hash(rd)
    t0 = time.time()
    try:
        p = subprocess.run([*cmd, PROMPT.format(rd=f"runs/{run_id}")], cwd=d, capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "files_unchanged": tree_hash(rd) == before}
    info = {"seconds": round(time.time() - t0), "exit": p.returncode, "files_unchanged": tree_hash(rd) == before}
    try:
        o = json.loads(p.stdout)
        info.update(text=o.get("result", ""), cost_usd=o.get("total_cost_usd"), turns=o.get("num_turns"))
    except json.JSONDecodeError:
        info.update(text=p.stdout, stderr=p.stderr[:500])
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="カンマ区切りのシナリオID（baseline も指定可）")
    ap.add_argument("--model")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    suite = yaml.safe_load((EVAL_DIR / "suite.yaml").read_text(encoding="utf-8"))
    only = set(a.only.split(",")) if a.only else None
    items = [{"id": "baseline", "kind": "baseline", "changes": []}] + [{"kind": "scenario", **s} for s in load_scenarios()]
    items = [s for s in items if not only or s["id"] in only]
    d = Path(tempfile.mkdtemp(prefix="estimator-reveval."))
    results = []
    try:
        cfg = build_workspace(d)
        for i, sc in enumerate(items, 1):
            run_id = f"r{i:02d}"  # シナリオの内容が分からない名前
            r = {"id": sc["id"], "kind": sc["kind"], "run": run_id, "description": sc.get("description", "")}
            err = prepare_run(d, cfg, run_id, sc)
            if err:
                r.update(setup_error=err, format_ok=False, files_unchanged=False, judge=judge("", sc.get("expect")))
            else:
                info = review(d, run_id, a.model)
                ex = None if sc["kind"] == "baseline" else sc["expect"]
                r.update(info, judge=judge(info.get("text", ""), ex))
                obj = extract_json(info.get("text", ""))
                r["format_ok"] = False
                if obj is not None:  # 既存の検証器で形式・ID実在を確かめる
                    rd = d / "runs" / run_id
                    (rd / "ai/semantic_review.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
                    code, out, _ = sh([d / "scripts/estimator", "validate-stage", "--run", run_id, "--stage", "semantic_review"], d)
                    r["format_ok"] = code == 0
                    if code:
                        r["format_errors"] = out[:500]
                    r["findings_detail"] = obj.get("findings", [])
            print(f"[{sc['id']}] detected={r['judge'].get('detected')} target_hit={r['judge'].get('target_hit')} "
                  f"findings={r['judge']['findings']} format_ok={r['format_ok']} unchanged={r['files_unchanged']}"
                  + (f" SETUP_ERROR {r['setup_error']}" if r.get("setup_error") else ""), flush=True)
            results.append(r)
    finally:
        if a.keep:
            print(f"検証ディレクトリ: {d}")
        else:
            shutil.rmtree(d, ignore_errors=True)
    summary = summarize(results, suite.get("thresholds", {}))
    out = ROOT / "runs" / f"reviewer_eval_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"結果: {out}")
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
