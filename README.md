# E2E自動化工数見積もり（Claude Code Skill + Pythonハーネス）

Excelのテスト項目書から、**基準Excelに書かれた判定基準と仮置き工数を適用して**Playwright自動化の構築工数を見積もる実験環境。
要件は [docs/ClaudeCode_E2E_Estimator_Implementation_Guide.md](docs/ClaudeCode_E2E_Estimator_Implementation_Guide.md)。

- 意味判断（項目の整理・共通部品の設計・5軸採点・共通作業の難易度）… Claude Code（Skill `/estimate-e2e`）
- 抽出・検証・計算・出力 … Python CLI（`scripts/estimator`）。AIが書いた計算値は採用せず、常に再計算する。
- 仮置き工数の妥当性・校正は対象外。数値は基準Excelからだけ取得する。

## 構成

| パス | 内容 |
|---|---|
| `CLAUDE.md` | 常時守る原則 |
| `.claude/skills/estimate-e2e/` | Skill本体（`SKILL.md`）と工程別の詳細（`references/`） |
| `.claude/agents/estimate-reviewer.md` | 意味レビュー専用サブエージェント（読取り専用。見積もり作成と別コンテキスト） |
| `config/estimate.example.yaml` | 案件設定の雛形 |
| `config/standards_adapter.yaml` | 基準Excelの読取りアダプター（見出し文字列で表・ラベルを特定） |
| `config/claude-estimate.settings.json` | 見積もりモード用の権限設定テンプレート（runごとに絶対パスで生成） |
| `standards/` | 基準Excel（正本・読取り専用）→ [standards/README.md](standards/README.md) |
| `inputs/` | 顧客項目書（読取り専用）→ [inputs/README.md](inputs/README.md) |
| `src/estimator/` | ハーネス本体 |
| `scripts/` | CLI入口、起動ランナー、Hooks、権限テスト |
| `schemas/` | 中間JSONのJSON Schema |
| `evals/` | 評価スイート・期待事項・回帰期待値 |
| `tests/` | 単体・統合・Hooksテスト（人工データを生成して使う） |
| `runs/<run_id>/` | 1回の見積もりの全成果物 |

## セットアップ

```bash
uv sync                       # Python 3.11+、依存は pyproject.toml / uv.lock で固定
uv run pytest -q              # テスト
cp config/estimate.example.yaml config/estimate.yaml
# standards/ に基準Excel 2冊、inputs/ に項目書を配置
scripts/estimator inspect-standards --config config/estimate.yaml   # 基準の読取り確認（standards/README.md 参照）
```

見積もりモード（保護付き実行）は既定で権限ルール＋Hookによる保護（OS非依存）。
追加でOSサンドボックスを使う場合（`--sandbox`）は、Linux/WSL2で `bubblewrap` と `socat` が必要:
```bash
sudo apt-get install bubblewrap socat   # --sandbox を使う場合のみ
```

## 実行方法

### A. 開発セッションから実行（MVPの基本経路）
Claude Code で:
```text
/estimate-e2e inputs/<項目書>.xlsx --config config/estimate.yaml
/estimate-e2e --project inputs/<案件マニフェスト>.yaml --config config/estimate.yaml   # 複数ファイルで1案件
/estimate-e2e --run <run_id>                                                           # 既存runの再開
```
Skillは `disable-model-invocation: true` のため、ユーザーが明示的に起動したときだけ動く。
この経路では保護設定は効いていない（通常の開発セッションの権限）。

### B. 見積もりモード（読取り専用の保護付き）
```bash
scripts/start-estimate-session.sh --input inputs/<項目書>.xlsx --config config/estimate.yaml
scripts/start-estimate-session.sh ... --print      # 起動コマンドを表示のみ
scripts/start-estimate-session.sh ... --headless   # claude -p で非対話実行
scripts/start-estimate-session.sh ... --sandbox    # OSサンドボックスを追加（Linux/WSL2はbubblewrap+socat必須）
```
ランナーが `init-run` → `extract` を行い、`runs/.sessions/<run_id>.settings.json` を生成して
`claude --settings <生成設定> --permission-mode dontAsk "/estimate-e2e --run <run_id>"` を起動する。
`--sandbox` 指定時に依存が無い場合は起動しない（無保護での実行を成功扱いにしない）。

### CLIの工程（AI解析はClaude Codeセッションが担当し、CLI 1回では完結しない）

```text
scripts/estimator init-run (--input X.xlsx | --project M.yaml) --config C.yaml [--run-id ID]
scripts/estimator extract --run ID                 # 構造抽出 → raw_workbook.json, source_inventory.json, views/*.md
scripts/estimator render --run ID [--sheet S] [--rows 1-80]   # 座標つきテキスト表示
scripts/estimator profile --run ID --sheet S [--rows 5-304] [--header-row 4] [--columns B,G] [--group-by B]
                                                   # 列ごとの値の分布（大規模資料の繰返し構造の把握）
  （AI）ai/normalized_cases.json, ai/screens.json（画面一覧）, ai/common_design.json, ai/questions.json, ai/assessments.json を作成（questionsは採点が参照するため採点より先）
scripts/estimator validate-stage --run ID --stage normalize|screens|common_design|questions|assessments|semantic_review
scripts/estimator calculate --run ID               # → estimate.json
scripts/estimator validate --run ID                # → validation.json（再計算照合を含む）
scripts/estimator export --run ID                  # → estimate.xlsx, summary.md
scripts/estimator mark-review --run ID --by ai --context independent|self | --by human [--reviewer 名前]
scripts/estimator status --run ID                  # 工程状態・上流変更による無効化
scripts/estimator inspect-standards --config C.yaml [--show-text]
scripts/estimator evaluate --suite evals/suites/automationexercise.yaml
```
`--run` には run_id または run ディレクトリのパスを指定できる。

### 再開
`scripts/estimator status --run ID` で各工程の状態を確認する。
- 上流ファイル（AI提出JSON・抽出結果・基準）のハッシュが記録と違うと、その工程より下流が `stale` になる。
  `ai/*.json` を検証後に変更した場合は `modified`。該当工程の `validate-stage` からやり直す。
- 共通設計を変えたら採点（assessments）が stale になる。影響ケースを再採点してから `calculate`。
- 入力・基準・設定・アダプターが実行開始後に変わると `SOURCE_CHANGED` で止まる。新しいrunを作る。
- 修正上限（既定: 初回提出＋修正2回）に達した工程は `failed_repair_limit`。その状態で計算・出力し、検証失敗として残す。

## 出力（`runs/<run_id>/`）

| ファイル | 内容 |
|---|---|
| `manifest.json` | run_id、入力/基準/設定/アダプターのSHA-256・サイズ、基準版、ハーネス版・git rev、環境 |
| `standards.json` / `standards_cells.json` / `standards_text/*.md` | 基準Excelから実行時に生成した参照値（セル位置つき）・セル一覧・全文 |
| `raw_workbook.json` | 全セル（型・原文・数式・保存値）、結合、非表示、コメント、図形位置 |
| `source_inventory.json` | シート・領域候補・読取り警告・制約 |
| `views/*.md` | AI読解用の座標つきテキスト（大きいシートは分割、境界を注記） |
| `standards_text/*.md` / `*.digest.md` | 基準Excelの文章（全文／判定例・出力仕様を省いたダイジェスト。読む順は digest → 必要なら全文） |
| `ai/*.json` | AI提出物（項目整理・共通設計・採点・確認事項・意味レビュー） |
| `estimate.json` | スクリプトが算出した工数（構成案別、下限/標準/上限） |
| `validation.json` | 機械検証・再計算照合・状態（execution_status / machine_validation / estimate_completeness / semantic_review_status） |
| `estimate.xlsx` | サマリー、個別ケース、共通作業、原項目対応、確認事項、意味レビュー、レビュー、検証結果、実行条件 |
| `summary.md` | 簡潔な結果 |
| `stage_state.json` / `logs/` | 工程状態・コマンド履歴 |

状態の意味は混同しない: `difficulty`（Low/Mid/High/Impossible/null）、`estimate_status`（確定可能/条件付き/要確認）、
`scope`（対象内/別見積/対象外）、`execution_status`（処理成功/処理失敗）、`estimate_completeness`（全対象算定/一部未算定）、
`semantic_review_status`（未実施/AIレビュー済/人確認済。AIレビュー済には「自己レビュー」「未対応N件」「レビュー記録後に見積もり変更」を括弧で併記）。
意味レビューの各指摘には対応（`resolution`: fixed/question/rejected/deferred）を記録し、`mark-review --by ai` は未記録の指摘があると拒否する。「算定済み総計」は一部未算定のとき案件全体の確定総額ではない。

## 計算ルール（実装）
- 計算規則の版は `src/estimator/__init__.py`（現行 `case-rule-2` / `common-rule-2`）。計算結果が変わる変更では必ず上げる。
  上げ忘れは `tests/test_calc_version.py` が固定入力の計算結果の指紋（`tests/golden/calculate_fingerprint.json`）で検出する。
  版が違う estimate.json は再計算照合で `RULE_VERSION_CHANGED`（手編集・上流変更の `RECOMPUTE_MISMATCH` と区別）。
- 個別ケース: 対象外/別見積を分離 → 実現不可確認済はImpossible → 情報不足・未採点軸ありは要確認(null)
  → いずれか3点または合計≧High閾値でHigh → 合計≦Low上限でLow → 残りMid。閾値・単価は基準Excelのセル値。
  原項目の未確定部分（`pending_parts`、ケースにせず保留したもの）は未解決件数に数える。
- 共通作業: `種別ID|難易度` で共通工数表を参照し、単価×構成要素数。基準にないキーは未算定（0や近似にしない）。
  既存流用は適合性確認済のときだけ新規実装分0。改修は変更責務を明示して同じ単価表を適用（割引なし）。
  `cost_owner` が他作業なら計上しない。同一構成案・同種別で同じ要素の重複計上は検証エラー。
- 下限・標準・上限をそれぞれ集計。null は合計から除き、未算定件数として残す。
- 数式は評価しない。基準の数式セルは保存済み計算結果のみ使い、無ければエラー。

## テスト

```bash
uv run pytest -q
```
- `test_calculate.py`: 総合判定（全軸1点/1〜2軸2点/3軸2点/3点あり/未採点/Impossible）、null工数、既存流用0、数量、共通部品の単一計上、改修、対象外、構成案分離、基準外キー、再現性、未算定件数。
- `test_standards.py`: 正本の「判定例」12件・「判定集計例」（22/39/64）の回帰、使い捨て人工基準での値追従、重複キー、下限≦標準≦上限、負数・非数値・空欄・単位欠落、未知の種別ID、未対応版、数式キャッシュ無し、文章変更検出、構造変更検出、判定集計例の再計算。正本配置時は「判定集計例」回帰（22/39/64）を実行（未配置ならskip）。
- `test_extract.py`: 結合セルを前方補完しない、非表示行/シート、数式キャッシュ無し、`=`始まりの文字列、列順・列名・シート名・ファイル名・説明行の変更、画像・コメント検出、非対応形式、出力時に数式化しない。
- `test_pipeline.py`: CLI全工程、手編集した estimate.json の拒否、AIの計算値提出の拒否、領域の処遇漏れと修正上限、重複計上、重複候補の根拠、不正なセル参照、上流変更による無効化、入力変更検出、案件マニフェスト、入力欠落の記録。
- `test_items.py`: 項目群の展開（複数行＋結合セル、IDなし、行数不整合、範囲外）、列の値による項目選択、.xlsm読込とVBA検出、大規模形式でのCLI全工程、見積もり状態規則（RULE-07・RULE-03）、共通作業のImpossible、条件一覧の出力。
- `test_review_and_coverage.py`: 意味レビュー指摘の対応記録と状態、計算規則の版変更の区別、未確定部分の保留、共通部品との二重加点の警告、前提行の追跡、形式横断の一貫性評価、AX-01の画面の数え方・共通作業の立て方・PAGEの難易度の仮ルール、画面一覧とPAGE・AX-01の照合。
- `test_calc_version.py`: 計算規則の版の上げ忘れ検出（固定入力の計算結果の指紋）。
- `test_guardrails.py`: Hooks（保護対象への編集拒否、スキーマ通知、Stopの回数制限）と見積もり設定の生成。

### 権限テスト（実機）
```bash
scripts/permission_check.sh [--keep]
```
使い捨てディレクトリに人工データでリポジトリを複製し、生成した見積もり設定で `claude -p` を起動して、
実行前後のファイル状態で判定する（AIの応答では判定しない）。結果は `runs/permission_check_*.json`。

## 評価
```bash
scripts/estimator evaluate --suite evals/suites/automationexercise.yaml
```
- 6ファイルは別案件として1ファイルずつ実行する。runは入力ハッシュが一致する最新runを自動選択。
- 期待事項（`evals/expectations/`）は実行時AIの出力から作らない。`review_status` が `human_reviewed` でない結果は暫定。
- 件数は評価資料にだけ記載し、解析ロジックには持たない。
- 人のレビューには `estimate.xlsx` の「レビュー」シート（AIの分解・採点・理由と、判定記入欄）を使う。
- `consistency_groups`: 同じ内容を別書式で書いた項目書群（01〜06）の最新runどうしで、工数・件数のばらつき、
  原IDごとの難易度の食い違い、入力ごとの試行回数（前のrunのAI成果物を流用したrunは独立試行に数えない）を出す。
  許容幅（`tolerances`）は評価担当者が決める。未記入なら `report_only` で合否にしない。
- 計算規則の版が変わった後の古いrunは `calculation_reproducible` が失敗し、理由に版の変更が出る（`calculate` の再実行で解消）。

## 開発モードと見積もりモードの切替

| | 開発モード | 見積もりモード |
|---|---|---|
| 起動 | 通常の `claude` | `scripts/start-estimate-session.sh` |
| 設定 | ユーザー/プロジェクト設定のみ | 上記＋ `runs/.sessions/<run_id>.settings.json`（`--settings`） |
| 書込み | 通常どおり | 現在の `runs/<run_id>/` のみ（Edit権限＋Hook。`--sandbox` 時は sandbox denyWrite も） |
| Hooks | 動作しない | PreToolUse（保護対象への編集拒否）/ PostToolUse（ai/*.jsonのスキーマ通知）/ Stop（成果物欠落を最大2回通知） |
| Skill/ハーネス改修 | 可 | 不可 |

既存の `~/.claude/settings.json`、プロジェクトの `.claude/settings.json` は変更しない（本リポジトリはプロジェクト設定を持たない）。
有効設定は見積もりセッション内で `/permissions`（`--sandbox` 時は `/sandbox` も）で確認できる。
Bashは `scripts/estimator` のみ許可（`dontAsk` のため他は拒否）。意味レビュー用の `estimate-reviewer` 以外のエージェントはdenyしている。

## 制約・未実装（MVP）
- 入力の正式対応は `.xlsx` と `.xlsm`（OOXMLとして読む。VBAは実行・解析せず、存在だけ警告）。`.xls`・パスワード保護（OLE形式）・破損ファイルは非対応として報告。
- 大規模資料（例：2,400件）は、AIが `item_groups`（行範囲・1項目の行数・ID列）で原項目を宣言し、スクリプトが展開する。
  ケースへの対応付けは `source_item_query`（列の値で選択）。AIが全行を読まずに済むよう `profile` で繰返し構造を把握する。
  画像・図形は位置と図形内テキストのみ検出し、画像内の文字は読まない。グラフシートは解析対象外。
- 基準Excelは `config/standards_adapter.yaml` の見出し候補で読む。v0.1正本（2026-10-10配置）で全項目の読取りと、判定例・判定集計例の回帰を確認済み。
  版が変わったら `inspect-standards` で再確認する（standards/README.md）。
- 既定（sandboxなし）の保護は、Edit権限・Hook・Bashの許可リスト（`scripts/estimator` のみ）。OSによる書込み禁止ではないため、
  許可リストを広げる変更をすると保護が弱まる。実機確認は `scripts/permission_check.sh`（`--sandbox` でsandbox付き）。
- `--sandbox` 時のsandboxの書込み制御は「作業ディレクトリは既定で書込み可」に対して保護対象を個別に `denyWrite` する方式。
  そのため sandbox 内の Bash からは、リポジトリ直下への**新規**ファイル作成や、**他の** `runs/<別id>/` への書込みは防げない
  （Edit/Writeツールは Hook と権限ルールで現在のrun以外を拒否）。厳密な分離が必要な場合は、入力/基準/実装を
  read-only マウントしたコンテナで実行する（未実装）。
- Hooks は（sandbox使用時も）sandbox の外で動く。Hook・起動スクリプトは `.venv/bin/python` と bash を前提とし、ネイティブWindowsは未対応。PostToolUse はスキーマのみの軽量検証。最終採否は `validate` の再計算で判断する。
- AI解析はClaude Codeセッションが行うため、CLI 1回では完結しない。APIキーを使う独自サービスは前提にしない。
