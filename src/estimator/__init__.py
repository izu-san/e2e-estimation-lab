"""E2E自動化工数見積もりハーネス。

AIの意味判断（中間JSON）とスクリプトの決定的処理（抽出・検証・計算・出力）を分離する。
"""

__version__ = "0.1.0"

# 計算ロジック（calculate.py）の版。基準Excelの「文章」が変わったときは、
# このロジックが新しい文章と整合するかを確認したうえで版を上げる。
# 計算結果（estimate.json の architectures）が変わる変更をしたときも必ず上げる。
# 上げ忘れは tests/test_calc_version.py が検出する（tests/golden/calculate_fingerprint.json）。
#   case-rule-2: 原項目の未確定部分（pending_parts）を未解決件数に数える
#   common-rule-2: 他部品へ計上した共通作業の estimate_status を「他へ計上」にする
CASE_RULE_VERSION = "case-rule-2"
COMMON_RULE_VERSION = "common-rule-2"
