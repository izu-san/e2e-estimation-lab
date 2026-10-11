"""計算規則の版の上げ忘れを検出する。

固定の人工入力で calculate の結果（architectures）を指紋にし、tests/golden/calculate_fingerprint.json と照合する。
- 版が同じなのに結果が変わった → 計算ロジックを変えたのに CASE/COMMON_RULE_VERSION を上げていない
- 版が変わった → 意図した変更。`UPDATE_GOLDEN=1 uv run pytest tests/test_calc_version.py` で指紋を更新する
"""

import json
import os
from pathlib import Path

from estimator import CASE_RULE_VERSION, COMMON_RULE_VERSION
from estimator.calculate import calculate, compare_estimate
from estimator.io_utils import sha256_json

GOLDEN = Path(__file__).parent / "golden" / "calculate_fingerprint.json"
AX = ["AX-01", "AX-02", "AX-03", "AX-04", "AX-05"]


def _inputs():
    def ax(*s):
        return {a: {"score": v, "condition": "c", "evidence": "e"} for a, v in zip(AX, s)}

    def case(cid, **kw):
        return {"case_id": cid, "title": cid, "source_item_ids": [f"I-{cid}"], "relation": "one_to_one",
                "summary": "", "steps": ["s"], "expected": ["e"], "step_count": 1, "assertion_count": 1,
                "data_pattern_count": 1, **kw}

    def item(iid, **kw):
        return {"item_id": iid, "original_id": iid, "id_assigned": False, "region_ids": ["R"],
                "refs": [{"workbook_id": "W1", "sheet": "S", "range": "A1"}], "title": iid, "step_count": 1,
                "expected_count": 1, "data_pattern_count": 1, "disposition": "mapped", "duplicate_of": None,
                "reason": "", **kw}

    cids = ["C-1", "C-2", "C-3", "C-4", "C-5", "C-6"]
    norm = {"schema_version": 1, "regions": [],
            "source_items": [item(f"I-{c}") for c in cids[:-1]]
            + [item("I-C-6", pending_parts=[{"summary": "スマホ表示の確認", "question_ids": ["Q-1"]}])],
            "cases": [case(c) for c in cids]}

    def ca(cid, axes, **kw):
        return {"case_id": cid, "arch_ids": ["A1"], "scope": "対象内", "scope_reason": "", "feasibility": "feasible",
                "info_sufficient": True, "axes": axes, "estimate_status": "確定可能", "rationale": "r", **kw}

    assess = {"schema_version": 1, "case_assessments": [
        ca("C-1", ax(1, 1, 1, 1, 1)),
        ca("C-2", ax(2, 2, 1, 2, 1), estimate_status="条件付き", conditions=["x"]),
        ca("C-3", ax(3, 1, 1, 1, 1)),
        ca("C-4", ax(1, 1, None, 1, 1), info_sufficient=False, estimate_status="要確認"),
        ca("C-5", ax(1, 1, 1, 1, 1), scope="別見積", scope_reason="r"),
        ca("C-6", ax(1, 1, 1, 1, 1), feasibility="impossible_confirmed", impossible_reason="r"),
    ], "common_assessments": [
        {"component_id": k, "difficulty": d, "matched_conditions": "m", "rationale": "r", "estimate_status": s}
        for k, d, s in (("BASE-1", "Low", "確定可能"), ("PAGE-1", "Mid", "条件付き"), ("FLOW-1", None, "要確認"),
                        ("REUSE-1", "Low", "確定可能"), ("POC-1", "Impossible", "確定可能"))]}
    base = {"responsibility": "r", "need_reason": "n", "used_by": [], "depends_on": [], "integrated_into": None,
            "arch_ids": ["A1"], "implementation_kind": "新規"}
    comps = [
        {**base, "component_id": "BASE-1", "type_id": "BASE", "name": "b", "elements": ["BASE"], "cost_owner": "BASE-1"},
        {**base, "component_id": "PAGE-1", "type_id": "PAGE", "name": "p", "elements": ["P1", "P2"], "cost_owner": "PAGE-1"},
        {**base, "component_id": "AUTH-1", "type_id": "AUTH", "name": "a", "elements": ["A"], "cost_owner": "PAGE-1",
         "integrated_into": "PAGE-1"},
        {**base, "component_id": "FLOW-1", "type_id": "FLOW", "name": "f", "elements": ["F"], "cost_owner": "FLOW-1"},
        {**base, "component_id": "REUSE-1", "type_id": "UTIL", "name": "u", "elements": ["U"], "cost_owner": "REUSE-1",
         "implementation_kind": "既存流用", "reuse_verified": True, "reuse_integration_owner": "BASE-1"},
        {**base, "component_id": "CI-1", "type_id": "CI", "name": "c", "elements": ["CI"], "cost_owner": "CI-1",
         "implementation_kind": "要確認"},
        {**base, "component_id": "DOC-1", "type_id": "DOC", "name": "d", "elements": ["D"], "cost_owner": "DOC-1",
         "implementation_kind": "対象外", "exclusion_reason": "r"},
        {**base, "component_id": "POC-1", "type_id": "POC", "name": "x", "elements": ["X"], "cost_owner": "POC-1"},
    ]
    design = {"schema_version": 1, "architectures": [{"arch_id": "A1", "name": "a", "assumptions": []}],
              "components": comps}
    return norm, design, assess


def _fingerprint(standards) -> dict:
    norm, design, assess = _inputs()
    est = calculate(standards, norm, design, assess, {"scope": {"excluded_type_ids": []}})
    return {"rule_versions": {"cases": CASE_RULE_VERSION, "common": COMMON_RULE_VERSION},
            "architectures_sha256": sha256_json(est["architectures"])}


def test_rule_version_bumped_when_calculation_changes(standards):
    now = _fingerprint(standards)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(now, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    saved = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if saved["rule_versions"] == now["rule_versions"]:
        assert saved["architectures_sha256"] == now["architectures_sha256"], (
            "計算結果が変わりましたが計算規則の版が同じです。src/estimator/__init__.py の CASE/COMMON_RULE_VERSION を上げ、"
            "UPDATE_GOLDEN=1 で指紋を更新してください")
    else:
        assert saved == now, "計算規則の版が変わりました。UPDATE_GOLDEN=1 uv run pytest tests/test_calc_version.py で指紋を更新してください"


def test_compare_estimate_distinguishes_rule_change(standards):
    norm, design, assess = _inputs()
    est = calculate(standards, norm, design, assess, {})
    assert compare_estimate(est, est) == "match"
    relabeled = {**est, "rule_versions": {"cases": "case-rule-0", "common": "common-rule-0"}}
    assert compare_estimate(relabeled, est) == "match"  # 版の表記だけの違いは一致
    changed = json.loads(json.dumps(relabeled))
    changed["architectures"][0]["components"][2]["estimate_status"] = "要確認"
    assert compare_estimate(changed, est) == "rule_version_changed"
    tampered = json.loads(json.dumps(est))
    tampered["architectures"][0]["subtotals"]["computed_total"]["std"] = 1.0
    assert compare_estimate(tampered, est) == "mismatch"
