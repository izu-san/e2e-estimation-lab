# はじめにやること（最初の1時間）

このリポジトリを初めて触る人が、全体をつかみ、1件の見積もりを最後まで体験するための手順です。
詳しい仕様は [README.md](../README.md) と [設計書](ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md) にあります。

## 0. 先に知っておくこと

- これは**実験段階（PoC）の仕組み**です。「AIが見積もりの下書きを作り、人が確認・承認する」ところまでを確かめました。
- **見積もりの正しさ（熟練者の見積もりや実績との一致）は未検証**です。出力を、そのまま顧客に出せる数字として扱わないでください。
- **基準の一部は仮ルール**です。基準Excelの COST-11〜13、BOUND-15〜19 は、PoCのために開発側が仮に決めて追記したものです。確定は基準の担当者が行います（[standards_questions.md](standards_questions.md)）。
- 詳しい検証結果は [poc_report.md](poc_report.md) にあります。まずここを15分で読むと、何がわかっていて何がわかっていないかをつかめます。

## 1. 環境を整える（約10分）

必要なもの: Python 3.11以上、[uv](https://docs.astral.sh/uv/)、Claude Code（`claude` コマンドが使え、ログイン済みであること）。

```bash
uv sync
uv run pytest -q
```

テストが通れば、ツール本体は正常です。テストはAIを使わないので、費用はかかりません。

`inputs/` の項目書と `standards/` の基準Excelは、検証のために作成した**サンプルデータ**で、リポジトリに含まれています。そのまま使えます。
実際の顧客資料や、社外秘の基準を使うときは、先に `.gitignore` で除外してから配置してください（誤ってコミットしないため）。

```bash
cp config/estimate.example.yaml config/estimate.yaml     # 既にある場合は不要
scripts/estimator inspect-standards --config config/estimate.yaml
```

`inspect-standards` が基準Excelを正しく読めていれば、工数表・閾値・判定軸が表示され、エラーは出ません。

## 2. 既存の結果を読む（約15分）

`runs/` には、過去の実行結果がフォルダごとに残っています（フォルダ名は `日時-項目書名-4桁`）。新しいものを1つ選び、次の順に開いてください。

1. `summary.md`: 結果の要約。「条件付きの仮定・条件」の一覧も読んでください。AIが「ここは前提を置いて見積もった」と言っている箇所です。
2. `estimate.xlsx`:
   - 「サマリー」: 下限・標準・上限の合計
   - 「個別ケース」: ケースごとの5軸の点数と理由
   - 「共通作業」: 共通部品の種別・数量・工数
   - 「確認事項」: AIが判断できずに残した質問
   - 「意味レビュー」: 別のAIが出した指摘と、その対応
   - 「レビュー」: 人が判定を記入するシート（記入方法は [review_guide.md](review_guide.md)）
3. `validation.json`: 機械検証の結果

見るときのコツ:

- 「一部未算定」と出ているときの「算定済み総計」は、**工数を出せた分だけの合計**です。案件全体の金額ではありません。
- 5軸の点数には、必ず根拠のセル位置が付いています。項目書の該当セルと見比べて、納得できるかを確認します。

## 3. 1件実行してみる（約30分）

AIの利用料がかかります。練習用の項目書（1件20ケース）で約15分かかります。

通常のClaude Codeセッションで実行する方法です。

```bash
claude
```

```text
/estimate-e2e inputs/AutomationExercise_01_詳細形式.xlsx --config config/estimate.yaml
```

- AIが各工程を進めます。途中で止まる場合や、質問が表示される場合があります。
- 不明点は、AIが `ai/questions.json` に書き残して先へ進みます。画面で確認を求められることは基本的にありません。
- 終わったら、`runs/` に新しいフォルダができています。手順2と同じ要領で結果を読んでください。

保護付きで実行する場合（AIが `runs/<id>/` 以外を書き換えられない）は、次を使います。

```bash
scripts/start-estimate-session.sh --input inputs/AutomationExercise_01_詳細形式.xlsx --config config/estimate.yaml
```

どちらの方法でも、同じ項目書を2回実行すると、細かい点数が変わることがあります。AIの判断は毎回少し揺れるのが普通です（揺れの大きさは [poc_report.md](poc_report.md) の測定結果を参照）。

## 4. 結果を人がレビューする（約15分）

[review_guide.md](review_guide.md) の手順で、`estimate.xlsx` の「レビュー」シートに判定を記入してみてください。
ここが、この仕組みで人が担う中心的な仕事です。

## 5. 困ったときは

| 状況 | 見る場所 |
|---|---|
| エラーコードの意味と対処 | [troubleshooting.md](troubleshooting.md) |
| 基準Excelを変えたい | [standards_update.md](standards_update.md) |
| コマンドの使い方 | [README.md](../README.md) の「コマンド一覧」 |
| なぜこの設計なのか | [設計書](ClaudeCode_E2E_Estimator_Implementation_Guide_v1.1.md) |
| 精度や残っている課題 | [poc_report.md](poc_report.md) |

## 6. やってはいけないこと

- 見積もり実行中に、ツール（`src/`）・基準Excel・検証ルールを書き換えてエラーを消すこと。
- `runs/<id>/estimate.json` を手で編集すること（再計算との不一致で検証が失敗します）。
- AIの出力に、工数や合計の数字を書き足すこと。数字は基準Excelからツールが計算します。
- 実際の顧客の項目書や社外秘の基準Excelを、除外設定（`.gitignore`）をしないままコミットすること。サンプルデータは対象外です。
- 複数の顧客の項目書を、1回の見積もりにまとめて渡すこと（1ファイル＝1案件）。
