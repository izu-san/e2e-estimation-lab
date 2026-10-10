"""原項目の一括宣言（item_groups）と、ケースの項目指定（source_item_query）の展開。

大規模な項目書では、AIが数千件の原項目を1件ずつJSONへ書くのは現実的でない。
AIは「どのシートの何行目から何行目までが、何行で1項目か、IDはどの列か」を宣言し、
スクリプトがセルを読んで原項目へ展開する。意味判断（どこが項目表か、何行で1項目か）はAI、
機械的な展開と検証はスクリプトという責任分担を保つ。
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from openpyxl.utils import column_index_from_string

from .io_utils import read_json


def _E(code, path, message, severity="error"):
    return {"code": code, "path": path, "message": message, "severity": severity}


def sheet_index(raw: dict) -> dict[tuple[str, str], dict]:
    return {(wb["workbook_id"], sh["name"]): sh for wb in raw["workbooks"] for sh in wb["sheets"]}


def _cell_map(sheet: dict) -> dict[tuple[int, int], dict]:
    m = sheet.get("_cellmap")
    if m is None:
        m = {(c["row"], c["col"]): c for c in sheet["cells"]}
        sheet["_cellmap"] = m
    return m


def cell_value_text(sheet: dict, row: int, col_letter: str) -> str:
    c = _cell_map(sheet).get((row, column_index_from_string(col_letter)))
    if c is None:
        return ""
    if c["type"] == "formula":
        v = c.get("cached_value")
        return "" if v is None else str(v)
    v = c.get("value")
    return "" if v is None else str(v)


def _col_ok(letter: str | None) -> bool:
    return letter is None or bool(re.fullmatch(r"[A-Z]{1,3}", letter))


def expand_groups(norm: dict, raw: dict) -> tuple[list[dict], list[dict]]:
    """item_groups を source_items 形式へ展開する。戻り値: (展開した項目, エラー)。"""
    sheets = sheet_index(raw)
    items: list[dict] = []
    errs: list[dict] = []
    for gi, g in enumerate(norm.get("item_groups", [])):
        p = f"item_groups/{gi}({g['group_id']})"
        sh = sheets.get((g["workbook_id"], g["sheet"]))
        if sh is None:
            errs.append(_E("BAD_REF", p, f"存在しないブック/シートです: {g['workbook_id']}/{g['sheet']}"))
            continue
        for k in ("first_column", "last_column", "id_column", "title_column"):
            if not _col_ok(g.get(k)):
                errs.append(_E("BAD_COLUMN", p, f"{k} は列記号（例 A, AB）で指定してください: {g.get(k)}"))
        if any(e["path"] == p and e["code"] == "BAD_COLUMN" for e in errs):
            continue
        first, last, n = g["first_row"], g["last_row"], g["rows_per_item"]
        if first > last or last > sh["max_row"]:
            errs.append(_E("BAD_REF", p, f"行範囲 {first}-{last} がシートの使用範囲(1-{sh['max_row']})外です"))
            continue
        skip = set(g.get("skip_rows", []))
        rows = [r for r in range(first, last + 1) if r not in skip]
        if len(rows) % n != 0:
            errs.append(_E("BAD_GROUP", p, f"対象行数 {len(rows)} が rows_per_item={n} で割り切れません"
                                           "（見出し・空行は skip_rows で除外）"))
            continue
        fc, lc = g.get("first_column") or "A", g["last_column"]
        for k in range(0, len(rows), n):
            chunk = rows[k:k + n]
            start, end = chunk[0], chunk[-1]
            if end - start + 1 != n:
                errs.append(_E("BAD_GROUP", p, f"R{start}-R{end} は連続した {n} 行ではありません（skip_rows が項目の途中にあります）"))
                break
            seq = k // n + 1
            if g.get("id_column"):
                oid = cell_value_text(sh, start, g["id_column"]).strip()
                if not oid:
                    errs.append(_E("ITEM_ID_EMPTY", p, f"{g['sheet']}!{g['id_column']}{start} のIDが空欄です"
                                                       "（IDなしなら id_column を null にして item_id_prefix を使う）"))
                    continue
                item_id, original_id, assigned = oid, oid, False
            else:
                item_id, original_id, assigned = f"{g['item_id_prefix']}{seq:04d}", None, True
            title = cell_value_text(sh, start, g["title_column"]).strip() if g.get("title_column") else ""
            items.append({
                "item_id": item_id, "original_id": original_id, "id_assigned": assigned,
                "region_ids": list(g["region_ids"]),
                "refs": [{"workbook_id": g["workbook_id"], "sheet": g["sheet"], "range": f"{fc}{start}:{lc}{end}"}],
                "title": title,
                "step_count": g.get("step_count"), "expected_count": g.get("expected_count"),
                "data_pattern_count": g.get("data_pattern_count"),
                "disposition": g["disposition"], "duplicate_of": None, "reason": g.get("reason", ""),
                "group_id": g["group_id"], "_rows": (start, end),
            })
    return items, errs


def _match(text: str, cond: dict) -> bool:
    if "equals" in cond:
        return text.strip() == cond["equals"]
    if "contains" in cond:
        return cond["contains"] in text
    if "regex" in cond:
        return re.search(cond["regex"], text) is not None
    return False


def resolve_queries(norm: dict, group_items: list[dict], raw: dict) -> list[dict]:
    """cases[].source_item_query を source_item_ids へ解決する（norm を直接更新）。"""
    sheets = sheet_index(raw)
    errs = []
    by_group: dict[str, list[dict]] = {}
    for it in group_items:
        by_group.setdefault(it["group_id"], []).append(it)
    gdef = {g["group_id"]: g for g in norm.get("item_groups", [])}
    for ci, c in enumerate(norm["cases"]):
        q = c.get("source_item_query")
        if not q:
            continue
        p = f"cases/{ci}({c['case_id']})/source_item_query"
        matched: list[str] = []
        for gid in q["group_ids"]:
            if gid not in gdef:
                errs.append(_E("UNKNOWN_GROUP", p, f"item_group {gid} が存在しません"))
                continue
            g = gdef[gid]
            sh = sheets.get((g["workbook_id"], g["sheet"]))
            for it in by_group.get(gid, []):
                r0, r1 = it["_rows"]
                ok = True
                for cond in q.get("where", []):
                    if not _col_ok(cond["column"]):
                        errs.append(_E("BAD_COLUMN", p, f"列記号が不正です: {cond['column']}"))
                        ok = False
                        break
                    texts = [cell_value_text(sh, r, cond["column"]) for r in range(r0, r1 + 1)]
                    if not any(_match(t, cond) for t in texts):
                        ok = False
                        break
                if ok:
                    matched.append(it["item_id"])
        if not matched:
            errs.append(_E("EMPTY_QUERY", p, "条件に一致する原項目がありません"))
        c["source_item_ids"] = list(dict.fromkeys(list(c.get("source_item_ids", [])) + matched))
        c["_query_matched"] = len(matched)
    return errs


def expand_normalized(norm: dict, raw: dict) -> tuple[dict, list[dict]]:
    """AI提出の normalized_cases に item_groups と source_item_query を展開した版を返す。"""
    out = copy.deepcopy(norm)
    group_items, errs = expand_groups(out, raw)
    errs += resolve_queries(out, group_items, raw)
    for it in group_items:
        it.pop("_rows", None)
    out["source_items"] = list(out["source_items"]) + group_items
    for c in out["cases"]:
        c.pop("_query_matched", None)
    for sh in sheet_index(raw).values():
        sh.pop("_cellmap", None)
    return out, errs


def load_normalized(rd: Path) -> dict:
    """計算・出力・評価で使う、展開済みの項目整理。"""
    norm = read_json(rd / "ai/normalized_cases.json")
    if not norm.get("item_groups") and not any(c.get("source_item_query") for c in norm["cases"]):
        return norm
    expanded, _ = expand_normalized(norm, read_json(rd / "raw_workbook.json"))
    return expanded
