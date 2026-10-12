# E2E自動化工数見積もり（AI + Pythonツール）

> [!CAUTION]
> **業務データは使っていません。
> 実データを使う前に会社のルールを確認してください**
>
> - **今回の技術検証で使ったデータに、業務データは一切含まれていません。**
>   項目書は、
>   練習用サイト [AutomationExercise](https://www.automationexercise.com) を題材に作ったサンプルです。
>   基準Excel（判定基準・工数表）の数値も、検証用に作った仮の値です。
> - **実際の業務データ（顧客の項目書、社内の工数基準など）をAIに読ませる場合は、セキュリティなど会社のルールに必ず従ってください。**
>   外部のAIサービスへ送信される可能性があるため、
>   利用の可否・許可された環境・マスキングの要否を、
>   事前に所管部門へ確認してください。
>   確認が取れるまでは実データを入力しないでください。


Excelのテスト項目書を読み込み、
**基準Excelに書かれた判定基準と工数表**を当てはめて、
Playwrightによる自動化の構築工数を見積もる実験用リポジトリです。

見積もりの手順は人が行う場合と同じです。
項目書を読み、テストケースに整理し、
共通部品（ページオブジェクトやログイン処理など）を洗い出し、
各ケースの難しさを採点して、基準の工数表から工数を引きます。
このうち「読んで判断する」部分をAI（Claude Code）が、
「数える・計算する・検算する」部分をPythonのツールが担当します。

- ドキュメント索引: [docs/README.md](docs/README.md)
- **はじめに読む**: [docs/handover.md](docs/handover.md)（最初の1時間の手順）
- よくある質問: [docs/faq.md](docs/faq.md)
- 新しい案件に使う: [docs/new_project.md](docs/new_project.md)
- 用語集: [docs/glossary.md](docs/glossary.md)
- 内部構造（開発者向け）: [docs/architecture.md](docs/architecture.md)
- 評価の読み方: [docs/evaluation_guide.md](docs/evaluation_guide.md)
- 結果のレビュー: [docs/review_guide.md](docs/review_guide.md)
- エラー対処: [docs/troubleshooting.md](docs/troubleshooting.md)
- 基準Excelの変更: [docs/standards_update.md](docs/standards_update.md)
- 要件・設計: [docs/ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md](docs/ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md)
- 検証結果のまとめ: [docs/poc_report.md](docs/poc_report.md)
- 基準Excelへの確認事項と決定の経緯: [docs/standards_questions.md](docs/standards_questions.md)
- レビュー用AIの評価設計: [docs/reviewer_agent_test_design.md](docs/reviewer_agent_test_design.md)

## 最初に押さえておくこと

### 何を任せていて、何を任せていないか

| 作業 | 担当 | 理由 |
|---|---|---|
| 項目書の読み取り（セル・結合・数式の抽出） | Pythonツール | 機械的に正確に行える |
| 項目の整理、共通部品の設計、5軸の採点 | AI | 文章を読んで意味を判断する作業 |
| 難易度の決定、工数の計算、集計 | Pythonツール | AIに計算させると誤るため、必ずツールで計算する |
| 提出内容のチェック（ID・根拠・二重計上など） | Pythonツール | 決まったルールで機械的に検査できる |
| 別の視点での見直し（意味レビュー） | 別のAI | 作成したAIとは別の「新しい会話」で読み直す |
| 最終確認・承認、基準の線引きの決定 | **人** | AIの判断の正しさは人が確認する |

大事な点が3つあります。

1. **工数の数字は基準Excelにしかありません。**
   ツールやAIへの指示文に数値を書き写していません。
   基準を直せば、次の見積もりから自動で追従します。
2. **AIは数字を書きません。**
   AIが書くのは「このケースは操作手順が2点」といった判断と、
   その根拠（元のセル位置）だけです。
   工数や合計を書いた提出物は、形式チェックで弾かれます。
3. **AIの判断は毎回少しぶれます。**
   同じ項目書でも実行のたびに採点が変わることがあります。
   そのため、ぶれを抑える仕組み（後述）と、人の確認が前提になっています。

### 用語

| 用語 | 意味 |
|---|---|
| Claude Code | AnthropicのAIが、ターミナルでファイルを読み書きしコマンドを実行しながら作業するツール。本リポジトリではこれが見積もりの判断を行う |
| Skill | Claude Codeに渡す「作業手順書」。`.claude/skills/estimate-e2e/` にあり、`/estimate-e2e` で呼び出す |
| ハーネス | AIの作業を支える周辺ツール一式（読み取り・検証・計算・出力）。`src/estimator/` と `scripts/estimator` |
| サブエージェント | メインのAIとは別の会話で動く、役割を限定したAI。ここでは意味レビュー専用（`estimate-reviewer`） |
| JSON | 構造化データの書式。AIの判断結果をこの形式でファイルに残す（`runs/<run_id>/ai/*.json`） |
| スキーマ | JSONに書いてよい項目と型の定義。違反するとエラーになる |
| run（ラン） | 1回の見積もり実行。成果物は `runs/<run_id>/` に全部まとまる |
| 基準Excel | 判定基準と仮置き工数が書かれた2冊のExcel（`standards/`）。工数の正本 |
| 5軸 | 個別ケースの採点軸。操作手順(AX-01)・確認手順(AX-02)・実装手段(AX-03)・あいまい度(AX-04)・データ準備後処理(AX-05)を各1〜3点で採点する |
| 意味レビュー | 見積もりの内容（分け方・採点・二重計上など）を、別のAIが読み直して指摘する工程 |

## 見積もりの流れ

```text
項目書(xlsx) ─▶ ① 読み取り ─▶ ② 項目の整理 ─▶ ③ 画面一覧 ─▶ ④ 共通設計
 (ツール)        (AI)        (AI)       (AI)
                                                  │
 ⑧ 人が確認 ◀─ ⑦ 意味レビュー ◀─ ⑥ 計算・検証・出力 ◀─ ⑤ 確認事項と採点
              (別のAI)         (ツール)             (AI)
```

1. **読み取り**: ツールが項目書の全セルを座標つきで取り出す。
2. **項目の整理**: AIが原項目をテストケースに整理する（分割・統合する場合は理由を記録）。
3. **画面一覧**: 案件に登場する画面を最初に一度だけ確定する。
   対象サイトを閲覧できる案件では、
   ツールがサイトを「見るだけ」で調べる（クリック・入力・送信はしない）。
4. **共通設計**: ページオブジェクト（PAGE）、共通UI（COMP）、
   業務フロー（FLOW）などの共通部品と、使うケースを決める。
5. **確認事項と採点**: 不明点は質問として残し（仮の数字は作らない）、
   5軸の点数と共通部品の難易度を、根拠セルつきで付ける。
6. **計算・検証・出力**: ツールが基準Excelの値で工数を計算し、
   結果を検算してExcelに出力する。
7. **意味レビュー**: 別のAIが成果物と原資料を読み、見落としや二重計上を指摘する。
   作成側が指摘ごとに対応を記録する。
8. **人の確認**: 「条件付き」「要確認」の項目と未対応の指摘を人が確認し、承認する。

各工程でAIが書いたJSONはツールが検査し、
誤りがあればエラー内容をAIに返して直させます（修正は初回提出のあと最大2回）。

### ぶれを抑える仕組み

AIの判断は、基準の文章に曖昧さがあるとぶれます。
そこで次の対策をとっています（詳細は [docs/poc_report.md](docs/poc_report.md)）。

- **線引きを基準に書く**: 曖昧な判断を基準Excelのルールに追記し、
  検査ツールがルールどおりかを照合する。
- **事実を先に確定する**: 画面一覧を先に作り、後の工程はそこから選ぶ。
  サイトを閲覧できる案件は実際に調べる。
- **手順をツールで強制する**: 「AIへの指示」だけでは手順が飛ばされることがあるため、
  守るべき手順は検査エラーで止める。

## セットアップ

前提: Python 3.11以上、[uv](https://docs.astral.sh/uv/)、Claude Code。

```bash
uv sync                       # 依存関係のインストール（pyproject.toml / uv.lock で固定）
uv run pytest -q              # テスト（人工データで動くので基準Excelが無くても実行できる）
cp config/estimate.example.yaml config/estimate.yaml    # 案件設定を作る
# standards/ に基準Excel 2冊、inputs/ に項目書を置く
scripts/estimator inspect-standards --config config/estimate.yaml   # 基準Excelが正しく読めるか確認
```

対象サイトを調べる案件だけ、追加で Node.js 18以上が必要です。

```bash
npm install --prefix tools/site-survey && tools/site-survey/node_modules/.bin/playwright install chromium
```

`inputs/` の項目書と `standards/` の基準Excelは、
検証用に作成したサンプルデータで、
リポジトリに含まれています（[inputs/README.md](inputs/README.md)、[standards/README.md](standards/README.md)）。
実際の顧客資料や社外秘の基準を使うときは、
先に `.gitignore` で除外してから配置してください。

## 見積もりの実行

実行方法は2通りあります。

### A. 通常のClaude Codeセッションから実行する

```bash
claude        # このリポジトリで起動
```

Claude Code上で次のように入力します。

```text
/estimate-e2e inputs/<項目書>.xlsx --config config/estimate.yaml
/estimate-e2e --project inputs/<案件マニフェスト>.yaml --config config/estimate.yaml   # 複数ファイルを1案件として見積もる
/estimate-e2e --run <run_id>                                                           # 途中で止まったrunの再開
```

- 利用者が明示的に入力したときだけ動きます（AIが勝手に起動することはありません）。
- 普通の開発用セッションの権限で動くため、AIはファイルを書き換えられる状態です。
  次のBのような書込み制限はありません。

### B. 保護付きで実行する（見積もりモード）

AIが書き込めるのを `runs/<run_id>/` だけに制限し、
入力・基準・ツール自体を誤って書き換えられないようにして実行します。

```bash
scripts/start-estimate-session.sh --input inputs/<項目書>.xlsx --config config/estimate.yaml
scripts/start-estimate-session.sh ... --print      # 起動コマンドの表示だけ（実行しない）
scripts/start-estimate-session.sh ... --headless   # 対話なしで最後まで実行
scripts/start-estimate-session.sh ... --sandbox    # OSレベルの書込み制限も追加（Linux/WSL2は要 bubblewrap・socat）
```

このスクリプトは、runの作成と読み取りを済ませたうえで、
そのrun専用の権限設定を生成してClaude Codeを起動します。
`--sandbox` を指定して必要なソフトが無い場合は、保護なしで実行せず、
起動を中止します。

```bash
sudo apt-get install bubblewrap socat   # --sandbox を使う場合のみ
```

### 開発モードと見積もりモード

| | 開発モード | 見積もりモード |
|---|---|---|
| 起動 | 通常の `claude` | `scripts/start-estimate-session.sh` |
| 書込み | 通常どおり | 現在の `runs/<run_id>/` のみ |
| 実行できるコマンド | 通常どおり | `scripts/estimator` のみ |
| Skill・ツールの改修 | 可 | 不可 |

ツールやSkillを直すときは開発モードで行い、`uv run pytest -q` を通してください。
見積もり中にAIが自分でツールを直してエラーを消すことは禁止しています。

## 途中経過の確認と再開

```bash
scripts/estimator status --run <run_id>
```

各工程が完了／失敗／再確認が必要（stale）のどれかを確認できます。

- **stale（再確認が必要）**: 上流の成果物（項目整理など）が変わったため、
  下流の工程の前提が古くなった状態。
  該当工程の `validate-stage` からやり直します。
  共通設計を変えたら採点も再確認が必要です。
- **modified**: 検証後に `ai/*.json` を手で変更した状態。同様にやり直します。
- **SOURCE_CHANGED が出た**: 実行開始後に入力・基準・設定が変更された。
  `extract` は拒否し、`validate` は「処理失敗」にします。
  結果が食い違うので、新しいrunを作り直してください。
- **failed_repair_limit**: 修正回数の上限（初回＋2回）に達した工程。
  エラーを残したまま計算・出力まで進み、結果には「検証失敗」と記録されます。

## 結果の見方（`runs/<run_id>/`）

まず見るのは次の3つです。

| ファイル | 内容 |
|---|---|
| `summary.md` | 結果の要約 |
| `estimate.xlsx` | 詳細。サマリー、個別ケース、共通作業、原項目との対応、画面一覧、確認事項、意味レビュー、人の判定記入用の「レビュー」シート、検証結果、実行条件 |
| `validation.json` | 検証結果と状態 |
| `annotated/<元ファイル名>_見積付き.xlsx` | 元の項目書のコピー。各項目の右隣に「自動化難易度(低/中/高/不可能)・自動化工数(標準)・懸念点・備考」の4列を追記。元ファイルは変更しない。共通作業の工数は項目に紐づかないため含まない。複数項目を統合したケースの工数は先頭項目にだけ計上 |

その他の成果物:

| ファイル | 内容 |
|---|---|
| `manifest.json` | 入力・基準・設定のハッシュ値（ファイルの指紋）、版、実行環境。同じ結果を再現できるかの手がかり |
| `standards.json` / `standards_cells.json` / `standards_text/` | 実行時に基準Excelから作った参照値（セル位置つき）と、基準の文章 |
| `raw_workbook.json` / `source_inventory.json` / `views/*.md` | 項目書の全セル、シート・領域の一覧と読み取り時の警告、AIが読むための座標つきテキスト |
| `ai/*.json` | AIの判断結果（項目整理、画面一覧、共通設計、確認事項、採点、意味レビュー） |
| `estimate.json` | ツールが計算した工数（構成案別に、下限・標準・上限） |
| `survey/` | 対象サイトの調査結果（調査した案件のみ） |
| `review/` | 意味レビューの記録（`ai_review.json`、`human_review.json`） |
| `stage_state.json` / `logs/` | 工程の状態とコマンド履歴 |

### 状態の言葉

似た言葉が複数あるので、混同しないでください。

| 項目 | 取りうる値 | 意味 |
|---|---|---|
| `difficulty`（難易度） | Low / Mid / High / Impossible / null | nullは判断材料が足りず難易度を決められない状態 |
| `estimate_status` | 確定可能 / 条件付き / 要確認 | 見積もりの確かさ。条件付きは「仮定が成り立つなら」の数字 |
| `scope` | 対象内 / 別見積 / 対象外 | 今回の見積もりに含めるか |
| `execution_status` | 処理成功 / 処理失敗 | ツールが正常に最後まで動き、再計算も一致したか。見積もり内容の正しさとは別 |
| `estimate_completeness` | 全対象算定 / 一部未算定 | 工数を出せなかった項目が残っていないか |
| `semantic_review_status` | 未実施 / AIレビュー済 / 人確認済 | 意味レビューの状況。AIレビュー済には「自己レビュー」（作成したAI自身の見直し）「未対応N件」なども併記される |

- 「処理成功」でも、内容を人が確認済みとは限りません。
- 「一部未算定」のとき、「算定済み総計」は案件全体の確定金額ではありません。
  出せた分だけの合計です。
- 意味レビューの指摘には、
  対応（`resolution`: fixed=修正 / question=質問に回す / rejected=不採用 / deferred=保留）を必ず記録します。
  未記録の指摘があると、レビュー済みにできません。

## 計算ルール

数値は基準Excelの値を使います。
ここでは考え方だけ示します（正確な条件は基準Excelの「総合判定」シートが正本です）。

**個別ケース**（上から順に判定）
1. 対象外・別見積のものを分ける。
2. 実現不可と確認済みならImpossible。工数は出さない。
3. 情報不足、または採点できない軸があれば「要確認」（難易度null、工数なし）。
4. いずれかの軸が3点、または5軸の合計がHigh閾値以上ならHigh。
5. 合計がLow上限以下ならLow。
6. 残りはMid。

**共通作業**
- 「種別ID|難易度」（例: `PAGE|Mid`）で共通工数表を引き、
  単価 × 構成要素の数で計算する。
- 基準に無い組合せは「未算定」にする。0や近似値で埋めない。
- 既存部品を流用する場合、新規実装分が0になるのは、
  存在と適合性が確認できたときだけ。
- 改修は、変更する責務を明記して同じ単価表を適用する（根拠のない割引はしない）。
- 他の作業に含めて計上するものは、重複して計上しない。
  同じ要素を二重に計上するとエラー。

**集計**
- 下限・標準・上限をそれぞれ合計する。
  算定できなかったものは合計に含めず、件数を残す。
- 基準Excelの数式は評価しない（保存されている計算結果だけを使い、無ければエラー）。

**計算規則の版**: 計算の仕方を変えたら `src/estimator/__init__.py` の版（現行 `case-rule-2` / `common-rule-2`）を必ず上げます。
上げ忘れはテスト（`tests/test_calc_version.py`）が検出します。
版が違う過去のrunは、
再計算の照合で「規則の版が変わった」という理由つきで失敗します（`calculate` を再実行すれば解消）。

## コマンド一覧

通常は上記の見積もり実行（Skill）が内部で呼びます。
直接使うのは、状態確認やデバッグのときです。
AIの判断が必要な工程があるため、コマンド1回で見積もりは完結しません。

```text
scripts/estimator init-run (--input X.xlsx | --project M.yaml) --config C.yaml [--run-id ID]   # runを作る
scripts/estimator extract --run ID                  # 項目書の読み取り
scripts/estimator render --run ID [--sheet S] [--rows 1-80]    # 座標つきテキストで表示
scripts/estimator profile --run ID --sheet S [--rows 5-304] [--header-row 4] [--columns B,G] [--group-by B]
                                                    # 列ごとの値の分布（大きな項目書の繰返し構造の把握）
  （AIが ai/normalized_cases.json → screens.json → common_design.json → questions.json → assessments.json を作成。
    questions は採点が参照するため採点より先）
scripts/estimator validate-stage --run ID --stage normalize|screens|common_design|questions|assessments|semantic_review
scripts/estimator survey --run ID                   # 対象サイトの調査（閲覧できる案件のみ）
scripts/estimator calculate --run ID                # 工数の計算 → estimate.json
scripts/estimator validate --run ID                 # 全体検証（再計算の照合を含む）→ validation.json
scripts/estimator export --run ID                   # → estimate.xlsx, summary.md
scripts/estimator mark-review --run ID --by ai --context independent|self | --by human [--reviewer 名前]
scripts/estimator status --run ID                   # 工程の状態の確認
scripts/estimator inspect-standards --config C.yaml [--show-text]    # 基準Excelの読み取り結果の確認
scripts/estimator evaluate --suite evals/suites/automationexercise.yaml   # 評価の実行
```

`--run` には run_id、または runディレクトリのパスを指定できます。

## テストと評価

### 自動テスト

```bash
uv run pytest -q
```

人工データで動くため、AIの利用料はかかりません。主な確認内容は次のとおりです。

| テスト | 確認内容 |
|---|---|
| `test_calculate.py` | 難易度判定（全軸1点／3点あり／未採点／Impossible など）、既存流用、数量、共通部品の二重計上防止、構成案の分離、再現性 |
| `test_standards.py` | 基準Excelの読み取り。基準の判定例12件と「判定集計例」（下限22・標準39・上限64人時）の再現、基準の値を変えたときの追従、不正な基準の検出（正本を置いていなければ一部skip） |
| `test_extract.py` | 項目書の読み取り。結合セル・非表示行・数式・画像・コメントの扱い、列順や名前が変わっても読めること |
| `test_pipeline.py` | 全工程の通し実行、手編集の拒否、AIが計算値を書いたときの拒否、上流変更による無効化 |
| `test_items.py` | 大規模項目書の展開、`.xlsm` の読み込み、状態の規則 |
| `test_review_and_coverage.py` | 意味レビューの指摘と対応の記録、画面一覧と各工程の整合 |
| `test_calc_version.py` | 計算規則の版の上げ忘れ検出 |
| `test_guardrails.py` | 保護機能（書込み拒否・スキーマ通知・見積もり設定の生成） |
| `test_survey.py` | 対象サイトの調査（URLの形の集約、除外URL、調査結果と画面一覧の照合、閲覧できない案件での拒否） |
| `test_reviewer_eval.py` | レビュー用AI評価の採点処理（オフライン部分） |

### 権限テスト（実機）

```bash
scripts/permission_check.sh [--keep]
```

使い捨てのディレクトリに人工データを複製し、
見積もりモードでClaude Codeを実際に起動して、
書込み制限が効いているかを**実行前後のファイル状態**で判定します（AIの返答では判定しません）。
結果は `runs/permission_check_*.json`。
AIの利用料がかかります。

### 評価（ばらつきの測定）

読み方の詳細は [docs/evaluation_guide.md](docs/evaluation_guide.md) を参照してください。
現在の期待事項はいずれも人確認済みではないため、評価結果は「暫定」です。

```bash
scripts/estimator evaluate --suite evals/suites/automationexercise.yaml
```

- 同じ内容を6種類の書式で書いた項目書（01〜06）を別々に見積もり、
  結果がどれだけそろうかを測ります。
  各ファイルは別案件として1つずつ実行します。
- 期待値（`evals/expectations/`）はAIの出力から作らず、人が確認します。
  `review_status` が `human_reviewed` でないものによる評価結果は「暫定」です。
- 工数や難易度のばらつきの許容幅（`tolerances`）は評価担当者が決めます。
  未記入のときは参考表示のみで、合否にはしません。
- 人の目視確認には、`estimate.xlsx` の「レビュー」シートを使います。

### レビュー用AIの評価

```bash
scripts/reviewer_eval.sh
```

意味レビューを行うAIが、
わざと仕込んだ欠陥を指摘できるかを測ります（AIの利用料がかかります。設計は [docs/reviewer_agent_test_design.md](docs/reviewer_agent_test_design.md)）。

## ディレクトリ構成

| パス | 内容 |
|---|---|
| `CLAUDE.md` | AIが常に守る原則 |
| `.claude/skills/estimate-e2e/` | 見積もりの手順書（`SKILL.md`）と、工程別の詳しい説明（`references/`） |
| `.claude/agents/estimate-reviewer.md` | 意味レビュー専用AIの定義（読み取り専用） |
| `config/estimate.example.yaml` | 案件設定の雛形（実際の設定は `estimate.yaml` にコピーして使う） |
| `config/standards_adapter.yaml` | 基準Excelの読み取り設定（見出しの文字列でシート・表を探す） |
| `config/claude-estimate.settings.json` | 見積もりモードの権限設定の雛形（runごとに実際のパスで生成） |
| `standards/` | 基準Excel（読み取り専用の正本） |
| `inputs/` | 顧客の項目書（読み取り専用） |
| `src/estimator/` | ツール本体 |
| `scripts/` | コマンドの入口、起動スクリプト、保護用の自動処理（Hooks）、権限テスト |
| `schemas/` | AIの提出JSONの定義（JSON Schema） |
| `evals/` | 評価の設定・期待値 |
| `tests/` | 自動テスト |
| `docs/` | 設計書・検証報告・確認事項 |
| `runs/<run_id>/` | 1回の見積もりの全成果物（Git管理外。不要になったら削除してよい。残す場合の扱いは [docs/handover.md](docs/handover.md)） |

## 制約・未対応事項

- **対応する入力**: `.xlsx` と `.xlsm`。
  `.xlsm` のマクロ（VBA）は実行も解析もせず、存在を警告するだけ。
  `.xls`、パスワード付き、破損ファイルは対応外として報告される。
- **画像・図形・グラフ**: 画像や図形の位置と図形内の文字だけを検出する。
  画像の中の文字は読まない。
  グラフシートは対象外。
- **大規模な項目書（例: 2,400件）**: AIが全行を読むのではなく、
  `profile` で繰返し構造を把握し、「何行目から何行目、
  何行で1項目」と宣言してツールに展開させる。
- **基準Excelの版**: v0.1（2026-10-10配置）で全項目の読み取りと回帰確認済み。
  版が変わったら `inspect-standards` で再確認する（[standards/README.md](standards/README.md)）。
- **保護の強さ**: 既定の保護は「権限ルール＋自動チェック（Hooks）＋実行できるコマンドの制限」で、
  OSによる書込み禁止ではない。
  許可するコマンドを増やすと保護が弱まるため、変更した場合は権限テストをやり直す。
- **`--sandbox` の限界**: sandbox内のコマンドからは、
  リポジトリ直下への新規ファイル作成や、
  他のrunへの書込みは防げない（Edit/Writeツールは別途拒否される）。
  厳密な分離が必要なら、
  入力・基準・実装を読み取り専用にしたコンテナで実行する（未実装）。
- **対応OS**: Linux / WSL2 で確認。
  起動スクリプトとHooksは bash と `.venv/bin/python` が前提で、
  ネイティブWindowsは未対応。
- **AIの判断部分**: Claude Codeのセッションが行うため、コマンド1回では完結しない。
  APIキーで動かす独自サービスは前提にしていない。
- **正しさは未検証**: 一貫性（形式が違っても同じ結果になるか）は測ったが、
  人の見積もりや実績工数との一致は測っていない。
  詳細は [docs/poc_report.md](docs/poc_report.md)。
