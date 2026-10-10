"""基準Excelの読込・検証。

基準Excelは「管理された形式」としてアダプター設定（config/standards_adapter.yaml）に従って読む。
値は元セルから取得し、数式は評価しない（保存済み計算結果のみ使用。無ければエラー）。
本モジュールに工数・閾値の数値を持たせてはいけない。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from . import CASE_RULE_VERSION, COMMON_RULE_VERSION
from .io_utils import sha256_json
from .workbook_reader import read_workbook, render_sheet


class StandardsError(Exception):
    def __init__(self, message: str, diagnostics: list[str] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or []


def norm(s: Any) -> str:
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s))
    t = re.sub(r"\s+", "", t)
    return t.lower()


def _alias_match(text: str, aliases: list[str]) -> bool:
    n = norm(text)
    if not n:
        return False
    for a in aliases:
        if a.startswith("re:"):
            if re.search(unicodedata.normalize("NFKC", a[3:]).lower(), n):
                return True
        elif n == norm(a):
            return True
    return False


def _numeric(cell: dict) -> tuple[float | None, str | None]:
    """数値セル→値。数式は保存済み計算結果を使い、無ければ理由を返す。"""
    if cell["type"] == "number":
        return float(cell["value"]), None
    if cell["type"] == "formula":
        if cell.get("cached_missing"):
            return None, "数式の保存済み計算結果がありません"
        v = cell.get("cached_value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v), None
        return None, f"数式の保存値が数値ではありません: {v!r}"
    if cell["type"] == "string":
        t = unicodedata.normalize("NFKC", cell["value"]).strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", t):
            return float(t), None
        return None, f"数値ではありません: {cell['value']!r}"
    return None, f"数値ではありません（型={cell['type']}）"


def _text(cell: dict | None) -> str:
    if cell is None:
        return ""
    if cell["type"] == "formula":
        v = cell.get("cached_value")
        return "" if v is None else str(v)
    return "" if cell.get("value") is None else str(cell["value"])


def _sheet_grid(sheet: dict) -> dict[tuple[int, int], dict]:
    return {(c["row"], c["col"]): c for c in sheet["cells"]}


def _iter_sheets(wb: dict, pattern: str | None):
    for sh in wb["sheets"]:
        if pattern is None or re.search(pattern, sh["name"]):
            yield sh


def find_table(wb: dict, spec: dict, what: str) -> dict:
    """必須列の見出しがすべて1行に揃う行を探す。0件・複数件はエラー。"""
    columns: dict[str, list[str]] = spec["columns"]
    optional: dict[str, list[str]] = spec.get("optional_columns", {}) or {}
    hits = []
    near = []
    for sh in _iter_sheets(wb, spec.get("sheet_pattern")):
        grid = _sheet_grid(sh)
        rows: dict[int, list[dict]] = {}
        for c in sh["cells"]:
            rows.setdefault(c["row"], []).append(c)
        for r, cells in rows.items():
            colmap: dict[str, int] = {}
            ambiguous = False
            for key, aliases in columns.items():
                m = [c["col"] for c in cells if c["type"] == "string" and _alias_match(c["value"], aliases)]
                if len(m) == 1:
                    colmap[key] = m[0]
                elif len(m) > 1:
                    ambiguous = True
            if len(colmap) == len(columns) and not ambiguous:
                for key, aliases in optional.items():
                    m = [c["col"] for c in cells if c["type"] == "string" and _alias_match(c["value"], aliases)]
                    if len(m) == 1:
                        colmap[key] = m[0]
                hits.append({"sheet": sh, "header_row": r, "colmap": colmap, "grid": grid})
            elif len(colmap) >= max(1, len(columns) - 1):
                near.append(f"{sh['name']}!R{r}: 一致列={sorted(colmap)} 不足={sorted(set(columns) - set(colmap))}"
                            + (" (重複一致あり)" if ambiguous else ""))
    if not hits:
        raise StandardsError(f"{what}: 必須見出し {list(columns)} を含む行が見つかりません", near[:20])
    if len(hits) > 1:
        raise StandardsError(
            f"{what}: 見出し行の候補が複数あります。アダプターでsheet_patternを指定してください",
            [f"{h['sheet']['name']}!R{h['header_row']}" for h in hits],
        )
    return hits[0]


def read_table_rows(hit: dict, key_col: str) -> list[dict]:
    """見出し行の下を、キー列が空になるまで読む。各値にセル座標を付与する。"""
    sheet, grid, colmap = hit["sheet"], hit["grid"], hit["colmap"]
    from openpyxl.utils import get_column_letter

    out = []
    r = hit["header_row"] + 1
    blank_run = 0
    while r <= sheet["max_row"]:
        kc = grid.get((r, colmap[key_col]))
        if kc is None or not _text(kc).strip():
            blank_run += 1
            if blank_run >= 1:
                break
            r += 1
            continue
        row = {"_row": r, "_sheet": sheet["name"]}
        for k, col in colmap.items():
            row[k] = grid.get((r, col))
            row[f"_ref_{k}"] = f"{sheet['name']}!{get_column_letter(col)}{r}"
        out.append(row)
        r += 1
    return out


def find_label_value(wb: dict, labels: list[str], what: str, sheet_pattern: str | None = None) -> dict:
    hits = []
    for sh in _iter_sheets(wb, sheet_pattern):
        grid = _sheet_grid(sh)
        for c in sh["cells"]:
            if c["type"] == "string" and _alias_match(c["value"], labels):
                # 同じ行の右側で最初の数値
                for col in range(c["col"] + 1, sh["max_col"] + 1):
                    vc = grid.get((c["row"], col))
                    if vc is None:
                        continue
                    val, err = _numeric(vc)
                    if val is not None:
                        hits.append({"label_ref": f"{sh['name']}!{c['ref']}", "ref": f"{sh['name']}!{vc['ref']}",
                                     "value": val, "formula": vc.get("formula")})
                        break
                    if err and vc["type"] == "formula":
                        raise StandardsError(f"{what}: {sh['name']}!{vc['ref']} {err}")
    uniq = {(h["value"]) for h in hits}
    if not hits:
        raise StandardsError(f"{what}: ラベル {labels} と数値の組が見つかりません")
    if len(uniq) > 1:
        raise StandardsError(f"{what}: ラベル一致が複数あり値が異なります（基準内の矛盾の可能性）",
                             [f"{h['ref']}={h['value']}" for h in hits])
    h = hits[0]
    h["all_refs"] = [x["ref"] for x in hits]
    return h


def _version(wb: dict, spec: dict, path: Path) -> dict:
    labels = spec.get("labels") or []
    for sh in wb["sheets"]:
        grid = _sheet_grid(sh)
        for c in sh["cells"]:
            if c["type"] == "string" and _alias_match(c["value"], labels):
                for col in range(c["col"] + 1, min(sh["max_col"], c["col"] + 4) + 1):
                    vc = grid.get((c["row"], col))
                    if vc is not None and _text(vc).strip():
                        v = norm(_text(vc)).lstrip("v")
                        return {"value": v, "source": f"{sh['name']}!{vc['ref']}"}
    pat = spec.get("from_filename")
    if pat:
        m = re.search(pat, path.name)
        if m:
            return {"value": m.group(1), "source": f"filename:{path.name}"}
    return {"value": None, "source": None}


def text_fingerprint(wb: dict) -> str:
    """非数値セル（文章）の指紋。文章変更をルール変更候補として検出する。"""
    items = []
    for sh in wb["sheets"]:
        for c in sh["cells"]:
            if c["type"] == "string":
                items.append([sh["name"], c["ref"], c["value"]])
    return sha256_json(items)


def _effort_values(row: dict, errors: list[str], label: str) -> dict | None:
    vals = {}
    for k in ("low", "std", "high"):
        cell = row.get(k)
        if cell is None:
            errors.append(f"{label}: {k} が空欄です ({row[f'_ref_{k}']})")
            return None
        v, err = _numeric(cell)
        if v is None:
            errors.append(f"{label}: {k} {err} ({row[f'_ref_{k}']})")
            return None
        vals[k] = v
    for k, v in vals.items():
        if v < 0:
            errors.append(f"{label}: {k} が負の数です ({row[f'_ref_{k}']})")
    if not (vals["low"] <= vals["std"] <= vals["high"]):
        errors.append(f"{label}: 下限≦標準≦上限 を満たしません {vals}")
    if vals["std"] <= 0:
        errors.append(f"{label}: 標準工数が正の数ではありません {vals}")
    return vals


def _approval(fp: str, approved: str | None, warnings: list[str], errors: list[str], what: str) -> str:
    if approved is None:
        warnings.append(f"{what}: 文章フィンガープリント未承認（ルール版の確認待ち） fp={fp}")
        return "unapproved"
    if approved != fp:
        errors.append(f"{what}: 基準の文章が承認時から変更されています。ルール実装の確認が必要です "
                      f"(approved={approved}, actual={fp})")
        return "changed"
    return "approved"


def load_cases_standard(path: Path, spec: dict) -> dict:
    wb = read_workbook(path, "STD-CASES")
    errors: list[str] = []
    warnings: list[str] = []
    ver = _version(wb, spec.get("version", {}), path)
    if ver["value"] is None:
        errors.append("個別基準: 基準版を特定できません")
    elif ver["value"] not in [str(v) for v in spec.get("supported_versions", [])]:
        errors.append(f"個別基準: 未対応の基準版です {ver['value']}（対応: {spec.get('supported_versions')}）")

    effort: dict[str, dict] = {}
    hit = find_table(wb, spec["effort_table"], "個別工数表")
    allowed = spec.get("difficulty_values", ["Low", "Mid", "High"])
    for row in read_table_rows(hit, "difficulty"):
        key = _text(row["difficulty"]).strip()
        matched = next((d for d in allowed if norm(d) == norm(key)), None)
        if matched is None:
            warnings.append(f"個別工数表: 難易度 {key!r} は対象外の行として扱います ({row['_ref_difficulty']})")
            continue
        if matched in effort:
            errors.append(f"個別工数表: 難易度 {matched} が重複しています ({row['_ref_difficulty']})")
            continue
        vals = _effort_values(row, errors, f"個別工数表[{matched}]")
        if vals:
            effort[matched] = {**vals, "refs": {k: row[f"_ref_{k}"] for k in ("difficulty", "low", "std", "high")}}
    for k in spec["effort_table"].get("required_keys", []):
        if k not in effort:
            errors.append(f"個別工数表: 必須の難易度 {k} の単価がありません")

    thresholds = {}
    for name in ("low_max", "high_min"):
        try:
            h = find_label_value(wb, spec["thresholds"][name]["labels"], f"閾値 {name}")
            thresholds[name] = {"value": h["value"], "ref": h["ref"], "label_ref": h["label_ref"],
                                "all_refs": h["all_refs"]}
        except StandardsError as e:
            errors.append(str(e) + ("; " + "; ".join(e.diagnostics) if e.diagnostics else ""))
    if "low_max" in thresholds and "high_min" in thresholds:
        if not thresholds["low_max"]["value"] < thresholds["high_min"]["value"]:
            errors.append(f"閾値: Low上限 < High閾値 を満たしません {thresholds}")

    axes = []
    try:
        ah = find_table(wb, spec["axes"], "判定軸一覧")
        for row in read_table_rows(ah, "axis_id"):
            axes.append({"axis_id": _text(row["axis_id"]).strip(), "name": _text(row["name"]).strip(),
                         "ref": row["_ref_axis_id"]})
    except StandardsError as e:
        errors.append(str(e))
    ids = [a["axis_id"] for a in axes]
    for rid in spec["axes"].get("required_ids", []):
        if rid not in ids:
            errors.append(f"判定軸: {rid} が基準にありません")
    if len(ids) != len(set(ids)):
        errors.append(f"判定軸: IDが重複しています {ids}")

    example = None
    if spec.get("example"):
        try:
            eh = find_table(wb, spec["example"], "判定例")
            rows = []
            for row in read_table_rows(eh, "example_id"):
                def num(k):
                    c = row.get(k)
                    return None if c is None else _numeric(c)[0]
                rows.append({
                    "example_id": _text(row["example_id"]).strip(),
                    "feasibility": _text(row["feasibility"]).strip() or None,
                    "assumption": _text(row["assumption"]).strip() or None,
                    "scores": [None if num(f"ax0{i}") is None else int(num(f"ax0{i}")) for i in range(1, 6)],
                    "expected": {"status": _text(row["status"]).strip() or None,
                                 "difficulty": _text(row["difficulty"]).strip() or None,
                                 "low": num("low"), "std": num("std"), "high": num("high")},
                    "ref": row["_ref_example_id"],
                })
            example = {"location": f"{eh['sheet']['name']}!R{eh['header_row']}", "rows": rows}
        except StandardsError as e:
            warnings.append(f"判定例を読めません（回帰テスト用）: {e}")

    fp = text_fingerprint(wb)
    approval = _approval(fp, spec.get("approved_text_fingerprint"), warnings, errors, "個別基準")
    return {
        "file": str(path), "file_name": path.name, "sha256": wb["sha256"], "size": wb["size"],
        "version": ver, "rule_version": CASE_RULE_VERSION,
        "effort": effort, "thresholds": thresholds, "axes": axes,
        "effort_table_location": f"{hit['sheet']['name']}!R{hit['header_row']}",
        "status_rule": spec.get("status_rule"),
        "example": example,
        "text_fingerprint": fp, "text_approval": approval,
        "errors": errors, "warnings": warnings + [f"読取警告 {w['code']} {w['ref']}" for w in wb["warnings"]],
        "_workbook": wb,
    }


def load_common_standard(path: Path, spec: dict) -> dict:
    wb = read_workbook(path, "STD-COMMON")
    errors: list[str] = []
    warnings: list[str] = []
    ver = _version(wb, spec.get("version", {}), path)
    if ver["value"] is None:
        errors.append("共通基準: 基準版を特定できません")
    elif ver["value"] not in [str(v) for v in spec.get("supported_versions", [])]:
        errors.append(f"共通基準: 未対応の基準版です {ver['value']}（対応: {spec.get('supported_versions')}）")

    known = list(spec.get("known_type_ids", []))
    allowed = spec.get("difficulty_values", ["Low", "Mid", "High"])
    effort: dict[str, dict] = {}
    hit = find_table(wb, spec["effort_table"], "共通工数表")
    for row in read_table_rows(hit, "type_id"):
        tid = _text(row["type_id"]).strip()
        diff_raw = _text(row["difficulty"]).strip()
        diff = next((d for d in allowed if norm(d) == norm(diff_raw)), None)
        label = f"共通工数表[{tid}|{diff_raw}]"
        if tid not in known:
            errors.append(f"{label}: 未知の種別IDです ({row['_ref_type_id']})")
            continue
        if diff is None:
            warnings.append(f"{label}: 難易度 {diff_raw!r} は工数行として扱いません ({row['_ref_difficulty']})")
            continue
        key = f"{tid}|{diff}"
        if key in effort:
            errors.append(f"{label}: 工数キー {key} が重複しています ({row['_ref_type_id']})")
            continue
        if "key" in row and row["key"] is not None:
            kt = norm(_text(row["key"]))
            if kt and kt != norm(key):
                errors.append(f"{label}: 工数キー列 {_text(row['key'])!r} と 種別ID|難易度 が一致しません ({row['_ref_key']})")
        vals = _effort_values(row, errors, label)
        if vals:
            effort[key] = {"type_id": tid, "difficulty": diff, "unit": _text(row["unit"]).strip() or None,
                           **vals, "refs": {k: row[f"_ref_{k}"] for k in ("type_id", "difficulty", "unit", "low", "std", "high")}}
            if not effort[key]["unit"]:
                errors.append(f"{label}: 単位が空欄です ({row['_ref_unit']})")
    present_types = sorted({v["type_id"] for v in effort.values()})
    missing_types = [t for t in known if t not in present_types]
    if missing_types:
        warnings.append(f"共通工数表: 単価行の無い種別ID {missing_types}（該当作業は未算定になります）")

    example = None
    ex_spec = spec.get("example")
    if ex_spec:
        try:
            eh = find_table(wb, ex_spec, "判定集計例")
            rows = []
            for row in read_table_rows(eh, "type_id"):
                q, qerr = (None, "空欄") if row.get("quantity") is None else _numeric(row["quantity"])
                rows.append({
                    "type_id": _text(row["type_id"]).strip(),
                    "difficulty": _text(row["difficulty"]).strip() or None,
                    "quantity": q, "quantity_error": qerr,
                    "status": _text(row.get("status")).strip() or None,
                    "kind": _text(row.get("kind")).strip() or None,
                    "ref": row["_ref_type_id"],
                })
            example = {"location": f"{eh['sheet']['name']}!R{eh['header_row']}", "rows": rows}
        except StandardsError as e:
            warnings.append(f"判定集計例を読めません（回帰テスト用）: {e}")

    fp = text_fingerprint(wb)
    approval = _approval(fp, spec.get("approved_text_fingerprint"), warnings, errors, "共通基準")
    return {
        "file": str(path), "file_name": path.name, "sha256": wb["sha256"], "size": wb["size"],
        "version": ver, "rule_version": COMMON_RULE_VERSION,
        "effort": effort, "type_ids": known, "types_with_effort": present_types,
        "effort_table_location": f"{hit['sheet']['name']}!R{hit['header_row']}",
        "example": example,
        "text_fingerprint": fp, "text_approval": approval,
        "errors": errors, "warnings": warnings + [f"読取警告 {w['code']} {w['ref']}" for w in wb["warnings"]],
        "_workbook": wb,
    }


def load_adapter(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_standards(cases_path: Path, common_path: Path, adapter: dict) -> dict:
    """両基準を読み、standards.json相当のdictを返す。'_workbook'キーは呼出し側で別保存する。"""
    out: dict[str, Any] = {"schema_version": 1, "adapter_version": adapter.get("adapter_version")}
    for key, loader, p in (("cases", load_cases_standard, cases_path), ("common", load_common_standard, common_path)):
        try:
            out[key] = loader(Path(p), adapter[key])
        except StandardsError as e:
            out[key] = {"file": str(p), "errors": [str(e)] + e.diagnostics, "warnings": [], "effort": {}}
        except FileNotFoundError:
            out[key] = {"file": str(p), "errors": [f"基準ファイルが見つかりません: {p}"], "warnings": [], "effort": {}}
    out["errors"] = out["cases"]["errors"] + out["common"]["errors"]
    out["warnings"] = out["cases"]["warnings"] + out["common"]["warnings"]
    return out


def standards_text(std_part: dict, exclude_sheet_patterns: list[str] | None = None) -> str:
    """AIに渡す基準の文章（座標つき）。既定は全シート。exclude_sheet_patterns に合うシートは省き、省いたシート名を明記する。"""
    wb = std_part.get("_workbook")
    if not wb:
        return "(読めませんでした)"
    pats = [re.compile(x) for x in exclude_sheet_patterns or []]
    keep = [sh for sh in wb["sheets"] if not any(p.search(sh["name"]) for p in pats)]
    omitted = [sh["name"] for sh in wb["sheets"] if sh not in keep]
    head = f"# {wb['file_name']} (sha256={wb['sha256']})\n\n"
    if omitted:
        head += f"> ダイジェスト: 次のシートは省略（説明用の例・出力仕様）: {', '.join(omitted)}。全文は同名の .md（ダイジェストでない方）を参照。判定例のID（EX-xx）を根拠に書く前に、全文で該当行を必ず確認する。\n\n"
    return head + "\n\n".join(render_sheet(sh) for sh in keep)


def digest_exclude_patterns(adapter_part: dict) -> list[str]:
    """ダイジェストで省くシートの正規表現。説明用の判定例シートと、アダプターの digest_exclude_sheets。"""
    pats = list(adapter_part.get("digest_exclude_sheets", []))
    ex = (adapter_part.get("example") or {}).get("sheet_pattern")
    if ex:
        pats.append(ex)
    return pats


def strip_private(std: dict) -> dict:
    return {k: ({kk: vv for kk, vv in v.items() if not kk.startswith("_")} if isinstance(v, dict) else v)
            for k, v in std.items()}
