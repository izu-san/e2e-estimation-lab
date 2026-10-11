# 意味レビュー（別パス）

機械検証は構造と計算だけを確認する。意味の正しさは別に見る。レビュー役は計算結果・中間JSONを直接書き換えず、
`ai/semantic_review.json` に指摘と修正案を返す。

観点:
- 漏れ: テスト項目らしい行が not_test になっていないか。非表示行・別シートの項目。
- 説明行混入: 説明・参考・凡例がケースになっていないか。
- 過剰分解/統合: 1assert=1ケースになっていないか。粗い行を必要以上に分けていないか。
- 手順数の誤カウント: 結合セル・複数行手順の数え方。
- 重複: 重複候補を無断で消していないか、統合先と根拠があるか。
- 責務重複: AUTH/FIX、DATA/FIX、PAGE/COMP/FLOW の分担。同じ部品の多重計上。
- 採点根拠: 軸の condition が基準の文言に対応し、evidence が原資料にあるか。
- 他ファイル情報での補完をしていないか。

## 独立性（--context）
作成者本人の見直しは、自分の前提や解釈を引き継ぐため独立したレビューにならない。
- サブエージェント `estimate-reviewer`（`.claude/agents/estimate-reviewer.md`、読取り専用）に任せる。
  渡すのは run ディレクトリのパスと「意味レビューを実施し、JSONで指摘を返す」という依頼だけ。
  作成時の推論や結論は渡さない。レビュー役はファイルを書けないので、返ったJSONを本セッションが
  `ai/semantic_review.json` に書く（内容を勝手に足し引きしない）。
  → `scripts/estimator mark-review --run <id> --by ai --context independent`
- 使えない（権限・環境）ときは本人が見直し、`--context self` で記録する。
  状態は「AIレビュー済（自己レビュー）」となり、最終報告でも自己レビューであることを明記する。

## 指摘の検証
`ai/semantic_review.json` は `scripts/estimator validate-stage --run <id> --stage semantic_review` で検証する。
`kind` は決められた値（over_split / under_split / missing_item / duplicate / double_count / scoring / status / question_missing / other）、
`target`・`related` は成果物に実在するID（または全体を指す `overall`）。`mark-review --by ai` は検証エラーがあると記録を拒否する。
検証は形式とIDの実在だけで、指摘の当否は判断しない。

## 指摘への対応（resolution）
指摘は記録して終わりにしない。`mark-review --by ai` は、全指摘に `resolution` が無いと記録を拒否する。
本セッションが各指摘を読み、`ai/semantic_review.json` の該当指摘に追記する（指摘本文は書き換えない）:
```json
"resolution": {"status": "fixed", "note": "C-015 の AX-01 を1点に修正（注文確定の操作列は FLOW-002 が所有）"}
```
| status | 使うとき |
|---|---|
| fixed | 成果物を直した。通常の工程（validate-stage → calculate → validate → export）をやり直してから記録する |
| question | 確認事項として起票した。`question_ids` 必須（questions.json に実在するID） |
| rejected | 指摘に当たらない。`note` に基準・原資料の根拠を書く |
| deferred | 今回は直さない（基準担当の回答待ち等）。`note` に理由。状態は「AIレビュー済（未対応N件）」になる |

順序: レビュー → 指摘に対応（修正なら再計算まで）→ resolution を記録 → `validate-stage --stage semantic_review` →
`scripts/estimator mark-review --run <id> --by ai --context independent|self`。
mark-review 後に見積もりが変わると、状態に「レビュー記録後に見積もり変更」と出る。対応をやり直したら mark-review も再実行する。
`summary.md` と `estimate.xlsx`（意味レビュー シート）に指摘と対応の一覧が出る。未対応の指摘は最終報告にも書く。
人が確認した場合のみ `--by human --reviewer <名前>`（AIは実行しない）。
