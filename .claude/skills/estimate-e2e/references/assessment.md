# Stage 6: 個別ケースの判定と共通作業の難易度（assessments.json）

前提: `ai/questions.json` が検証済み（工程5）。`question_ids` は questions.json に存在するIDだけを使う。

スキーマ: `schemas/assessments.schema.json`。**工数・総合難易度・合計は書かない**（書くとスキーマエラー）。

## 個別ケース（case_assessments）
確定または仮定した共通構成を前提に、ケース×構成案（`arch_ids`）ごとに書く。同じ採点を複数案に使うなら `arch_ids` に列挙。

1. `scope`: 対象内 / 別見積 / 対象外（理由 `scope_reason`）。Web E2E以外の手段が必要なもの等。
2. `feasibility`: `impossible_confirmed` は「合意範囲で実現不可と確認済」のときだけ（理由 `impossible_reason`）。疑いだけなら `unknown`。
3. `info_sufficient`: 主要情報が不足し方針を定められないなら false（→要確認・難易度null）。
4. `axes`: 基準Excelの全軸（AX-01〜AX-05）を1〜3点またはnull。各軸に
   - `condition`: 基準のどの条件に当てはめたか（基準の文言。可能なら `standard_refs` に `cases:シート名!セル`）
   - `evidence`: 原資料の根拠（どの手順・期待結果か）
   - `assumptions`: 置いた仮定
5. `estimate_status`: 確定可能 / 条件付き（`conditions` 必須）/ 要確認。基準の規則（RULE-07・RULE-03）で決まり、検証器が照合する:
   - 仮定なし・5軸確定 → 確定可能。あいまい度（AX-04）が2点以上、または軸の `assumptions`・`conditions` があれば → 条件付き
   - 情報不足・実現性不明 → 要確認。Impossible → 確定可能（工数はnull）
6. `uses_components`: 前提にした共通作業ID。

総合難易度（Low/Mid/High）は閾値とともにCLIが基準Excelの値から決める。合計点を自分で判定しない。

### AX-05（データ準備・後処理）と共通のDATA/FIXの境界
個別ケースのAX-05は「そのケース固有の準備・後処理の重さ」を採点する。共通部品の開発時間は共通側（DATA/FIX/AUTH等）に別計上する（基準 判定基準 AX-05 の根拠欄、計上ルール COST-04）。
- 共通部品（ユーザー作成・削除など）が**あっても**、ケースが「ユーザー作成・ファイル・削除/復元が必要」なら、基準の2点の条件に該当する（方法が既知なら2点）。共通部品があることを理由に1点へ下げない（基準にない割引になる）。
- 1点にできるのは、静的データまたは既存fixtureで足り、ケース固有の復元が軽微なとき（データの指定とcleanup呼出しだけ）。
- 3点は、多段階の状態作成・共有資源の隔離・複数システム間の準備復元が**このケース固有で**必要なとき。共通側のFIX/DATAがHighでも、ケースのAX-05を自動で3点にしない。
- 二重計上の確認: 共通側に積んだ作業（DATA-xxx の実装）を、ケースのevidenceで「新規開発」として再び重く評価していないか。ケースは「共通部品を呼ぶ＋固有データを指定する」範囲だけを根拠にする。
- 迷ったら、evidenceに「どの共通部品を呼ぶか」と「ケース固有の準備・後処理」を分けて書く。

## 共通作業（common_assessments）
- 共通基準の**種類別の判定条件**に照らして Low/Mid/High（決められなければnull＋要確認）。
  当てはまる最も高い条件を選び、仕様に無いHigh要因を想像で加えない（COM-04）。Mid要因が複数あるだけで昇格しない（COM-05）。
- 合意した手段・権限・環境で実現不可と確認済みなら `Impossible`（`impossible_reason` に理由・根拠・解消条件・代替案。
  estimate_status は確定可能。COM-10）。不明なだけならImpossibleにしない。
- 条件付きにする場合は `conditions` に仮定・影響・再見積条件を書く（COM-09）。
- `matched_conditions` に当てはめた条件、`standard_refs` に `common:シート名!セル`、`rationale` に理由。
- `cost_owner` が自分自身の 新規/改修 作業はすべて判定する（無いと未算定）。

## 共通構成を変えたら
`common_design.json` を変更すると採点・計算は stale になる。影響する `used_by` のケースを再採点してから再計算する。
