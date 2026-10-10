"""E2E自動化工数見積もりハーネス。

AIの意味判断（中間JSON）とスクリプトの決定的処理（抽出・検証・計算・出力）を分離する。
"""

__version__ = "0.1.0"

# 個別ケース総合判定ロジックの版。基準Excelの「文章」が変わったときは、
# このロジックが新しい文章と整合するかを確認したうえで版を上げる。
CASE_RULE_VERSION = "case-rule-1"
COMMON_RULE_VERSION = "common-rule-1"
