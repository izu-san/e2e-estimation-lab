# 内部構造（開発者向け）

ツール（ハーネス）を改修・拡張する人向けの説明です。
使い方だけを知りたい場合は [README.md](../README.md) と [handover.md](handover.md) で足ります。
設計の考え方と要件は [設計書](ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md) にあります。

## 1. 全体の構造

```text
Claude Code（AI）                         Pythonハーネス（src/estimator/）
  Skill: .claude/skills/estimate-e2e/        ├─ 抽出   extract / workbook_reader / items
  意味判断 → runs/<id>/ai/*.json ──────────▶ ├─ 検証   validate（+ schemas/）
                                             ├─ 計算   calculate（基準は standards から）
  ◀─ エラー内容を返し、AIが直して再提出 ──── └─ 出力   export
```

- AIとハーネスの接点は、
  **ファイル**（`runs/<id>/` 配下のJSON）と**CLI**（`scripts/estimator <サブコマンド>`）だけです。
- AIが書くのは `runs/<id>/ai/*.json`、ハーネスが書くのは `runs/<id>/` 直下です。
  置き場所で作成者を区別します。
- 数値は基準Excelにしかありません。
  ハーネスは実行時に基準を読み、`runs/<id>/standards.json` を作ります。

## 2. モジュールの役割（`src/estimator/`）

| ファイル | 役割 |
|---|---|
| `cli.py` | CLIの入口。サブコマンドの定義と、各処理の呼び出し。`validate-stage` の修正回数の管理もここ |
| `run.py` | runの作成、工程の定義（`STAGES`、`STAGE_INPUTS`、`STAGE_OUTPUTS`、`AI_FILES`）、状態管理、上流変更による無効化、案件設定の既定値 |
| `workbook_reader.py` | Excelの構造抽出。セル・数式・保存値・結合・非表示・コメント・図形を、意味判断なしで保持する。顧客項目書と基準Excelの両方の下位処理 |
| `extract.py` | 項目書の読み取り工程。`raw_workbook.json`、`source_inventory.json`、`views/*.md`（座標つきテキスト）を作る |
| `items.py` | 大規模項目書向けの、原項目の一括宣言（`item_groups`）とケースの項目指定（`source_item_query`）の展開 |
| `standards.py` | 基準Excelの読み込み・検証。読み取り設定（`config/standards_adapter.yaml`）に従う。文章フィンガープリントの照合もここ |
| `validate.py` | 機械検証。工程ごとの検証関数（`validate_normalize`、`validate_screens`、`validate_common_design`、`validate_assessments`、`validate_questions`、`validate_semantic_review`）と、全体検証（`validate_all`）。工程名と関数の対応は `STAGE_VALIDATORS` |
| `calculate.py` | 決定的な計算器。AIの採点・共通設計・基準だけから難易度と工数を出す。`CASE_RULE_VERSION` / `COMMON_RULE_VERSION`（`__init__.py`）と対 |
| `export.py` | `estimate.xlsx`、`summary.md`、`annotated/*_見積付き.xlsx`（元の項目書へ難易度・工数などを追記したコピー）の出力。値はすべて `estimate.json` と `ai/*.json` から転記する |
| `survey.py` | 対象サイトの読み取りだけの調査。同じサイト内のリンクをたどり、URLの形ごとに1ページだけ保存する |
| `evaluate.py` | 評価ランナー（[evaluation_guide.md](evaluation_guide.md)） |
| `reviewer_eval.py` | レビュー用AIの評価。AIは呼ばず、変更の適用・応答の抽出・判定だけを行う（[reviewer_agent_test_design.md](reviewer_agent_test_design.md)） |
| `schemas.py` | `schemas/` のJSON Schemaによる検証 |
| `io_utils.py` | 原子的な保存（書き込み途中のファイルを他が読まない）、ハッシュ計算 |

その他の主な場所:

| パス | 役割 |
|---|---|
| `schemas/*.schema.json` | AI提出JSONと設定・マニフェストの型定義。工数や総合難易度の項目を持たせないことで、AIの計算値を拒否する |
| `scripts/estimator` | CLIの起動スクリプト |
| `scripts/start-estimate-session.sh` | 保護付き実行の外側ランナー（`init-run` → `extract` → 設定生成 → `claude` 起動） |
| `scripts/make_session_settings.py` | run専用の権限設定を、テンプレート（`config/claude-estimate.settings.json`）から絶対パスで生成 |
| `scripts/hooks/` | Claude CodeのHook。`pre_tool_guard.py`（保護対象への編集を拒否）、`post_tool_validate.py`（`ai/*.json` のスキーマ通知）、`stop_check.py`（成果物欠落の通知、最大2回） |
| `scripts/permission_check.sh` | 権限の実機テスト |
| `scripts/reviewer_eval.sh` / `.py` | レビュー用AIの評価の実行 |
| `config/standards_adapter.yaml` | 基準Excelの読み取り設定と、検証器の設定（`component_overlap`、`screen_rule`、`page_rule`、`component_rules` など） |
| `.claude/skills/estimate-e2e/` | AIへの手順書。`SKILL.md` と、工程別の `references/` |
| `.claude/agents/estimate-reviewer.md` | 意味レビュー専用AIの定義 |

## 3. 工程と状態管理

工程の並びは `run.py` の `STAGES` です。

```text
init → extract → normalize → screens → common_design → assessments → calculate → validate → export
```

- `STAGE_INPUTS` は、各工程が読む上流ファイルです。
  `runs/<id>/stage_state.json` に、
  工程完了時の上流ファイルのハッシュが記録されます。
- 再開時に上流のハッシュが変わっていると、その工程より下流が `stale` になります。
  `ai/*.json` が検証後に変更されていたら `modified` です。
- `questions`（質問）と `semantic_review`（意味レビュー）は、工程状態には載せず、
  `validate-stage` の対象としてだけ扱います。
- `validate-stage` は、
  エラーを数えて `validated` / `failed` / `failed_repair_limit` を返します。
  上限は `1 + max_repair_attempts`（初回＋修正回数）です。

計算の再現性は、
**同じAI成果物と基準から、同じ `estimate.json` が再計算できること**で担保します。
`validate_all` が毎回その場で再計算して照合します（`RECOMPUTE_MISMATCH`）。

## 4. 変更の種類ごとの手順

### 4.1 AI提出物の項目（スキーマ）を追加・変更する

1. `schemas/*.schema.json` に項目を追加する（必須にするかは、既存のrunとの互換性を考えて決める）。
2. `validate.py` の該当する検証関数に、整合チェックを追加する。
   - エラー（直さないと進めない）と警告（注意喚起）を分ける。
   - エラーコードは大文字の英数字で、メッセージは日本語で何を直すかを書く。
3. AIへの手順書を更新する：`.claude/skills/estimate-e2e/references/formats.md`（形式と例）、
   該当工程の説明、`errors.md`（新しいエラーコードの対処）。
4. テストを追加する（`tests/test_pipeline.py` など）。

### 4.2 新しい検証ルールを追加する

1. `validate.py` に関数を追加し、該当する工程の検証から呼ぶ。
2. 基準の数値や条件に依存する場合は、コードに書かず、
   `config/standards_adapter.yaml` に設定として置く（既存の `component_overlap`、`screen_rule`、`page_rule` が例）。
3. `references/errors.md` に、コードと対処を追加する。
4. 警告から始めて、AIが安定して守れるようになってからエラーにする。

### 4.3 計算の仕方を変える

1. `calculate.py` を修正する。
2. `src/estimator/__init__.py` のルール版（`CASE_RULE_VERSION` / `COMMON_RULE_VERSION`）を**必ず**上げ、
   変更点を同ファイルのコメントに書く。
3. `uv run pytest -q` を実行する。
   `tests/test_calc_version.py` が、
   固定入力の計算結果の指紋（`tests/golden/calculate_fingerprint.json`）で版の上げ忘れを検出する。
   意図した変更なら、指紋を更新する。
4. 版が違う過去のrunは `RULE_VERSION_CHANGED` になる。
   `calculate` の再実行で解消する。

### 4.4 工程を追加する

下の「5. 実例：画面一覧の工程の追加」を参照してください。

### 4.5 基準Excelの変更に伴う修正

[standards_update.md](standards_update.md) を参照してください。

### 4.6 開発の約束

- 改修は**開発モード**で行い、`uv run pytest -q` を通す。
  見積もり中（`ESTIMATOR_MODE=estimate`）は `runs/<id>/` 以外を変更しない。
- 検証器や基準を変えて、エラーを消さない。
- 工数・閾値の数値を、コード・Skill・JSONに書き写さない。
- コメント、ドキュメント、AIが書く文章は日本語にする。
  識別子・コマンド・パスは英語のまま。
- Skill（AIへの手順書）は、AIの挙動を左右する。
  変更したら、実際のrunで挙動を確認する。

## 5. 実例：画面一覧の工程の追加

画面の特定が工程ごとにぶれていたため、
共通設計の前に画面一覧（`ai/screens.json`）を確定させる工程を追加しました（コミット `4a3369d`）。
**新しい工程を足すときに触る場所**が、そのまま一覧になっています。

| 触った場所 | 内容 |
|---|---|
| `schemas/screens.schema.json`（新規） | 画面一覧の型定義 |
| `src/estimator/validate.py` | `validate_screens` を追加。PAGEの `elements` と一覧の過不足、AX-01の `operation_screens` と一覧の照合など。工程の検証一覧（`STAGE_VALIDATORS`）に登録 |
| `src/estimator/run.py` | `STAGES` に `screens` を追加。`AI_FILES`、`STAGE_INPUTS`、`STAGE_OUTPUTS` に追加。下流の `common_design`・`assessments` の入力に `ai/screens.json` を追加（一覧が変わると下流が stale になる） |
| `src/estimator/cli.py` | `validate-stage` の工程名の選択肢は `STAGE_VALIDATORS` から自動で決まる。工程名を並べている2か所（`calculate` の事前検証、`validate` の修正回数の集計）に `screens` を追加 |
| `src/estimator/evaluate.py` | 評価で「独立した試行か」を判定するAI成果物の一覧に追加 |
| `src/estimator/export.py` | Excelと `summary.md` に画面一覧を出力 |
| `scripts/hooks/post_tool_validate.py` | `screens.json` を、スキーマ通知の対象に追加 |
| `.claude/skills/estimate-e2e/SKILL.md` | 工程順に「画面一覧」を追加 |
| `.claude/skills/estimate-e2e/references/screens.md`（新規） | 画面の数え方の手順（BOUND-15 を項目書に当てはめる方法） |
| `references/assessment.md`、`common-design.md`、`errors.md`、`formats.md` | 下流の工程の説明を、画面一覧から選ぶ形に更新。新しいエラーコードの対処を追加 |
| `.claude/agents/estimate-reviewer.md` | レビュー用AIの観点に追加 |
| `tests/test_items.py`、`tests/test_pipeline.py` | 工程の追加に合わせたテストの更新 |
| `README.md`、`docs/standards_questions.md` | 工程の説明と、追加した経緯の記録 |

この工程の後に、2つの変更が続きました。

- 対象サイトの調査：`survey.py` と `survey` コマンドを追加し（`a1d983e`）、
  `STAGE_INPUTS` の `screens` に `survey/pages.json` を追加しました。
  調査を飛ばした場合は `SURVEY_MISSING` エラーにしました（`15ab90c`）。
- レビュー用AI：指摘の対象に画面IDを選べるようにしました（`d547421`、`review_target_ids`）。

### 工程を追加するときの要点

1. **スキーマ → 検証 → 工程の登録 → 手順書**の順に作る。
   先に手順書だけ書いても、
   AIは守らないことがある（検証エラーで強制するほうが確実）。
2. 工程の入力（`STAGE_INPUTS`）を正しく書く。
   ここが抜けると、上流が変わっても下流が stale にならない。
3. 工程を扱う箇所は複数ある（`cli.py` の2か所、`evaluate.py`、`export.py`、Hook）。
   `grep` で既存の工程名（例: `common_design`）を探し、漏れがないか確認する。
4. 工程を足すと、既存のrunが新しい検証に合わなくなる。
   古いrunは削除するか、新しいrunで確認する。
5. 効果を測るときは、
   各形式1回の測定では**施策の効果と実行のぶれを切り分けられない**ことに注意する（[poc_report.md](poc_report.md)）。

## 6. 保護の仕組みの構造

見積もりモードの保護は、3つの層で成り立っています。

| 層 | 実体 | 防ぐもの |
|---|---|---|
| 権限ルール | `config/claude-estimate.settings.json`（テンプレート）から生成した、run専用の設定 | 保護対象への編集ツールによる書き込み。許可外のコマンドの実行（Bashは `scripts/estimator` のみ） |
| Hook | `scripts/hooks/` | 権限ルールの補助（別のrunへの書き込みの拒否など）、`ai/*.json` のスキーマ通知、成果物欠落の通知 |
| OSサンドボックス（任意） | `config/claude-estimate.sandbox.json`、`--sandbox` | 許可されたコマンド内のプロセスによる書き込み |

- 環境変数 `ESTIMATOR_MODE=estimate` と `ESTIMATOR_RUN_DIR` が設定されているときだけ、
  Hookが働きます（通常の開発セッションでは何もしません）。
- Bashの許可リストを広げると、保護の中核が弱まります。
  変更したら `scripts/permission_check.sh` をやり直してください。
- 保護の限界は [README.md](../README.md) の「制約・未対応事項」を参照してください。

## 7. テストの構成

`uv run pytest -q` は、AIを使わずに（人工データで）動きます。
ファイルごとの内容は [README.md](../README.md) の「テストと評価」を参照してください。
改修の種類と、特に見るテストは次のとおりです。

| 改修 | 見るテスト |
|---|---|
| 計算 | `test_calculate.py`、`test_calc_version.py` |
| 基準の読み取り | `test_standards.py` |
| 項目書の読み取り | `test_extract.py`、`test_items.py` |
| 工程・検証 | `test_pipeline.py`、`test_review_and_coverage.py` |
| 保護 | `test_guardrails.py` |
| サイト調査 | `test_survey.py` |
| レビュー用AIの評価 | `test_reviewer_eval.py` |

`tests/helpers.py` の人工基準・人工項目書の生成関数を使うと、
基準Excelや顧客資料がなくてもテストを書けます。
