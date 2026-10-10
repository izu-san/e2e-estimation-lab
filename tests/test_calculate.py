"""計算・例外処理の単体テスト（10.1）。"""

import copy

import pytest

from estimator.calculate import calc_case, calculate, decide_case_difficulty

AX = ["AX-01", "AX-02", "AX-03", "AX-04", "AX-05"]


def axes(*scores):
    return {a: {"score": s, "condition": "c", "evidence": "e"} for a, s in zip(AX, scores)}


def assess(case_id="C1", scores=(1, 1, 1, 1, 1), **kw):
    a = {"case_id": case_id, "arch_ids": ["A1"], "scope": "対象内", "scope_reason": "", "feasibility": "feasible",
         "info_sufficient": True, "axes": axes(*scores), "estimate_status": "確定可能", "rationale": "r"}
    a.update(kw)
    return a


@pytest.mark.parametrize("scores,expected", [
    ((1, 1, 1, 1, 1), "Low"),          # 全軸1点 → 合計5 ≦ Low上限5
    ((2, 1, 1, 1, 1), "Mid"),          # 1軸のみ2点 → 6
    ((2, 2, 1, 1, 1), "Mid"),          # 2軸2点 → 7
    ((2, 2, 2, 1, 1), "High"),         # 3軸2点 → 8 ≧ High閾値8
    ((3, 1, 1, 1, 1), "High"),         # いずれか3点
    ((1, None, 1, 1, 1), None),        # 未採点
])
def test_case_difficulty_rule(scores, expected):
    assert decide_case_difficulty(list(scores), 5, 8) == expected


def test_case_effort_from_standards(standards):
    row = calc_case(assess(scores=(2, 2, 2, 1, 1)), standards["cases"], AX)
    assert row["difficulty"] == "High"
    assert row["effort"] == {"low": 8.0, "std": 16.0, "high": 24.0}
    assert row["standard_refs"]["effort_std"].startswith("工数標準!")


def test_impossible_and_pending_have_null_effort(standards):
    imp = calc_case(assess(feasibility="impossible_confirmed", impossible_reason="x"), standards["cases"], AX)
    assert imp["difficulty"] == "Impossible" and imp["effort"] == {"low": None, "std": None, "high": None}
    pend = calc_case(assess(scores=(1, None, 1, 1, 1), info_sufficient=False, estimate_status="要確認"),
                     standards["cases"], AX)
    assert pend["difficulty"] is None and pend["category"] == "pending"
    assert pend["effort"]["std"] is None


def test_pending_status_forced(standards):
    row = calc_case(assess(scores=(1, None, 1, 1, 1), info_sufficient=True), standards["cases"], AX)
    assert row["estimate_status"] == "要確認"


def test_out_of_scope_and_separate(standards):
    o = calc_case(assess(scope="対象外", scope_reason="x"), standards["cases"], AX)
    s = calc_case(assess(scope="別見積", scope_reason="x"), standards["cases"], AX)
    assert o["category"] == "out_of_scope" and s["category"] == "separate_estimate"
    assert o["effort"]["std"] is None and s["effort"]["std"] is None


def comp(cid, type_id="PAGE", elements=("P1",), kind="新規", arch=("A1",), owner=None, **kw):
    c = {"component_id": cid, "arch_ids": list(arch), "type_id": type_id, "name": cid, "responsibility": "r",
         "need_reason": "n", "implementation_kind": kind, "elements": list(elements), "used_by": [],
         "depends_on": [], "integrated_into": None, "cost_owner": owner or cid}
    c.update(kw)
    return c


def run_calc(standards, comps, cas, case_assessments=(), cases=(), archs=("A1",), config=None):
    norm = {"schema_version": 1, "regions": [], "source_items": [],
            "cases": [{"case_id": c, "title": c, "source_item_ids": ["S"], "relation": "one_to_one", "summary": "",
                       "steps": [], "expected": [], "step_count": 0, "assertion_count": 0, "data_pattern_count": 1}
                      for c in cases]}
    design = {"schema_version": 1, "architectures": [{"arch_id": a, "name": a, "assumptions": []} for a in archs],
              "components": comps}
    asm = {"schema_version": 1, "case_assessments": list(case_assessments), "common_assessments": cas}
    return calculate(standards, norm, design, asm, config or {})


def ca(cid, diff="Mid", status="確定可能"):
    return {"component_id": cid, "difficulty": diff, "matched_conditions": "m", "rationale": "r",
            "estimate_status": status}


def test_common_quantity_multiplies(standards):
    est = run_calc(standards, [comp("PG", elements=("P1", "P2"))], [ca("PG")])
    row = est["architectures"][0]["components"][0]
    assert row["quantity"] == 2
    assert row["effort"] == {"low": 4.0, "std": 8.0, "high": 12.0}  # Mid単価(2,4,6)×2


def test_shared_component_counted_once(standards):
    c = comp("AUTH1", type_id="AUTH", used_by=["C1", "C2", "C3"])
    est = run_calc(standards, [c], [ca("AUTH1", "Low")],
                   [assess("C1"), assess("C2"), assess("C3")], cases=("C1", "C2", "C3"))
    a = est["architectures"][0]
    assert a["subtotals"]["common"] == {"low": 1.0, "std": 2.0, "high": 3.0}
    assert a["subtotals"]["cases"] == {"low": 3.0, "std": 6.0, "high": 9.0}


def test_modification_uses_standard_without_discount(standards):
    est = run_calc(standards, [comp("M", kind="改修", change_responsibility="ログイン手順の変更")], [ca("M", "Low")])
    assert est["architectures"][0]["components"][0]["effort"]["std"] == 2.0


def test_reuse_zero_only_when_verified(standards):
    ok = comp("R", kind="既存流用", reuse_verified=True, reuse_integration_owner="B")
    ng = comp("R2", kind="既存流用", reuse_verified=False)
    est = run_calc(standards, [ok, ng, comp("B", type_id="BASE")], [ca("R"), ca("R2"), ca("B")])
    rows = {r["component_id"]: r for r in est["architectures"][0]["components"]}
    assert rows["R"]["category"] == "reuse_zero" and rows["R"]["effort"]["std"] == 0.0
    assert rows["R2"]["category"] == "pending" and rows["R2"]["effort"]["std"] is None


def test_out_of_scope_and_config_exclusion(standards):
    est = run_calc(standards, [comp("X", kind="対象外", exclusion_reason="x"), comp("CI1", type_id="CI")],
                   [ca("CI1")], config={"scope": {"excluded_type_ids": ["CI"]}})
    rows = est["architectures"][0]["components"]
    assert all(r["category"] == "out_of_scope" and r["effort"]["std"] is None for r in rows)
    assert est["architectures"][0]["estimate_completeness"] == "全対象算定"


def test_architectures_are_separate(standards):
    comps = [comp("POM", elements=("P1", "P2", "P3"), arch=("A1",)), comp("NOPOM", type_id="UTIL", arch=("A2",))]
    est = run_calc(standards, comps, [ca("POM", "Low"), ca("NOPOM", "Low")], archs=("A1", "A2"))
    a1, a2 = est["architectures"]
    assert [r["component_id"] for r in a1["components"]] == ["POM"]
    assert [r["component_id"] for r in a2["components"]] == ["NOPOM"]
    assert a1["subtotals"]["common"]["std"] == 6.0 and a2["subtotals"]["common"]["std"] == 2.0


def test_missing_key_not_converted(standards):
    std = copy.deepcopy(standards)
    del std["common"]["effort"]["EXT|High"]
    est = run_calc(std, [comp("E", type_id="EXT")], [ca("E", "High")])
    row = est["architectures"][0]["components"][0]
    assert row["category"] == "uncomputed" and row["effort"]["std"] is None
    assert est["architectures"][0]["estimate_completeness"] == "一部未算定"


def test_counted_elsewhere(standards):
    est = run_calc(standards, [comp("BASE1", type_id="BASE"), comp("FIX1", type_id="FIX", owner="BASE1")],
                   [ca("BASE1", "Low"), ca("FIX1", "Low")])
    rows = {r["component_id"]: r for r in est["architectures"][0]["components"]}
    assert rows["FIX1"]["category"] == "counted_elsewhere" and rows["FIX1"]["effort"]["std"] is None


def test_reproducible(standards):
    args = ([comp("PG", elements=("P1", "P2"))], [ca("PG")], [assess("C1", (2, 2, 1, 1, 1))])
    a = run_calc(standards, *args, cases=("C1",))
    b = run_calc(standards, *args, cases=("C1",))
    assert a == b


def test_null_excluded_but_counted(standards):
    est = run_calc(standards, [], [], [assess("C1"), assess("C2", (1, None, 1, 1, 1), info_sufficient=False,
                                                            estimate_status="要確認")], cases=("C1", "C2"))
    a = est["architectures"][0]
    assert a["subtotals"]["cases"]["std"] == 2.0
    assert a["counts"]["cases"]["pending"] == 1
    assert a["counts"]["unresolved_items"] == 1
    assert a["estimate_completeness"] == "一部未算定"


def test_unassessed_case_is_counted(standards):
    est = run_calc(standards, [], [], [], cases=("C1",))
    a = est["architectures"][0]
    assert a["cases"][0]["category"] == "unassessed" and a["estimate_completeness"] == "一部未算定"
