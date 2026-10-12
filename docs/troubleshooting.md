# トラブルシューティング

見積もりの途中で止まったとき、エラーや警告が出たときの対処をまとめました。
AIが読む詳しい対応表は `.claude/skills/estimate-e2e/references/errors.md` にあります。
ここでは人が判断するときに必要な内容に絞っています。

## 1. まず確認すること

```bash
scripts/estimator status --run <run_id>      # 各工程の状態
```

結果の `validation.json` と `summary.md` の「警告の内訳」も見てください。
エラーと警告の違いは次のとおりです。

| 種類 | 意味 | 工程 |
|---|---|---|
| エラー | 直さないと先へ進めない（または検証が失敗する） | AIに直させる。修正は初回提出のあと最大2回 |
| 警告 | 注意が必要だが止まらない | 人が内容を見て、問題なら対応する |

AIによる修正が上限（初回＋2回）に達した工程は `failed_repair_limit` になり、
エラーを残したまま計算・出力まで進みます。
その場合は、結果に検証失敗と記録されます。

## 2. 人が判断する必要があるエラー

| コード | 意味 | 対処 |
|---|---|---|
| `SOURCE_CHANGED` | 実行開始後に、入力の項目書・基準Excel・設定のいずれかが変わった（`extract` は拒否し、`validate` は「処理失敗」にする） | そのrunは続けられない。新しいrunを作り直す（`init-run` か、保護付きなら `start-estimate-session.sh`） |
| `RECOMPUTE_MISMATCH` | 再計算した結果が `estimate.json` と合わない。`estimate.json` を手で編集した、または上流の成果物が変わった | `scripts/estimator calculate --run <run_id>` を再実行する。手で編集しない |
| `RULE_VERSION_CHANGED` | 計算規則の版が、そのrunを作った時と違う（ツールを改修した後に古いrunを見ている） | AIの成果物はそのままでよい。`calculate` → `validate` → `export` を再実行する |
| `SURVEY_MISSING` | 案件設定が `site.access: browsable` なのに、サイト調査の結果が無い | `scripts/estimator survey --run <run_id>` を実行してから、画面一覧の検証をやり直す。調査できない案件なら、設定を `unavailable` にする |
| `STANDARDS` | 基準Excelの読み取りか整合のエラー | 基準を直さず、該当セルと影響を記録する。基準を変更する場合は [standards_update.md](standards_update.md) |
| 「基準の文章が承認時から変更されています」 | 基準の文章が、承認済みの状態から変わった | 意図した変更なら承認値を更新（[standards_update.md](standards_update.md) 手順4）。意図しない変更ならExcelを戻す |
| `UNSOURCED_NUMBER` | AIが理由文などに、工数や合計点の数値を書いた | AIに書き直させる。数値は基準から計算するもので、AIが書くものではない |
| スキーマエラー（`SCHEMA`） | AIが、書いてはいけない項目（工数・難易度など）や、不正な値を書いた | AIに直させる |

## 3. 警告が出たとき

警告は、AIの判断に疑わしい点があることを示します。
ゼロにする必要はありませんが、内容は確認してください。

| コード | 何を疑っているか | 人の確認 |
|---|---|---|
| `AXIS_COMPONENT_OVERLAP` | 共通部品が行う作業を、ケースの点数にも数えていないか（二重計上） | ケース固有に残る作業が何かを確認し、点数が妥当かを判断する |
| `AX01_SCREEN_RULE` | 操作画面の数と、AX-01の点数が、基準（COST-13）と合わない | 操作画面の数え方が正しいかを確認する |
| `PAGE_DIFFICULTY_RULE` / `PAGE_MIXED_DIFFICULTY` | 画面の特徴から決まる難易度と、AIが付けた難易度が違う | 画面の特徴（入力数・動的な一覧・ダイアログなど）の記録が正しいかを確認する |
| `STEP_COUNT_MISMATCH` | 分解前後で手順数の数え方がそろっていない | 結合セルや複数行の手順の数え方を確認する |
| `SPECULATIVE_EVIDENCE` | 要確認のケースの根拠に、推測の表現がある | 「決められない軸は決めない」という扱いになっているかを確認する |
| `QUESTION_NOT_LINKED` | 質問と、それに関係するケースが結びついていない | 質問の影響範囲に漏れがないかを確認する |
| `SURVEY_PAGE_UNREVIEWED` | サイト調査で開いたページが、画面一覧に反映されていない | 画面として数えるべきかを確認する |
| `FINDING_UNRESOLVED` | 意味レビューの指摘に、対応が書かれていない | 対応を書くまでレビュー済みにはできない（[review_guide.md](review_guide.md)） |
| `PENDING_SPLIT_CASE` | 仕様が未提示の部分を、ケースとして切り出している | ケースにせず、原項目の保留にするべきかを確認する |

## 4. 実行環境のトラブル

| 症状 | 原因と対処 |
|---|---|
| `claude` コマンドが見つからない | Claude Code が未インストール、またはパスが通っていない。インストールとログインを確認する |
| `--sandbox` で起動しない | `bubblewrap` と `socat` が未導入。`sudo apt-get install bubblewrap socat`。Ubuntu 24.04以降は、AppArmorの設定が必要な場合がある（[設計書 2.3](ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md)）。保護なしでの実行は、意図的にできないようにしている |
| `.venv/bin/python` が無いというエラー | `uv sync` を実行する。Hooks・起動スクリプトはこのPythonを使う |
| Windowsのコマンドプロンプト／PowerShellで動かない | ネイティブWindowsは未対応。WSL2のLinux上で実行する |
| サイト調査（`survey`）が失敗する | Node.js 18以上と、`tools/site-survey` の導入（README参照）を確認する。調査対象のURLが `exclude_url_patterns` に該当していないかも確認する |
| 基準Excelが読めない | `scripts/estimator inspect-standards --config config/estimate.yaml` で原因を確認する。数式の保存結果が無い場合は、Excelで開いて保存し直す |
| 項目書が読めない | `.xls`、パスワード付き、破損ファイルは対応外。`.xlsx` に変換してから使う |
| 見積もりモードで、AIが「許可されていない」と言って止まる | 意図した動作。見積もりモードでは `scripts/estimator` 以外のコマンドと、`runs/<id>/` 外への書き込みを拒否している。開発作業は開発モード（通常の `claude`）で行う |

## 5. 結果の食い違いに困ったとき

| 状況 | 考え方 |
|---|---|
| 同じ項目書を2回実行したら、数字が違う | AIの判断は毎回少し揺れる。形式による合計の差は、PoCの最後の測定で7.5%だった（[poc_report.md](poc_report.md)）。ケース単位ではもっと揺れる |
| 形式が違う項目書で、結果が違う | 同じテスト内容でも、書式によって情報量が違う。差の大きさは [poc_report.md](poc_report.md) を参照 |
| 毎回同じ点で割れる | 基準の曖昧さが原因の可能性が高い。[standards_update.md](standards_update.md) の「基準の担当者に確認するべきとき」を参照 |
| 古いrunと新しいrunを比べたい | 計算規則の版が違うと比べられない場合がある。`manifest.json` の版と基準のハッシュを確認する |
