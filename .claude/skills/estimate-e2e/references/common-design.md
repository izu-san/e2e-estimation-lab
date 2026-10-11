# Stage 4: 共通部分の設計（common_design.json）

スキーマ: `schemas/common_design.schema.json`。種別IDと判定条件は `standards_text/common.md` を読む（種類別の条件で難易度を決める。個別ケースの5軸合計ルールを転用しない）。

## 構成案（architectures）
- 案件設定 `architecture.pom` が `compare` なら POMあり/なし等の複数案、`unspecified` なら1案＋仮定を `assumptions` に書く。
- 構成案ごとに共通作業と個別採点を分けて計算する。案をまたいで合算しない。

## 共通作業（components）
各作業に: 種別(`type_id`)、`responsibility`（責務）、`need_reason`（必要性と、どのケースが使うか）、
`implementation_kind`、`elements`（数量に対応する構成要素ID。数量=要素数）、`used_by`、`depends_on`、`integrated_into`、`cost_owner`。

### 責務分担（重複計上の防止）
- AUTH＝認証本体、FIX＝準備順序・スコープ・解放。
- DATA＝データ投入・識別・復元本体、FIX＝そのライフサイクル。
- PAGE＝ページ固有の操作、COMP＝共通UI、FLOW＝部品を組み合わせる業務フロー。
- 部品の通常の動作確認は部品の単価に含む。RUNは全体の干渉・並列性・横断的確認。
- 20ケースが使う部品でも本体は1回だけ計上（`used_by` に20ケースを並べる）。
- 同じ構成案・同じ種別で同じ要素IDを2つの作業に入れない（検証で `DOUBLE_COUNT`）。

### 4つの関係は別物
| 項目 | 意味 |
|---|---|
| `depends_on` | 実装・実行の依存先（循環は検証エラー） |
| `used_by` | この部品を使う個別ケース |
| `integrated_into` | 説明上どの作業に統合したか |
| `cost_owner` | 工数をどの作業に計上するか（自分なら自分のID） |
説明用Excelの「依存/統合先」のような混在列をそのまま `depends_on` にしない。

### 実装区分
- `新規`: 種別×難易度の単価×数量。
- `改修`: `change_responsibility` に変更する責務を書く。割引率を作らない（同じ単価表を変更責務に適用）。
- `既存流用`: 適合性確認済みなら `reuse_verified: true` と確認・組込みの計上先 `reuse_integration_owner`。新規実装分だけ0になる。未確認なら要確認。
- `要確認`: 情報不足。工数null。
- `対象外`: `exclusion_reason` 必須。案件設定で除外された種別も対象外になる。

不明なCI要件などは `要確認` として残してよい。基準にない作業は作らず、questions に「基準外」として残す。

## used_by と採点の一致
`used_by` は、採点工程の `uses_components` と同じ集合にする。全ケースが使う部品（BASE・RUN など）も `used_by` に全ケースを並べ、
各ケースの `uses_components` にも入れる。要確認ケースも、前提にする部品を両方に書く。
PAGE は `responsibility` に挙げた画面と `elements` を一致させる（挙げた画面が要素に無い、または逆、を作らない）。

## ケースが検証する操作と、共通部品の操作が重なるとき
登録・ログインなど、ケース自体が検証する操作を共通部品（DATA の作成処理など）も実行する場合、実装の所有者を1つに決める。
共通部品が実処理を持ち、ケースはそれを呼んで固有の判定だけを持つ形にして、`need_reason` にその旨を書く。
ケースの AX-05 の evidence には、共通部品と重ならないケース固有の準備・後処理だけを書く。
一意なメールの生成だけが目的の利用は「入力値の違い」であり、DATA の利用者に含めるかを `need_reason` で説明する。

## 削除・解放の所有者を1文で書く（DATA と FIX）
専用ユーザー等の削除は「**削除の実処理は DATA、呼出し順序・スコープ・失敗時の解放保証は FIX**」と `responsibility` に明記する。
FIX が AUTH に `depends_on` を持つ場合は、その理由（例: 認証状態を fixture で束ねるため。認証本体の実装は AUTH）を `need_reason` に書く。

## 案件前提の記録（共通基準 GEN-07）
構成案の `assumptions` に、次の項目を確認できた事実または仮定として残す（資料に書かれていなければ仮定とし、質問・仮定にも起票する）。
- POM（採用／不採用／比較／未指定）、認証方式（UIログイン等）、API利用可否、既存資産・既存コード、CI。
- 実行環境の未調査項目（接続・広告表示など）と、実サイトに副作用を残す操作（登録・送信・購読など）の扱い。

## 共通作業の立て方（共通基準 構成と重複防止 BOUND-15〜18）
- **PAGE（BOUND-15）:** `elements` は画面一覧（`ai/screens.json`、工程4）の `screen_id` をそのまま使う。
  部品の分け方によらず、構成案ごとのPAGEの `elements` の合計を画面一覧と一致させる（過不足は `SCREEN_NOT_IN_PAGE` / `PAGE_NOT_IN_SCREENS` エラー）。
  画面の数え方を変えたいときは、PAGE ではなく画面一覧を直す。
- **COMP（BOUND-16）:** 2つ以上のケースが使い、2つ以上の画面に現れるUIだけ。1画面だけのUIはその画面の PAGE に含める。
- **FLOW（BOUND-17）:** 2つ以上のケース（または共通部品）が前提として呼ぶ業務操作列だけ。1ケースだけの操作列はケース内に置く。
- **RUN（BOUND-18）:** 複数ケースを一連の自動テストとして納めるなら必ず1式。単一環境の逐次実行は Low。要件が不明でも立て、仮定を質問に残す。
- 検証器の警告: `REQUIRED_COMPONENT_MISSING`（BASE・RUN が無い）、`COMPONENT_SINGLE_USE`（FLOW・COMP の利用が used_by と依存部品の合計で2件未満）。

## PAGE 等を数量でまとめるとき
- 画面数をそのまま部品数にしない。まとめる場合は、同種・同難易度・同責務の画面だけを `elements` に並べ、`need_reason` にまとめる理由を書く（BOUND-08・BOUND-13）。
- 責務や難易度が違う画面は別の部品に分ける。

## responsibility と used_by の整合
- `responsibility` に書いた機能の利用者は `used_by` に含めるか、含めない理由を `need_reason` に書く。責務から外した機能を `need_reason` で再び列挙しない。
- `used_by` に入れるのは、その部品の責務（入力・送信・取得など）を実際に使うケース。表示を確認するだけのケースを共通UI部品の利用者にしない。
- `responsibility` / `need_reason` に書いたケースIDが `used_by` に無いと `TEXT_CASE_NOT_IN_USED_BY` 警告になる（ID照合のみ。機能の記述と利用者の意味的な対応は意味レビューで見る）。
