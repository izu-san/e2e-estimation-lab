# inputs/ — 顧客のテスト項目書（読取り専用）

`.xlsx` または `.xlsm`（OOXMLとして読む。VBAは実行しない）を配置する。ファイル名・シート名・列構成は任意（解析ロジックは特定形式に依存しない）。
見積もり実行中は変更禁止。ここにある項目書は作成したサンプルデータで、リポジトリに含めている。実際の顧客資料を置くときは、先に `.gitignore` で除外すること。

実験用に想定している配置（実装指示書 2.2）:

| ファイル | 状態 |
|---|---|
| `AutomationExercise_01_詳細形式.xlsx` | 配置済（2026-10-10） |
| `AutomationExercise_02_少数列_粗粒度.xlsx` | 配置済（2026-10-10） |
| `AutomationExercise_03_横持ち形式.xlsx` | 配置済（2026-10-10） |
| `AutomationExercise_04_複数行_結合セル.xlsx` | 配置済（2026-10-10） |
| `AutomationExercise_05_IDなし_重複候補.xlsx` | 配置済（2026-10-10） |
| `AutomationExercise_06_複数シート_説明混在.xlsx` | 配置済（2026-10-10） |
| `AutomationExercise_大規模テスト項目書_2400件.xlsm` | 配置済。本番想定の大規模項目書（2,400件）。実験対象 |

配置状況は `scripts/estimator evaluate --suite evals/suites/automationexercise.yaml` の `input_exists` でも確認できる。

複数ファイルで1案件とする場合は、案件マニフェスト（例）を用意して `--project` で指定する:
```yaml
schema_version: 1
project_name: sample-project
inputs:
  - {path: inputs/機能A.xlsx, role: 機能A項目書}
  - {path: inputs/機能B.xlsx, role: 機能B項目書}
```
