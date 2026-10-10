# Stage 3: 項目の整理（normalized_cases.json）

入力: `source_inventory.json` の `regions`、`views/*.md`。スキーマ: `schemas/normalized_cases.schema.json`。

## 1. 領域の処遇（regions）
`source_inventory.json` の**全領域**（`region_id`）について1件ずつ処遇を書く。漏れは検証エラー。

| role | 例 |
|---|---|
| test_table / test_block | テスト項目の表・項目のまとまり |
| heading / description / legend | 表題・説明文・凡例 |
| reference / revision_history | 参考情報・改版履歴 |
| data_definition | テストデータ定義（データパターン数の根拠になり得る） |
| drawing | 図・画像（内容は読めていない前提） |
| unreadable / other | 読めない・判断できない |

`disposition`: `parsed`（項目を抽出した）/ `not_test`（項目でない）/ `unreadable` / `needs_question`。
非表示シート・非表示行は黙って無視しない。テスト項目なら抽出し、扱いが不明なら `needs_question` と質問を残す。

## 2. 原項目（source_items）
- 原資料上の「1項目」を1件とする。原IDがあれば `original_id`、無ければ内部ID（例 `AUTO-001`）を `item_id` にし `id_assigned: true`、`original_id: null`。
- `refs` は項目が占めるセル範囲（例 `{"workbook_id":"W1","sheet":"テスト項目","range":"A5:F7"}`）。複数行手順・横持ちも全範囲を含める。
- `step_count` / `expected_count` / `data_pattern_count` は原資料に書かれた数。不明ならnull。行数をそのまま手順数にしない。
- 重複候補: 完全一致でも削除しない。統合する場合は `disposition: merged_duplicate`、`duplicate_of` に統合先、`reason` に根拠。
  統合しない場合は `mapped` のまま `duplicate_of` に候補を記録し、`reason` に判断を書く。
- 結合セル・空欄から値を引き継いだら `inheritance` に `ref`（空欄側）・`from_ref`（値の出所）・`reason` を書く。
- テストでない行（参考・説明）を項目にしない。項目らしいが判断できないものは `needs_question`。

## 3. 見積もりケース（cases）
- 見積もり単位。原項目と1対1（`one_to_one`）、1項目を複数に分解（`split`）、複数を統合（`merged`）。
  `split`/`merged` は `relation_reason` 必須。
- 粗い項目（複数の確認をまとめた行）は、独立に自動化・実行される単位に分解してよい。
  1クリック・1assert・1URLを自動的に1ケースにしない。
- `steps` / `expected` は原文の意味を保った要約。原資料に無い手順を補わない（推測した場合は `notes` と questions に仮定を残す）。
- `step_count` / `assertion_count` / `data_pattern_count` はケース単位の数（データパターンは最低1）。

### 一部だけ仕様が未提示の項目（分割するか、全体を要確認にするか）
1つの項目の中に、確定できる部分と仕様未提示の部分が混ざることがある（例: ダウンロードは確認できるが内容照合の仕様が無い、PCは確定だがスマホ条件が無い）。
- **分割する**: 両部分が独立して自動化・判定でき、片方の未提示がもう片方の実装・判定に影響しない。
  `relation: split` とし、`relation_reason` に「どこが確定で、どこが未提示か」と基準の根拠（判定例 EX-10・EX-08、RULE-04、COST-06 など）を書く。
  未提示側は5軸のうち決められない軸をnull・`info_sufficient: false`（要確認）にし、**必ず質問を起票**する。
- **分割しない（項目全体を要確認）**: 未提示部分が確定部分の操作・データ・判定に影響する、または切り分けると手順が成立しない。
- 分割しても元項目全体が自動化済みになるわけではない。確定部分だけが算定され、総計は暫定になる（最終報告に明記）。
- 迷ったら分割せず、仮定を置ける軽微な欠落なら AX-04 を2点（条件付き）で扱う。未提示を埋めるために仮の数字・手順は作らない。

## 大規模資料：item_groups と source_item_query
数百〜数千件の項目を1件ずつ `source_items` に書かない。規則的な表は **item_groups** で宣言し、展開はスクリプトに任せる。
```json
"item_groups": [
  {"group_id": "G-CART", "region_ids": ["W1-S8-R002"], "workbook_id": "W1", "sheet": "カート",
   "first_row": 6, "last_row": 905, "rows_per_item": 3, "first_column": "A", "last_column": "I",
   "id_column": "A", "title_column": "B", "disposition": "mapped", "reason": "1ケース3行・結合セル"}
]
```
- `first_row` は最初の項目の先頭行（見出し行を含めない）。範囲内の中見出し・空行は `skip_rows`。
- IDが無い表は `id_column: null` と `item_id_prefix`（例 `AUTO-CART-`）。内部IDが連番で付く。
- 宣言前に `profile` と `render` で、見出し行・1項目の行数・ID列を必ず確認する。展開結果は `validate-stage` が検証する
  （ID空欄、行数が割り切れない、範囲外、項目の重なり）。
- ケースへの対応付けは **source_item_query** で列の値から選べる（全条件AND、`equals` / `contains` / `regex`）。
```json
{"case_id": "C-CART-01", "title": "指定数量の追加", "source_item_ids": [], "relation": "merged",
 "relation_reason": "同じ観点のデータ違い・ブラウザー違いを1つのパラメータ化ケースへ（個別基準 COST-05）",
 "source_item_query": {"group_ids": ["G-CART"], "where": [{"column": "B", "equals": "指定数量の追加"}]},
 "summary": "...", "steps": ["..."], "expected": ["..."], "step_count": 3, "assertion_count": 3, "data_pattern_count": 10}
```
- 判定・準備が同じでデータだけ違う項目は、1つのパラメータ化ケースにまとめる（個別基準 COST-05）。
  ブラウザー違いは基準環境（Chromium 1種）外の差分として扱う（COST-06）。総工数をブラウザー数で一律に掛けない。
- 例外的な行（他と手順が違う等）は、グループから `skip_rows` で外して `source_items` に個別に書く。

## 大きな資料
`views/` はシート・行範囲で分割されている。分割の先頭に「領域が続いている」注記と見出し行が再掲される。
途中の手順行を独立項目と誤認しないこと。全ビューを読んでから項目を確定する。
