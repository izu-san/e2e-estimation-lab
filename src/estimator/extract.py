"""Stage 2: 顧客項目書の構造抽出。raw_workbook.json / source_inventory.json / views/*.md を作る。"""

from __future__ import annotations

from pathlib import Path

from .io_utils import read_json, write_json, write_text
from .workbook_reader import UnsupportedWorkbook, detect_regions, read_workbook, render_sheet


def _chunks(sheet: dict, regions: list[dict], chunk_rows: int) -> list[dict]:
    """行数で分割する場合も、領域の途中で切れたことと領域先頭行（見出し候補）を添える。"""
    if sheet["max_row"] <= chunk_rows:
        return [{"rows": (1, sheet["max_row"]), "context": []}]
    out = []
    lo = 1
    while lo <= sheet["max_row"]:
        hi = min(sheet["max_row"], lo + chunk_rows - 1)
        ctx = []
        for r in regions:
            if r.get("first_row") is None:
                continue
            if r["first_row"] < lo <= r["last_row"]:
                ctx.append({"region_id": r["region_id"], "continues_from_row": r["first_row"],
                            "header_rows": (r["first_row"], min(r["first_row"] + 2, lo - 1))})
            if lo <= r["first_row"] <= hi < r["last_row"]:
                ctx.append({"region_id": r["region_id"], "continues_after_row": hi})
        out.append({"rows": (lo, hi), "context": ctx})
        lo = hi + 1
    return out


def extract(rd: Path, chunk_rows: int = 80) -> dict:
    man = read_json(rd / "manifest.json")
    workbooks, regions, constraints, warnings = [], [], [], []
    views_dir = rd / "views"
    view_files = []
    for inp in man["inputs"]:
        wid = inp["workbook_id"]
        try:
            wb = read_workbook(inp["path"], wid)
        except FileNotFoundError:
            constraints.append({"workbook_id": wid, "path": inp["path"], "code": "NOT_FOUND",
                                "message": "入力ファイルが見つかりません。読んだことにしません"})
            continue
        except UnsupportedWorkbook as e:
            constraints.append({"workbook_id": wid, "path": inp["path"], "code": "UNSUPPORTED", "message": str(e)})
            continue
        workbooks.append(wb)
        warnings += [{"workbook_id": wid, **w} for w in wb["warnings"]]
        for sh in wb["sheets"]:
            sregs = detect_regions(sh, wid)
            regions += sregs
            for k, ch in enumerate(_chunks(sh, sregs, chunk_rows), start=1):
                lo, hi = ch["rows"]
                head = []
                for c in ch["context"]:
                    if "continues_from_row" in c:
                        h0, h1 = c["header_rows"]
                        head.append(f"<!-- 領域 {c['region_id']} は R{c['continues_from_row']} から続いています。"
                                    f"先頭行(見出し候補) R{h0}-R{h1} を以下に再掲 -->")
                        head.append(render_sheet(sh, h0, h1))
                    else:
                        head.append(f"<!-- 領域 {c['region_id']} は R{c['continues_after_row']} の後も続きます -->")
                name = f"{wid}_S{sh['index']}_part{k}.md"
                write_text(views_dir / name, "\n".join(head + [render_sheet(sh, lo, hi)]) + "\n")
                view_files.append({"file": f"views/{name}", "workbook_id": wid, "sheet": sh["name"], "rows": [lo, hi]})
        for cs in wb.get("chartsheets", []):
            constraints.append({"workbook_id": wid, "code": "CHARTSHEET", "message": f"グラフシート {cs} は解析対象外"})
        for sh in wb["sheets"]:
            for d in sh["drawings"]:
                constraints.append({"workbook_id": wid, "code": "DRAWING", "sheet": sh["name"], "anchor": d.get("anchor"),
                                    "message": f"{d['kind']} の内容（画像内の文字等）は読み取っていません"
                                               + (f"。図形テキスト: {d['text']!r}" if d.get("text") else "")})
    raw = {"schema_version": 1, "workbooks": workbooks}
    inventory = {
        "schema_version": 1,
        "workbooks": [{
            "workbook_id": wb["workbook_id"], "file_name": wb["file_name"], "sha256": wb["sha256"],
            "sheets": [{"index": s["index"], "name": s["name"], "state": s["state"], "max_row": s["max_row"],
                        "max_col": s["max_col"], "nonempty_cells": len(s["cells"]), "merged_count": len(s["merged"]),
                        "hidden_rows": s["hidden_rows"], "hidden_cols": s["hidden_cols"],
                        "comments": len(s["comments"]), "drawings": len(s["drawings"]),
                        "data_validations": len(s["data_validations"])} for s in wb["sheets"]],
        } for wb in workbooks],
        "regions": regions,
        "views": view_files,
        "warnings": warnings,
        "constraints": constraints,
        "counts": {"excel_rows_nonempty": sum(len({c["row"] for c in s["cells"]}) for wb in workbooks for s in wb["sheets"]),
                   "regions": len(regions)},
    }
    write_json(rd / "raw_workbook.json", raw)
    write_json(rd / "source_inventory.json", inventory)
    return {"workbooks": len(workbooks), "sheets": sum(len(w["sheets"]) for w in workbooks),
            "regions": len(regions), "views": [v["file"] for v in view_files],
            "warnings": len(warnings), "constraints": constraints}
