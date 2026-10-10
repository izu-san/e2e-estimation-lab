# standards/ — 基準Excel（正本・読取り専用）

| ファイル | 用途 | 状態 |
|---|---|---|
| `Playwright_自動化工数標準設定_v0.1.xlsx` | 個別ケースの5軸評価、総合難易度、工数、例外処理 | 配置済（2026-10-10） |
| `Playwright_汎用共通部分工数基準_v0.1.xlsx` | 共通基盤等の種類別難易度、単位、工数、重複防止 | 配置済（2026-10-10） |

ファイル名・配置は `config/estimate.yaml` の `standards:` で変更できる。

## 配置後に行うこと（開発モード）
1. `scripts/estimator inspect-standards --config config/estimate.yaml` で、工数表・閾値・判定軸・判定集計例が
   正しいセルから読めているか確認する（`--show-text` で全シートを座標つき表示）。
2. 読めない・誤読している場合は `config/standards_adapter.yaml` の見出し候補（aliases）や `sheet_pattern` を調整する。
   コードに数値を書かない。
3. 基準の文章を確認し、`src/estimator/calculate.py` の総合判定ロジック（ルール版 `case-rule-1`）と一致すると
   判断したら、表示された `text_fingerprint` を adapter の `approved_text_fingerprint` に記入する
   （未記入でも実行はできるが「未承認」警告が出る。記入後に文章が変わるとエラーになる）。
4. `evals/regression/common_example.yaml` の `standards_sha256` に共通基準のハッシュを記入し、
   `uv run pytest -q tests/test_standards.py` で「判定集計例」回帰（22/39/64）を確認する。
