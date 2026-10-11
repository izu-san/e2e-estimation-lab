# ドキュメント索引

目的に合わせて、読む順序を示します。リポジトリ全体の入口は [../README.md](../README.md) です。

## まず読む（全員）

| 順 | 文書 | 内容 | 目安 |
|---|---|---|---|
| 1 | [poc_report.md](poc_report.md) | 検証でわかったことと、わかっていないこと | 15分 |
| 2 | [handover.md](handover.md) | 環境構築から1件の実行・レビューまでの手順 | 1時間 |
| 3 | [faq.md](faq.md) | よくある疑問への短い回答 | 10分 |

迷ったら [glossary.md](glossary.md)（用語集）を引いてください。

## 目的別

### 見積もりを実行して、結果を使う
| 文書 | 内容 |
|---|---|
| [handover.md](handover.md) | 実行・結果の読み方・`runs/` の保管と削除 |
| [new_project.md](new_project.md) | 新しい案件（実際の顧客資料）に適用する手順、案件設定の書き方 |
| [review_guide.md](review_guide.md) | 結果を人がレビューし、承認を記録する手順 |
| [troubleshooting.md](troubleshooting.md) | エラー・警告の意味と対処 |

### 基準Excel（判定基準・工数表）を扱う
| 文書 | 内容 |
|---|---|
| [standards_update.md](standards_update.md) | 基準を変更するときの手順と、影響範囲 |
| [standards_questions.md](standards_questions.md) | 基準の曖昧さに対する確認事項と、決定の経緯（仮ルールの一覧） |

### ツールを改修する・評価する
| 文書 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 内部構造、変更の種類ごとの手順、工程の追加方法 |
| [evaluation_guide.md](evaluation_guide.md) | 評価コマンドの読み方、期待事項の確認、許容幅 |
| [reviewer_agent_test_design.md](reviewer_agent_test_design.md) | 意味レビュー用AIの評価の設計と結果 |
| [ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md](ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md) | 要件・設計書（なぜこの設計か）。基準Excelの構造と入力形式の対応を含む |

## 状況別の早見表

| 状況 | 見る文書 |
|---|---|
| 初めて触る | [poc_report.md](poc_report.md) → [handover.md](handover.md) |
| 見積もりを実行したい | [handover.md](handover.md)（練習用）、[new_project.md](new_project.md)（実案件） |
| エラーが出た | [troubleshooting.md](troubleshooting.md) |
| 結果が正しいか判断したい | [review_guide.md](review_guide.md) |
| 数字や判定の根拠を知りたい | [glossary.md](glossary.md)（ルール番号の索引）、[standards_questions.md](standards_questions.md) |
| 基準（工数・閾値・ルール）を変えたい | [standards_update.md](standards_update.md) |
| AIのモデルを更新した | [evaluation_guide.md](evaluation_guide.md)（「モデルを更新するとき」） |
| 結果が毎回少し違う理由を知りたい | [faq.md](faq.md)、[poc_report.md](poc_report.md) |
| コードを直したい | [architecture.md](architecture.md) |
| 評価結果の意味を知りたい | [evaluation_guide.md](evaluation_guide.md) |
| 設計の意図を知りたい | [設計書](ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md) |

## 文書を書く・直すときの約束

- 工数・閾値などの数値は、文書に書き写さない（正本は基準Excel）。説明に出てくる数値は、測定結果や例として示すものに限る。
- 仮のルール（COST-11〜13、BOUND-15〜19）は、確定するまで「仮」と明記する。
- 測定結果を書くときは、測定した日付と回数（各形式1回など）を添える。
- 文書を追加したら、この索引にも追加する。
- 文章は日本語で書く。識別子、コマンド、ファイルパス、ライブラリ名は英語のまま。
