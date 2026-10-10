"""決定的な計算器。

AIの採点(assessments)・共通設計(common_design)・基準(standards)だけから工数を算出する。
AIが提出した計算値は入力に存在しない（スキーマで禁止）ため、常にここで再計算する。
工数・閾値の数値はすべて standards（基準Excel由来）から取る。
"""

from __future__ import annotations

from typing import Any

from . import CASE_RULE_VERSION, COMMON_RULE_VERSION
from .io_utils import sha256_json

POINTS = ("low", "std", "high")


def decide_case_difficulty(scores: list[int | None], low_max: float, high_min: float) -> str | None:
    """現行基準の総合判定（4〜6）。未採点軸があればNone（要確認）。

    4. いずれか3点、または合計がHigh閾値以上ならHigh
    5. それ以外で合計がLow上限以下ならLow
    6. 残りはMid
    """
    if any(s is None for s in scores):
        return None
    total = sum(scores)  # type: ignore[arg-type]
    if any(s == 3 for s in scores) or total >= high_min:
        return "High"
    if total <= low_max:
        return "Low"
    return "Mid"


def _null_effort() -> dict:
    return {k: None for k in POINTS}


def calc_case(assess: dict, std_cases: dict, axis_ids: list[str]) -> dict:
    """1ケース×1構成案の判定。戻り値はestimate.jsonのcase行の一部。"""
    th = std_cases["thresholds"]
    low_max, high_min = th["low_max"]["value"], th["high_min"]["value"]
    scores = [assess["axes"].get(a, {}).get("score") for a in axis_ids]
    total = None if any(s is None for s in scores) else sum(scores)
    row: dict[str, Any] = {
        "axis_scores": dict(zip(axis_ids, scores)),
        "axis_total": total,
        "scope": assess["scope"],
        "difficulty": None,
        "category": None,
        "estimate_status": assess["estimate_status"],
        "effort": _null_effort(),
        "standard_refs": {},
        "notes": [],
    }
    # 1. 対象外/別見積を分離
    if assess["scope"] != "対象内":
        row["category"] = "out_of_scope" if assess["scope"] == "対象外" else "separate_estimate"
        return row
    # 2. 合意範囲で実現不可と確認済ならImpossible
    if assess["feasibility"] == "impossible_confirmed":
        row["difficulty"] = "Impossible"
        row["category"] = "impossible"
        return row
    # 3. 主要情報が不足し方針を定められないなら要確認・難易度null
    if not assess["info_sufficient"] or total is None or assess["feasibility"] == "unknown":
        row["category"] = "pending"
        if row["estimate_status"] != "要確認":
            row["notes"].append(f"estimate_statusを{row['estimate_status']}→要確認へ補正（難易度未確定のため）")
        row["estimate_status"] = "要確認"
        return row
    diff = decide_case_difficulty(scores, low_max, high_min)
    row["difficulty"] = diff
    row["standard_refs"]["threshold_low_max"] = th["low_max"]["ref"]
    row["standard_refs"]["threshold_high_min"] = th["high_min"]["ref"]
    unit = std_cases["effort"].get(diff)
    if unit is None:
        row["category"] = "uncomputed"
        row["notes"].append(f"個別工数表に {diff} の単価がありません")
        return row
    row["effort"] = {k: unit[k] for k in POINTS}
    row["standard_refs"].update({f"effort_{k}": unit["refs"][k] for k in POINTS})
    row["category"] = "computed"
    return row


def calc_component(comp: dict, ca: dict | None, std_common: dict, excluded_types: set[str],
                   components_by_id: dict[str, dict]) -> dict:
    qty = len(comp["elements"])
    row: dict[str, Any] = {
        "component_id": comp["component_id"],
        "type_id": comp["type_id"],
        "implementation_kind": comp["implementation_kind"],
        "difficulty": ca["difficulty"] if ca else None,
        "estimate_status": ca["estimate_status"] if ca else "要確認",
        "quantity": qty,
        "elements": list(comp["elements"]),
        "unit": None,
        "unit_effort": _null_effort(),
        "effort": _null_effort(),
        "cost_owner": comp["cost_owner"],
        "category": None,
        "standard_refs": {},
        "notes": [],
    }
    kind = comp["implementation_kind"]
    if kind == "対象外" or comp["type_id"] in excluded_types:
        row["category"] = "out_of_scope"
        if comp["type_id"] in excluded_types:
            row["notes"].append("案件設定で対象外の種別")
        return row
    if comp["cost_owner"] != comp["component_id"]:
        row["category"] = "counted_elsewhere"
        row["estimate_status"] = "他へ計上"  # 判定なし=情報不足、と誤読されないようにする
        row["notes"].append(f"工数は {comp['cost_owner']} に計上")
        return row
    if kind == "要確認":
        row["category"] = "pending"
        row["estimate_status"] = "要確認"
        return row
    if ca is None:
        row["category"] = "pending"
        row["notes"].append("共通作業の難易度判定がありません")
        return row
    if kind == "既存流用":
        if comp.get("reuse_verified") and comp.get("reuse_integration_owner"):
            row["category"] = "reuse_zero"
            row["effort"] = {k: 0.0 for k in POINTS}
            row["notes"].append(f"新規実装分0。確認・組込みは {comp['reuse_integration_owner']} に計上")
        else:
            row["category"] = "pending"
            row["estimate_status"] = "要確認"
            row["notes"].append("既存流用の適合性未確認、または確認・組込みの計上先が未指定")
        return row
    if ca["difficulty"] is None:
        row["category"] = "pending"
        row["estimate_status"] = "要確認"
        return row
    if ca["difficulty"] == "Impossible":
        # 合意範囲で実現不可と確認済。工数表にImpossibleの行は無く、工数はnull（共通基準 COM-10）
        row["category"] = "impossible"
        return row
    key = f"{comp['type_id']}|{ca['difficulty']}"
    unit = std_common["effort"].get(key)
    if unit is None:
        # 基準にないキーは0や近似単価に変換しない
        row["category"] = "uncomputed"
        row["notes"].append(f"共通工数表に工数キー {key} がありません（未算定）")
        return row
    row["unit"] = unit["unit"]
    row["unit_effort"] = {k: unit[k] for k in POINTS}
    row["effort"] = {k: unit[k] * qty for k in POINTS}
    row["standard_refs"] = {f"effort_{k}": unit["refs"][k] for k in POINTS}
    row["standard_refs"]["unit"] = unit["refs"]["unit"]
    row["standard_key"] = key
    row["category"] = "computed"
    return row


def _sum(rows: list[dict]) -> dict:
    out = {}
    for k in POINTS:
        vals = [r["effort"][k] for r in rows if r["effort"][k] is not None]
        out[k] = round(sum(vals), 6) if vals else 0.0
    return out


def _counts(rows: list[dict]) -> dict:
    c: dict[str, int] = {}
    for r in rows:
        c[r["category"]] = c.get(r["category"], 0) + 1
    c["conditional"] = sum(1 for r in rows if r.get("estimate_status") == "条件付き")
    return c


def calculate(standards: dict, normalized: dict, design: dict, assessments: dict, config: dict) -> dict:
    std_cases, std_common = standards["cases"], standards["common"]
    axis_ids = [a["axis_id"] for a in std_cases["axes"]]
    excluded_types = set((config.get("scope") or {}).get("excluded_type_ids") or [])
    comps_by_id = {c["component_id"]: c for c in design["components"]}
    ca_by_id = {c["component_id"]: c for c in assessments["common_assessments"]}
    case_by_id = {c["case_id"]: c for c in normalized["cases"]}

    archs = []
    for arch in design["architectures"]:
        aid = arch["arch_id"]
        case_rows = []
        for case_id, case in case_by_id.items():
            matches = [a for a in assessments["case_assessments"]
                       if a["case_id"] == case_id and aid in a["arch_ids"]]
            base = {"case_id": case_id, "title": case["title"], "source_item_ids": case["source_item_ids"]}
            if len(matches) != 1:
                case_rows.append({**base, "category": "unassessed", "difficulty": None, "scope": None,
                                  "estimate_status": "要確認", "effort": _null_effort(), "axis_scores": {},
                                  "axis_total": None, "standard_refs": {},
                                  "notes": ["採点がありません" if not matches else "採点が重複しています"]})
                continue
            case_rows.append({**base, **calc_case(matches[0], std_cases, axis_ids)})
        comp_rows = [calc_component(c, ca_by_id.get(c["component_id"]), std_common, excluded_types, comps_by_id)
                     for c in design["components"] if aid in c["arch_ids"]]
        cs, cm = _sum(case_rows), _sum(comp_rows)
        cc, mc = _counts(case_rows), _counts(comp_rows)
        unresolved = sum(cc.get(k, 0) + mc.get(k, 0) for k in ("pending", "uncomputed", "unassessed", "impossible"))
        unresolved += cc.get("separate_estimate", 0)
        archs.append({
            "arch_id": aid,
            "name": arch["name"],
            "cases": case_rows,
            "components": comp_rows,
            "subtotals": {"cases": cs, "common": cm,
                          "computed_total": {k: round(cs[k] + cm[k], 6) for k in POINTS}},
            "counts": {"cases": cc, "components": mc, "unresolved_items": unresolved},
            "estimate_completeness": "全対象算定" if unresolved == 0 else "一部未算定",
        })
    return {
        "schema_version": 1,
        "rule_versions": {"cases": CASE_RULE_VERSION, "common": COMMON_RULE_VERSION},
        "standards_ref": {
            "cases": {"sha256": std_cases["sha256"], "version": std_cases["version"]},
            "common": {"sha256": std_common["sha256"], "version": std_common["version"]},
        },
        "input_hashes": {
            "standards": sha256_json({"cases": {k: std_cases[k] for k in ("effort", "thresholds", "axes")},
                                      "common": std_common["effort"]}),
            "normalized_cases": sha256_json(normalized),
            "common_design": sha256_json(design),
            "assessments": sha256_json(assessments),
        },
        "note": "computed_totalは算定済み分の合計。一部未算定の場合は案件全体の確定総額ではない。",
        "architectures": archs,
    }


def calc_common_example(example: dict, std_common: dict) -> dict:
    """共通基準『判定集計例』の算定済み小計を、本番と同じ単価参照で再計算する（回帰テスト用）。

    計上の条件は v0.1 判定集計例の参照キー列（J列）の式と同じ:
    実装区分が新規/改修、見積状態が要確認以外、難易度が Low/Mid/High なら 単価×数量。
    実装区分が既存流用なら 0。それ以外は小計に含めない。
    """
    tot = {k: 0.0 for k in POINTS}
    skipped = []
    for r in example["rows"]:
        kind = r.get("kind")
        key = f"{r['type_id']}|{r['difficulty']}"
        if kind == "既存流用":
            continue  # 新規実装分0
        countable = (kind in (None, "新規", "改修") and r.get("status") != "要確認"
                     and r["difficulty"] in ("Low", "Mid", "High"))
        unit = std_common["effort"].get(key) if countable else None
        if unit is None or r["quantity"] is None:
            skipped.append({"ref": r["ref"], "key": key, "kind": kind, "quantity": r["quantity"],
                            "status": r.get("status")})
            continue
        for k in POINTS:
            tot[k] += unit[k] * r["quantity"]
    return {"computed": {k: round(v, 6) for k, v in tot.items()}, "skipped": skipped}
