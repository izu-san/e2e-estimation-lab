"""基準Excelの読込・検証テスト（10.1）。正本は変更せず、使い捨てコピー/人工データで検証する。"""

import os
import shutil
from pathlib import Path

import pytest
import yaml

from conftest import ADAPTER, REAL_ADAPTER, ROOT
from estimator.calculate import calc_case, calc_common_example
from estimator.io_utils import sha256_file
from estimator.standards import load_adapter, load_standards
from helpers import build_cases_standard, build_common_standard, default_common_rows


def load(c, m, adapter=None):
    return load_standards(c, m, adapter or load_adapter(ADAPTER))


def test_values_follow_modified_copy(tmp_path):
    c = build_cases_standard(tmp_path / "c_v0.1.xlsx", low=(2, 3, 4), low_max=6, high_min=9)
    m = build_common_standard(tmp_path / "m_v0.1.xlsx")
    std = load(c, m)
    assert std["errors"] == []
    assert std["cases"]["effort"]["Low"]["std"] == 3.0
    assert std["cases"]["thresholds"]["low_max"]["value"] == 6.0
    ax = {f"AX-0{i}": {"score": s, "condition": "c", "evidence": "e"} for i, s in enumerate((2, 1, 1, 1, 1), 1)}
    row = calc_case({"scope": "対象内", "feasibility": "feasible", "info_sufficient": True, "axes": ax,
                     "estimate_status": "確定可能"}, std["cases"], list(ax))
    assert row["difficulty"] == "Low"  # 合計6 ≦ 変更後Low上限6
    assert row["effort"]["std"] == 3.0


def test_duplicate_key_detected(tmp_path):
    std = load(build_cases_standard(tmp_path / "c_v0.1.xlsx", dup_mid=True), build_common_standard(tmp_path / "m_v0.1.xlsx"))
    assert any("重複" in e for e in std["errors"])
    rows = default_common_rows() + [["PAGE", "Mid", "1部品", 1, 2, 3]]
    std = load(build_cases_standard(tmp_path / "c2_v0.1.xlsx"), build_common_standard(tmp_path / "m2_v0.1.xlsx", rows=rows))
    assert any("PAGE|Mid が重複" in e for e in std["errors"])


@pytest.mark.parametrize("bad,msg", [
    (["PAGE", "Low", "1部品", 5, 2, 3], "下限≦標準≦上限"),
    (["PAGE", "Low", "1部品", -1, 2, 3], "負の数"),
    (["PAGE", "Low", "1部品", "abc", 2, 3], "数値ではありません"),
    (["PAGE", "Low", "1部品", None, 2, 3], "空欄"),
    (["PAGE", "Low", None, 1, 2, 3], "単位が空欄"),
    (["XYZ", "Low", "1部品", 1, 2, 3], "未知の種別ID"),
])
def test_invalid_common_rows(tmp_path, bad, msg):
    rows = [r for r in default_common_rows() if r[:2] != ["PAGE", "Low"]] + [bad]
    std = load(build_cases_standard(tmp_path / "c_v0.1.xlsx"), build_common_standard(tmp_path / "m_v0.1.xlsx", rows=rows))
    assert any(msg in e for e in std["errors"]), std["errors"]


def test_missing_unit_price_is_reported_not_zero(tmp_path):
    rows = [r for r in default_common_rows() if r[0] != "POC"]
    std = load(build_cases_standard(tmp_path / "c_v0.1.xlsx"), build_common_standard(tmp_path / "m_v0.1.xlsx", rows=rows))
    assert "POC|Low" not in std["common"]["effort"]
    assert any("POC" in w for w in std["warnings"])


def test_unknown_version_rejected(tmp_path):
    std = load(build_cases_standard(tmp_path / "c_v0.9.xlsx", version="v0.9"), build_common_standard(tmp_path / "m_v0.1.xlsx"))
    assert any("未対応の基準版" in e for e in std["errors"])


def test_formula_without_cache_is_error(tmp_path):
    std = load(build_cases_standard(tmp_path / "c_v0.1.xlsx", formula_threshold=True), build_common_standard(tmp_path / "m_v0.1.xlsx"))
    assert any("保存済み計算結果" in e for e in std["errors"])


def test_text_change_requires_rule_review(tmp_path):
    c = build_cases_standard(tmp_path / "c_v0.1.xlsx")
    m = build_common_standard(tmp_path / "m_v0.1.xlsx")
    adapter = load_adapter(ADAPTER)
    fp = load(c, m, adapter)["cases"]["text_fingerprint"]
    adapter["cases"]["approved_text_fingerprint"] = fp
    assert load(c, m, adapter)["cases"]["text_approval"] == "approved"
    c2 = build_cases_standard(tmp_path / "c_v0.1.xlsx", extra_text="判定ルールを変更しました")
    std = load(c2, m, adapter)
    assert std["cases"]["text_approval"] == "changed"
    assert any("文章が承認時から変更" in e for e in std["errors"])


def test_structure_change_detected(tmp_path):
    adapter = load_adapter(ADAPTER)
    adapter["cases"]["effort_table"]["columns"]["std"] = ["存在しない見出し"]
    std = load(build_cases_standard(tmp_path / "c_v0.1.xlsx"), build_common_standard(tmp_path / "m_v0.1.xlsx"), adapter)
    assert any("見つかりません" in e for e in std["errors"])


def test_common_example_recalculated_with_same_lookup(tmp_path):
    m = build_common_standard(tmp_path / "m_v0.1.xlsx", example=[["BASE", "Mid", 1, "算定"], ["PAGE", "Low", 3, "算定"],
                                                               ["EXT", None, 1, "要確認"]])
    std = load(build_cases_standard(tmp_path / "c_v0.1.xlsx"), m)
    res = calc_common_example(std["common"]["example"], std["common"])
    assert res["computed"] == {"low": 5.0, "std": 10.0, "high": 15.0}
    assert len(res["skipped"]) == 1


# ---------------------------------------------------------------- 正本を使う回帰テスト（配置時のみ）

REGRESSION = ROOT / "evals" / "regression" / "common_example.yaml"


def _real_config():
    p = ROOT / "config" / "estimate.yaml"
    if not p.exists():
        p = ROOT / "config" / "estimate.example.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


@pytest.mark.skipif(not REGRESSION.exists(), reason="回帰期待値ファイルがありません")
def test_real_common_example_regression():
    reg = yaml.safe_load(REGRESSION.read_text(encoding="utf-8"))
    cfg = _real_config()
    c, m = ROOT / cfg["standards"]["cases"], ROOT / cfg["standards"]["common"]
    if not (c.exists() and m.exists()):
        pytest.skip("正本の基準Excelが standards/ に配置されていません")
    if reg.get("standards_sha256") and sha256_file(m) != reg["standards_sha256"]:
        pytest.skip(f"共通基準のハッシュが回帰期待値の版と異なります（期待 {reg['standards_sha256']}）")
    before = sha256_file(m)
    std = load(c, m, load_adapter(REAL_ADAPTER))
    assert std["errors"] == [], std["errors"]
    assert std["common"]["example"] is not None, std["common"]["warnings"]
    res = calc_common_example(std["common"]["example"], std["common"])
    assert res["computed"] == reg["expected_computed_subtotal"]
    assert sha256_file(m) == before  # 正本を変更していない


# 2026-10-11: 計上ルールに COST-11〜13 を追記した版（判定例シートは変更なし）
CASES_REGRESSION_SHA = "f45b9677cab6b92fdda8f1cc10f055e07a0358d03cd0b52b41a8a6abd96c2716"


def test_real_case_examples_regression():
    """個別基準『判定例』の各例を、本番と同じ総合判定・工数参照で再計算し、Excelの保存値と照合する。"""
    cfg = _real_config()
    c, m = ROOT / cfg["standards"]["cases"], ROOT / cfg["standards"]["common"]
    if not (c.exists() and m.exists()):
        pytest.skip("正本の基準Excelが standards/ に配置されていません")
    if sha256_file(c) != CASES_REGRESSION_SHA:
        pytest.skip("個別基準のハッシュが回帰期待値の版と異なります")
    std = load(c, m, load_adapter(REAL_ADAPTER))
    assert std["errors"] == [], std["errors"]
    ex = std["cases"]["example"]
    assert ex is not None and len(ex["rows"]) >= 1, std["cases"]["warnings"]
    axis_ids = [a["axis_id"] for a in std["cases"]["axes"]]
    feas = {"可能": "feasible", "不可": "impossible_confirmed", "不明": "unknown"}
    for r in ex["rows"]:
        a = {"scope": "対象内", "feasibility": feas[r["feasibility"]],
             "info_sufficient": r["assumption"] != "未解決",
             "axes": {ax: {"score": s} for ax, s in zip(axis_ids, r["scores"])},
             "estimate_status": r["expected"]["status"]}
        row = calc_case(a, std["cases"], axis_ids)
        assert row["difficulty"] == r["expected"]["difficulty"], r
        assert [row["effort"][k] for k in ("low", "std", "high")] == \
            [r["expected"][k] for k in ("low", "std", "high")], r


def test_standards_digest_omits_example_and_spec_sheets():
    from estimator.standards import digest_exclude_patterns, standards_text
    import estimator.standards as stdmod
    stdmod_render = stdmod.render_sheet
    stdmod.render_sheet = lambda sh: f"## シート: {sh['name']}"  # 描画の詳細はここでは見ない
    try:
        _digest_check(stdmod, digest_exclude_patterns, standards_text)
    finally:
        stdmod.render_sheet = stdmod_render


def _digest_check(stdmod, digest_exclude_patterns, standards_text):
    def sheet(i, name):
        return {"name": name}
    wb = {"file_name": "x.xlsx", "sha256": "h", "sheets": [sheet(1, "判定基準"), sheet(2, "判定例"), sheet(3, "AI出力仕様")]}
    part = {"_workbook": wb}
    adapter = {"example": {"sheet_pattern": "^判定例$"}, "digest_exclude_sheets": ["^AI出力仕様$"]}
    full = standards_text(part)
    digest = standards_text(part, digest_exclude_patterns(adapter))
    assert "判定例" in full and "AI出力仕様" in full and "ダイジェスト" not in full
    assert "シート: 判定基準" in digest and "シート: 判定例" not in digest and "シート: AI出力仕様" not in digest
    assert "判定例, AI出力仕様" in digest  # 省いたシート名を明記する


def test_example_sheet_formula_cache_warnings_are_summarized():
    """判定例シートの数式キャッシュなしは1行にまとめ、他シートの警告は個別に残す。"""
    from estimator.standards import _read_warnings

    wb = {"warnings": [
        {"code": "FORMULA_NO_CACHE", "ref": "判定例!K9"},
        {"code": "FORMULA_NO_CACHE", "ref": "判定例!M9"},
        {"code": "FORMULA_NO_CACHE", "ref": "工数標準!B3"},
        {"code": "HIDDEN_SHEET", "ref": "メモ"},
    ]}
    got = _read_warnings(wb, {"example": {"sheet_pattern": "^判定例$"}})
    assert "読取警告 FORMULA_NO_CACHE 工数標準!B3" in got and "読取警告 HIDDEN_SHEET メモ" in got
    summary = [w for w in got if "FORMULA_NO_CACHE_EXAMPLE" in w]
    assert len(summary) == 1 and "2件" in summary[0]
    assert not any("判定例!K9" in w and "FORMULA_NO_CACHE " in w for w in got)
