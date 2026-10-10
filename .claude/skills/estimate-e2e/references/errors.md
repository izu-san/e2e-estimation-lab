# 検証エラーへの対応

`validate-stage` のエラーは `{code, path, message}`。示された箇所だけを直す。

| code | 対応 |
|---|---|
| SCHEMA | 型・必須項目・enumを直す。計算値（difficulty, effort 等）をcase_assessmentsに書いていないか確認 |
| REGION_NOT_DISPOSED | source_inventoryの全領域に処遇を書く（説明・参考でも `not_test` で記録） |
| BAD_REF | 存在するシート名・範囲にする（views/*.md の座標を確認） |
| ITEM_UNMAPPED / ITEM_NOT_MAPPED | mappedの項目はケースに対応させる。除外・統合なら disposition を変えて理由を書く |
| BAD_DUPLICATE / NO_REASON | 統合先と根拠を書く |
| DOUBLE_COUNT | 同一要素を複数作業で計上している。どちらかに寄せるか cost_owner で計上先を一本化 |
| DEPENDENCY_CYCLE | depends_on の循環を解消（統合・計上先の関係を depends_on に混ぜていないか） |
| UNKNOWN_TYPE | 共通基準にある種別IDだけを使う。基準外の作業は questions に standards_issue/基準外として残す |
| AXIS_MISSING / INCONSISTENT | 全軸を書く（未判定はnull）。nullがあれば info_sufficient=false・要確認 |
| UNKNOWN_QUESTION | `question_ids` の質問IDが `ai/questions.json` に無い。先に questions.json へ起票（工程5）して `validate-stage --stage questions` を通してから採点を再提出する |
| UNKNOWN_TARGET | 意味レビューの `target`/`related` が実在IDでない。成果物のcase_id・component_id等か `overall` にする |
| BAD_STD_REF | `cases:シート名!セル` 形式で、standards_text に現れる座標を使う |
| RECOMPUTE_MISMATCH | estimate.json を手で触らない。`calculate` を再実行する |
| SOURCE_CHANGED | 入力・基準・設定が実行開始後に変わった。新しいrunを作る（このrunでは続けない） |
| STATUS_RULE | estimate_status を基準の規則どおりにする（AX-04が2点以上・仮定あり→条件付き、Impossible→確定可能） |
| BAD_GROUP / ITEM_ID_EMPTY / EMPTY_QUERY | item_groups の行範囲・1項目の行数・ID列、query の列と値を `render` / `profile` で確認して直す |
| ITEM_OVERLAP（警告） | 同じ行を2つの項目に数えていないか確認する |
| STANDARDS | 基準の読取り・整合エラー。原本は変更せず、該当セル・影響・暫定扱いを questions(standards_issue) と最終報告に書く |

検証器・スキーマ・基準・設定を変更してエラーを消してはいけない。上限に達したら止める。

## 整合チェック（2026-10 追加）
| code | 対応 |
|---|---|
| USAGE_MISMATCH | `common_design.json` の `used_by` と `assessments.json` の `uses_components` を一致させる。部品を使うケースは両方に書く（RUN・BASEなど全ケースが使う部品も含む）。どちらが正しいかは責務から決める |
| STEP_COUNT_MISMATCH（警告） | 親項目と分解先ケースの `step_count` の数え方を揃える。意図して違う場合は `relation_reason` に理由を書く |
| QUESTION_NOT_LINKED / QUESTION_TARGET_MISSING（警告） | 質問の `targets` と、ケース・共通作業の `question_ids` を双方向でそろえる。同じ前提に依存する他のケースの漏れも探す |
| EVIDENCE_REF_NO_SHEET（警告） | evidence のセル座標は `シート名!セル`（例: `確認リスト!C3`）。`views/*.md` で実際の座標を確認する。列Aが「No.」の場合、手順・期待結果は別の列にある |
