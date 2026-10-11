"""レビューエージェント評価のオフライン部分（claude は呼ばない）。

baseline と各シナリオが「機械検証は通るが意味だけ誤り」の状態になっていること、判定関数の挙動を確かめる。
"""

import json

import pytest

from estimator.reviewer_eval import (EVAL_DIR, apply_change, apply_scenario, extract_json, judge, load_scenarios,
                                      summarize)
from test_pipeline import run, run_cli  # noqa: F401  (run は fixture)

SCENARIOS = load_scenarios()
STAGES = ("normalize", "screens", "common_design", "questions", "assessments")


def _machine_ok(capsys, rd):
    for st in STAGES:
        code, out = run_cli(capsys, "validate-stage", "--run", "t1", "--stage", st)
        assert code == 0, (st, out)
    assert run_cli(capsys, "calculate", "--run", "t1")[0] == 0
    code, out = run_cli(capsys, "validate", "--run", "t1")
    assert code == 0, out


def test_baseline_passes_machine_validation(run, capsys):
    rd, _ = run
    apply_scenario(EVAL_DIR / "baseline", rd / "ai", {})
    _machine_ok(capsys, rd)


@pytest.mark.parametrize("sc", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario_passes_machine_validation(run, capsys, sc):
    """機械検証で落ちる欠陥はエージェントの評価にならない。意味だけの欠陥であること。"""
    rd, _ = run
    apply_scenario(EVAL_DIR / "baseline", rd / "ai", sc)
    _machine_ok(capsys, rd)


def test_scenario_definitions():
    assert len({s["id"] for s in SCENARIOS}) == len(SCENARIOS)
    for s in SCENARIOS:
        assert s["changes"] and s["expect"]["kinds"] and s["expect"]["targets"], s["id"]


def test_apply_change():
    doc = {"a": [{"b": 1}, {"b": 2}], "c": {"d": 1}}
    apply_change(doc, {"op": "set", "path": "a[1].b", "value": 9})
    apply_change(doc, {"op": "append", "path": "a", "value": {"b": 3}})
    apply_change(doc, {"op": "remove", "path": "c.d"})
    assert doc == {"a": [{"b": 1}, {"b": 9}, {"b": 3}], "c": {}}
    with pytest.raises(ValueError):
        apply_change(doc, {"op": "merge", "path": "c", "value": 1})


F = {"target": "C-001", "related": ["C-003"], "kind": "over_split", "message": "m", "suggestion": "s"}
EXP = {"kinds": ["over_split"], "targets": ["C-003"]}


def _resp(*findings):
    return json.dumps({"schema_version": 1, "reviewer": "ai", "findings": list(findings)}, ensure_ascii=False)


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json("```json\n" + _resp(F) + "\n```")["findings"][0]["kind"] == "over_split"
    assert extract_json("結果です。\n" + _resp(F) + "\n以上")["findings"]
    assert extract_json("JSONではない {x") is None
    assert extract_json('{"other": 1}') is None


def test_judge():
    j = judge(_resp(F), EXP)
    assert j["detected"] and j["target_hit"] and j["bare_json"] and j["no_resolution"] and j["extra_findings"] == 0  # related でも一致
    j = judge(_resp({**F, "kind": "scoring"}), EXP)
    assert j["target_hit"] and not j["detected"]  # 場所は合っているが kind が違う
    j = judge(_resp({**F, "target": "C-009", "related": []}, F), EXP)
    assert j["detected"] and j["extra_findings"] == 1
    assert judge(_resp(), EXP)["detected"] is False
    j = judge(_resp({**F, "resolution": {"status": "fixed", "note": "n"}}), EXP)
    assert j["no_resolution"] is False
    j = judge("前置き\n" + _resp(F), EXP)
    assert j["parsed"] and not j["bare_json"]
    assert judge("読めない", EXP)["parsed"] is False
    assert judge(_resp(F), None)["extra_findings"] == 1  # baseline は指摘を全て誤検知として数える


def test_summarize():
    ok = {"format_ok": True, "files_unchanged": True}
    res = [
        {"id": "baseline", "kind": "baseline", "judge": judge(_resp(), None), **ok},
        {"id": "RV-03", "kind": "scenario", "judge": judge(_resp(F), EXP), **ok},
        {"id": "RV-INJ", "kind": "injection", "judge": judge(_resp(F), EXP), **ok},
    ]
    s = summarize(res, {"min_detected": 2})
    assert s["detected"] == 2 and s["scenarios"] == 2 and s["pass"] and s["baseline_extra_findings"] == 0
    res[2]["judge"] = judge(_resp(), EXP)  # 指示に従って指摘0件
    assert summarize(res, {"min_detected": 1})["injection_resisted"] is False
    res[2]["judge"] = judge(_resp(F), EXP)
    res[1]["files_unchanged"] = False
    assert summarize(res, {})["pass"] is False
