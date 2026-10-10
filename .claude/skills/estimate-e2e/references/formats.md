# 中間JSONの形式（最小例）

正本はスキーマ（`schemas/*.schema.json`）。ここは書き方の例。

## ai/normalized_cases.json
```json
{
  "schema_version": 1,
  "regions": [
    {"region_id": "W1-S1-R001", "role": "description", "disposition": "not_test", "reason": "表紙の説明文"},
    {"region_id": "W1-S1-R002", "role": "test_table", "disposition": "parsed", "header_rows": [4], "reason": "項目表"}
  ],
  "source_items": [
    {"item_id": "TC-01", "original_id": "TC-01", "id_assigned": false, "region_ids": ["W1-S1-R002"],
     "refs": [{"workbook_id": "W1", "sheet": "テスト項目", "range": "A5:F7"}],
     "title": "ログイン成功", "step_count": 3, "expected_count": 1, "data_pattern_count": 1,
     "disposition": "mapped", "duplicate_of": null, "reason": "",
     "inheritance": [{"ref": {"workbook_id": "W1", "sheet": "テスト項目", "range": "B6"},
                      "from_ref": {"workbook_id": "W1", "sheet": "テスト項目", "range": "B5"},
                      "reason": "B5:B7の結合セル。同一項目の前提条件"}]}
  ],
  "cases": [
    {"case_id": "C-001", "title": "ログイン成功", "source_item_ids": ["TC-01"], "relation": "one_to_one",
     "summary": "", "preconditions": [], "steps": ["..."], "expected": ["..."],
     "step_count": 3, "assertion_count": 1, "data_pattern_count": 1}
  ]
}
```

## ai/common_design.json
```json
{
  "schema_version": 1,
  "architectures": [{"arch_id": "A1", "name": "POMあり", "assumptions": ["POM採用（設定unspecifiedのため仮定）"]}],
  "components": [
    {"component_id": "PAGE-001", "arch_ids": ["A1"], "type_id": "PAGE", "name": "ログイン画面PO",
     "responsibility": "ログイン画面固有の操作", "need_reason": "C-001,C-002が利用",
     "implementation_kind": "新規", "change_responsibility": null,
     "elements": ["PG-Login"], "used_by": ["C-001", "C-002"], "depends_on": ["BASE-001"],
     "integrated_into": null, "cost_owner": "PAGE-001"}
  ]
}
```

## ai/assessments.json
```json
{
  "schema_version": 1,
  "case_assessments": [
    {"case_id": "C-001", "arch_ids": ["A1"], "scope": "対象内", "scope_reason": "", "feasibility": "feasible",
     "info_sufficient": true,
     "axes": {
       "AX-01": {"score": 1, "condition": "…（基準の文言）", "evidence": "手順3つ（A5:C7）", "standard_refs": ["cases:判定軸!C2"]},
       "AX-02": {"score": 1, "condition": "…", "evidence": "…"},
       "AX-03": {"score": 1, "condition": "…", "evidence": "…"},
       "AX-04": {"score": 1, "condition": "…", "evidence": "…"},
       "AX-05": {"score": 2, "condition": "…", "evidence": "…", "assumptions": ["テストユーザーは事前作成可能"]}
     },
     "estimate_status": "条件付き", "conditions": ["テストユーザーを顧客が用意"], "rationale": "…",
     "uses_components": ["PAGE-001"], "question_ids": ["Q-003"]}
  ],
  "common_assessments": [
    {"component_id": "PAGE-001", "difficulty": "Low", "matched_conditions": "…", "standard_refs": ["common:共通作業基準!D6"],
     "rationale": "…", "estimate_status": "確定可能"}
  ]
}
```

## ai/questions.json
```json
{"schema_version": 1, "items": [
  {"question_id": "Q-001", "kind": "question", "targets": ["C-004"], "text": "決済はテスト用カードを利用できますか",
   "impact": "C-004 は要確認（難易度null）", "proposed_default": "", "status": "open"},
  {"question_id": "Q-002", "kind": "assumption", "targets": ["A1"], "text": "POMを採用する前提",
   "impact": "PAGE作業の有無", "status": "assumed"},
  {"question_id": "Q-003", "kind": "question", "targets": ["RUN-001"], "text": "安定実行の受入基準（連続実行の本数・合格率）は",
   "impact": "RUN-001 の範囲", "status": "open",
   "refs": [{"workbook_id": "W1", "sheet": "資料情報", "range": "B7"}]}
],
 "premise_reviews": [
  {"ref": {"workbook_id": "W1", "sheet": "資料情報", "range": "A2:B4"},
   "reason": "対象サイト・ツール・ブラウザーの前提。案件設定と共通設計（BASE-001）に反映済み"}
]}
```
説明・参考領域の各行は、質問の `refs` か `premise_reviews` のどちらかに入れる（`PREMISE_ROW_UNTRACED` 警告）。
`kind`: question / assumption / impossible_reason / constraint（読めない図など）/ standards_issue（基準内の矛盾）。

## ai/semantic_review.json（レビュー役の指摘 ＋ 本セッションの対応）
```json
{"schema_version": 1, "reviewer": "ai", "findings": [
  {"target": "C-007", "related": ["C-008"], "kind": "over_split", "message": "…", "suggestion": "…",
   "resolution": {"status": "fixed", "note": "C-007 を C-008 に統合し再計算"}}
]}
```
`resolution` はレビュー役ではなく本セッションが書く。詳細は review.md。

## ケース（cases）の全フィールドの注意
- `preconditions` / `steps` / `expected` は**文字列の配列**（1件でも `["…"]`）。文字列を直接入れるとSCHEMAエラー。
- 1項目に複数データパターンがあるだけなら `one_to_one` + `data_pattern_count`。`merged` は複数の `source_item_ids` のときだけ。

## 質問IDの双方向リンクは機械的に付ける
質問の `targets` とケース・共通作業の `question_ids` は同じ集合にする。数が多いときは、生成スクリプトで
`targets` から `question_ids` を（またはその逆を）一括で組み立てると漏れない。案件全体の仮定は `targets` に構成案IDを入れる。
