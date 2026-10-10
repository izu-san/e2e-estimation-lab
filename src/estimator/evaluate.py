"""評価ランナー。期待事項（人が用意・レビューしたもの）と実行結果を照合する。

- 期待事項は実行時AIの出力から独立したファイル（evals/expectations/）に置く。
- 期待事項の review_status が human_reviewed でなければ、結果は「暫定」として扱う。
- 件数は評価資料にだけ書き、解析ロジックには持ち込まない。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .calculate import calculate
from .io_utils import read_json, sha256_file, sha256_json
from .items import load_normalized
from .run import ROOT, runs_root
from .validate import validate_normalize


def _find_run(input_path: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        p = p if p.is_absolute() else ROOT / p
        return p if p.is_dir() else None
    if not input_path.exists():
        return None
    sha = sha256_file(input_path)
    cands = []
    for m in runs_root().glob("*/manifest.json"):
        man = read_json(m)
        if len(man["inputs"]) == 1 and man["inputs"][0]["sha256"] == sha:
            cands.append((man["created_at"], m.parent))
    return sorted(cands)[-1][1] if cands else None


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
        checks.append({"check": "calculation_reproducible",
                       "ok": sha256_json(re) == sha256_json(read_json(rd / "estimate.json"))})
    if (rd / "validation.json").exists():
        v = read_json(rd / "validation.json")
        want = e.get("machine_validation", "passed")
        checks.append({"check": "machine_validation", "ok": v["status"]["machine_validation"] == want,
                       "actual": v["status"]})
    return checks


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
    return {"suite": suite.get("suite_id"), "status": "passed" if all_ok else "incomplete_or_failed",
            "results": results}
