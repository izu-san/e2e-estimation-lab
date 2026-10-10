"""評価ランナー。期待事項（人が用意・レビューしたもの）と実行結果を照合する。

- 期待事項は実行時AIの出力から独立したファイル（evals/expectations/）に置く。
- 期待事項の review_status が human_reviewed でなければ、結果は「暫定」として扱う。
- 件数は評価資料にだけ書き、解析ロジックには持ち込まない。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .calculate import calculate, compare_estimate
from .io_utils import read_json, sha256_file
from .items import load_normalized
from .run import ROOT, runs_root
from .validate import validate_normalize


def _runs_for(input_path: Path) -> list[Path]:
    """入力ファイルのSHA-256が一致するrun（古い順）。"""
    if not input_path.exists():
        return []
    sha = sha256_file(input_path)
    cands = []
    for m in runs_root().glob("*/manifest.json"):
        man = read_json(m)
        if len(man["inputs"]) == 1 and man["inputs"][0]["sha256"] == sha:
            cands.append((man["created_at"], m.parent))
    return [p for _, p in sorted(cands)]


def _find_run(input_path: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        p = p if p.is_absolute() else ROOT / p
        return p if p.is_dir() else None
    runs = _runs_for(input_path)
    return runs[-1] if runs else None


def _range_check(name: str, actual: int, spec: dict | None) -> dict | None:
    if not spec:
        return None
    ok = spec.get("min", actual) <= actual <= spec.get("max", actual)
    return {"check": name, "ok": ok, "actual": actual, "expected": spec}


def evaluate_run(rd: Path, exp: dict) -> list[dict]:
    checks: list[dict] = []
    norm_p = rd / "ai/normalized_cases.json"
    if not norm_p.exists():
        return [{"check": "normalized_cases_exists", "ok": False}]
    norm = load_normalized(rd)
    e = exp.get("expect", {})
    ne = [x for x in validate_normalize(rd) if x.get("severity", "error") == "error"]
    checks.append({"check": "region_coverage_and_refs", "ok": not ne, "errors": ne[:10]})
    for name, actual in (("source_items", len(norm["source_items"])),
                         ("source_items_mapped", sum(1 for i in norm["source_items"] if i["disposition"] == "mapped")),
                         ("cases", len(norm["cases"])),
                         ("duplicates_recorded", sum(1 for i in norm["source_items"] if i["duplicate_of"])),
                         ("ids_assigned", sum(1 for i in norm["source_items"] if i["id_assigned"]))):
        r = _range_check(name, actual, e.get(name))
        if r:
            checks.append(r)
    roles = {r["region_id"]: r["role"] for r in norm["regions"]}
    for want in e.get("non_test_regions_min", []) or []:
        n = sum(1 for v in roles.values() if v == want["role"])
        checks.append({"check": f"regions_role_{want['role']}", "ok": n >= want["min"], "actual": n, "expected": want})
    text = {c["case_id"]: " ".join([c["title"], c["summary"], *c["steps"], *c["expected"]]) for c in norm["cases"]}
    for t in e.get("required_topics", []) or []:
        hits = [cid for cid, s in text.items() if any(k in s for k in t["keywords"])]
        checks.append({"check": f"topic:{t['name']}", "ok": len(hits) >= t.get("min_cases", 1), "cases": hits})
    for q in e.get("required_question_keywords", []) or []:
        qp = rd / "ai/questions.json"
        items = read_json(qp)["items"] if qp.exists() else []
        hit = [x["question_id"] for x in items if any(k in x["text"] for k in q["keywords"])]
        checks.append({"check": f"question:{q['name']}", "ok": bool(hit), "questions": hit})
    if (rd / "estimate.json").exists() and (rd / "ai/assessments.json").exists():
        man = read_json(rd / "manifest.json")
        re = calculate(read_json(rd / "standards.json"), norm, read_json(rd / "ai/common_design.json"),
                       read_json(rd / "ai/assessments.json"), man["config_resolved"])
        stored = read_json(rd / "estimate.json")
        verdict = compare_estimate(stored, re)
        chk = {"check": "calculation_reproducible", "ok": verdict == "match"}
        if verdict == "rule_version_changed":
            chk["reason"] = (f"計算規則の版が変わったため（estimate: {stored.get('rule_versions')}、現行: {re['rule_versions']}）。"
                             "calculate の再実行で解消し、AIの成果物の問題ではない")
        elif verdict == "mismatch":
            chk["reason"] = "同じ規則の版で結果が異なる（手編集・上流変更、または計算変更時の版の上げ忘れ）"
        checks.append(chk)
    if (rd / "validation.json").exists():
        v = read_json(rd / "validation.json")
        want = e.get("machine_validation", "passed")
        checks.append({"check": "machine_validation", "ok": v["status"]["machine_validation"] == want,
                       "actual": v["status"]})
    return checks


# ------------------------------------------------------------------ 形式横断の一貫性

AI_OUTPUTS = ("ai/normalized_cases.json", "ai/common_design.json", "ai/assessments.json")


def run_metrics(rd: Path) -> dict | None:
    """1runの集計指標（最初の構成案）。同じ内容を別書式で書いた項目書どうしの比較に使う。"""
    if not (rd / "estimate.json").exists():
        return None
    est = read_json(rd / "estimate.json")
    a = est["architectures"][0]
    diff: dict[str, int] = {}
    for c in a["cases"]:
        k = c["difficulty"] or c["category"]
        diff[k] = diff.get(k, 0) + 1
    qp = rd / "ai/questions.json"
    return {
        "arch_id": a["arch_id"],
        "computed_total_std": a["subtotals"]["computed_total"]["std"],
        "cases_std": a["subtotals"]["cases"]["std"],
        "common_std": a["subtotals"]["common"]["std"],
        "cases": len(a["cases"]),
        "case_difficulty": dict(sorted(diff.items())),
        "cases_conditional": a["counts"]["cases"].get("conditional", 0),
        "components_computed": a["counts"]["components"].get("computed", 0),
        "components_total": len(a["components"]),
        "pending_parts": a["counts"].get("pending_parts", 0),
        "unresolved_items": a["counts"]["unresolved_items"],
        "questions": len(read_json(qp)["items"]) if qp.exists() else None,
        "rule_versions": est.get("rule_versions"),
    }


def _item_difficulties(rd: Path) -> dict[str, list[str | None]]:
    """原ID → その原項目から作ったケースの難易度（最初の構成案）。原IDの無い（内部付与）項目は除く。"""
    norm = load_normalized(rd)
    orig = {i["item_id"]: i["original_id"] for i in norm["source_items"] if i["original_id"] and not i["id_assigned"]}
    est = read_json(rd / "estimate.json")
    out: dict[str, list[str | None]] = {}
    for c in est["architectures"][0]["cases"]:
        for sid in c["source_item_ids"]:
            if sid in orig:
                out.setdefault(orig[sid], []).append(c["difficulty"] or c["category"])
    return {k: sorted(v, key=str) for k, v in out.items()}


def _reused_from(rd: Path, earlier: list[Path]) -> str | None:
    """AI成果物のいずれかが前のrunと同一なら、そのrun名（独立した試行として数えない）。"""
    mine = [sha256_file(rd / f) if (rd / f).exists() else None for f in AI_OUTPUTS]
    for prev in reversed(earlier):
        theirs = [sha256_file(prev / f) if (prev / f).exists() else None for f in AI_OUTPUTS]
        if any(m and m == t for m, t in zip(mine, theirs)):
            return prev.name
    return None


def evaluate_consistency(group: dict) -> dict:
    """同じ内容を別書式で書いた項目書群の結果のばらつき。許容幅（tolerances）は人が評価資料に書く。
    許容幅が無ければ report_only（ばらつきを示すだけで合否にしない）。"""
    per_input, latest = [], {}
    for inp in group["inputs"]:
        runs = _runs_for(ROOT / inp)
        trials = []
        for i, rd in enumerate(runs):
            m = run_metrics(rd)
            if m is None:
                continue
            trials.append({"run": rd.name, "reused_ai_outputs_from": _reused_from(rd, runs[:i]), **m})
        label = Path(inp).stem
        per_input.append({"input": inp, "label": label, "runs": trials,
                          "independent_runs": sum(1 for t in trials if not t["reused_ai_outputs_from"])})
        if trials:
            latest[label] = next(rd for rd in runs if rd.name == trials[-1]["run"])
    metrics = {lbl: run_metrics(rd) for lbl, rd in latest.items()}
    spread = {}
    for key in ("computed_total_std", "cases_std", "common_std", "cases", "cases_conditional",
                "components_computed", "pending_parts", "unresolved_items", "questions"):
        vals = {lbl: m[key] for lbl, m in metrics.items() if m and m.get(key) is not None}
        if len(vals) < 2:
            continue
        lo, hi = min(vals.values()), max(vals.values())
        spread[key] = {"min": lo, "max": hi, "abs": hi - lo,
                       "relative": round((hi - lo) / hi, 4) if hi else 0.0, "values": vals}
    items: dict[str, dict[str, list]] = {}
    for lbl, rd in latest.items():
        for oid, diffs in _item_difficulties(rd).items():
            items.setdefault(oid, {})[lbl] = diffs
    disagreements = {oid: v for oid, v in sorted(items.items())
                     if len(v) >= 2 and len({tuple(map(str, d)) for d in v.values()}) > 1}
    checks = []
    tol = group.get("tolerances") or {}
    for key, lim in (tol.get("max_relative_spread") or {}).items():
        if key in spread:
            checks.append({"check": f"relative_spread:{key}", "ok": spread[key]["relative"] <= lim,
                           "actual": spread[key]["relative"], "limit": lim})
    for key, lim in (tol.get("max_abs_spread") or {}).items():
        if key in spread:
            checks.append({"check": f"abs_spread:{key}", "ok": spread[key]["abs"] <= lim,
                           "actual": spread[key]["abs"], "limit": lim})
    if "max_item_disagreements" in tol:
        checks.append({"check": "item_disagreements", "ok": len(disagreements) <= tol["max_item_disagreements"],
                       "actual": len(disagreements), "limit": tol["max_item_disagreements"]})
    rules = {json.dumps(m["rule_versions"], sort_keys=True) for m in metrics.values() if m}
    status = "report_only" if not checks else ("passed" if all(c["ok"] for c in checks) else "failed")
    return {"name": group["name"], "description": group.get("description"), "status": status,
            "compared_runs": {lbl: rd.name for lbl, rd in latest.items()},
            "mixed_rule_versions": len(rules) > 1,
            "spread": spread, "item_difficulty_disagreements": disagreements,
            "items_compared": sum(1 for v in items.values() if len(v) >= 2),
            "checks": checks, "inputs": per_input}


def evaluate_suite(path: Path) -> dict:
    suite = yaml.safe_load(path.read_text(encoding="utf-8"))
    results = []
    all_ok = True
    for entry in suite["runs"]:
        inp = ROOT / entry["input"]
        exp_path = ROOT / entry["expectation"]
        exp = yaml.safe_load(exp_path.read_text(encoding="utf-8")) if exp_path.exists() else None
        rd = _find_run(inp, entry.get("run"))
        res = {"input": entry["input"], "input_exists": inp.exists(), "run": str(rd) if rd else None,
               "expectation": entry["expectation"],
               "expectation_review_status": (exp or {}).get("review_status", "missing")}
        if not inp.exists():
            res.update(status="input_missing")
        elif exp is None:
            res.update(status="expectation_missing")
        elif rd is None:
            res.update(status="not_run")
        else:
            checks = evaluate_run(rd, exp)
            ok = all(c["ok"] for c in checks)
            res.update(status="passed" if ok else "failed", checks=checks)
        if res["status"] != "passed":
            all_ok = False
        if res["expectation_review_status"] != "human_reviewed":
            res["note"] = "期待事項が人確認済みではないため、結果は暫定です"
        results.append(res)
    consistency = [evaluate_consistency(g) for g in suite.get("consistency_groups", []) or []]
    if any(c["status"] == "failed" for c in consistency):
        all_ok = False
    return {"suite": suite.get("suite_id"), "status": "passed" if all_ok else "incomplete_or_failed",
            "results": results, "consistency": consistency}
