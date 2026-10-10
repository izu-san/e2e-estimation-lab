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
