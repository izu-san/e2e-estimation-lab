"""機械検証。構造・参照整合・計上の重複・計算再現性を確認する。

意味上の正しさ（採点が妥当か等）はここでは判断しない。
検証器はAI提出物を修正しない。エラーを具体的に返すだけ。
"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl.utils import get_column_letter, range_boundaries

from .calculate import calculate, compare_estimate
from .io_utils import read_json
from .items import expand_normalized, load_normalized
from .schemas import schema_errors


def E(code: str, path: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "path": path, "message": message, "severity": severity}


def _load(rd: Path, rel: str) -> tuple[dict | None, list[dict]]:
    p = rd / rel
    if not p.exists():
        return None, [E("MISSING_FILE", rel, f"{rel} がありません")]
    try:
        return read_json(p), []
    except ValueError as e:
        return None, [E("INVALID_JSON", rel, f"JSONとして読めません: {e}")]


def _dupes(ids: list[str]) -> list[str]:
    seen, d = set(), []
    for i in ids:
        if i in seen:
            d.append(i)
        seen.add(i)
    return d


def _check_ref(ref: dict, sheets: dict[tuple[str, str], dict], where: str) -> list[dict]:
    key = (ref["workbook_id"], ref["sheet"])
    sh = sheets.get(key)
    if sh is None:
        return [E("BAD_REF", where, f"存在しないブック/シートです: {ref['workbook_id']}/{ref['sheet']}")]
    try:
        min_col, min_row, max_col, max_row = range_boundaries(ref["range"])
    except ValueError:
        return [E("BAD_REF", where, f"範囲形式が不正です: {ref['range']}")]
    if max_row > sh["max_row"] or max_col > sh["max_col"]:
        return [E("BAD_REF", where, f"範囲 {ref['range']} がシートの使用範囲外です "
                                    f"(max_row={sh['max_row']}, max_col={sh['max_col']})")]
    return []


def _sheet_index(raw: dict) -> dict[tuple[str, str], dict]:
    return {(wb["workbook_id"], sh["name"]): sh for wb in raw["workbooks"] for sh in wb["sheets"]}


# ------------------------------------------------------------------ stages

def validate_normalize(rd: Path) -> list[dict]:
    data, errs = _load(rd, "ai/normalized_cases.json")
    if data is None:
        return errs
    errs = schema_errors("normalized_cases", data)
    if errs:
        return errs
    inv = read_json(rd / "source_inventory.json")
    raw = read_json(rd / "raw_workbook.json")
    data, exp_errs = expand_normalized(data, raw)
    errs += exp_errs
    sheets = _sheet_index(raw)
    region_ids = {r["region_id"] for r in inv["regions"]}
    for gi, g in enumerate(data.get("item_groups", [])):
        for rid in g["region_ids"]:
            if rid not in region_ids:
                errs.append(E("UNKNOWN_REGION", f"item_groups/{gi}({g['group_id']})", f"領域 {rid} は存在しません"))
        if g["id_column"] is None and not g.get("item_id_prefix"):
            errs.append(E("NO_ID_PREFIX", f"item_groups/{gi}({g['group_id']})", "id_column=null には item_id_prefix が必要です"))
        if g["disposition"] != "mapped" and not g["reason"].strip():
            errs.append(E("NO_REASON", f"item_groups/{gi}({g['group_id']})", f"{g['disposition']} には理由 reason が必要です"))
    given = [r["region_id"] for r in data["regions"]]
    for d in _dupes(given):
        errs.append(E("DUPLICATE_ID", "regions", f"領域 {d} の処遇が重複しています"))
    for missing in sorted(region_ids - set(given)):
        errs.append(E("REGION_NOT_DISPOSED", "regions", f"領域 {missing} の処遇がありません（無言で捨てない）"))
    for unknown in sorted(set(given) - region_ids):
        errs.append(E("UNKNOWN_REGION", "regions", f"source_inventoryに無い領域です: {unknown}"))

    items = data["source_items"]
    item_ids = [i["item_id"] for i in items]
    for d in _dupes(item_ids):
        errs.append(E("DUPLICATE_ID", "source_items", f"item_id {d} が重複しています"))
    item_by_id = {i["item_id"]: i for i in items}
    for n, it in enumerate(items):
        p = f"source_items/{n}({it['item_id']})"
        for rid in it["region_ids"]:
            if rid not in region_ids:
                errs.append(E("UNKNOWN_REGION", p, f"領域 {rid} は存在しません"))
        for k, ref in enumerate(it["refs"]):
            errs += _check_ref(ref, sheets, f"{p}/refs/{k}")
        for k, part in enumerate(it.get("pending_parts", [])):
            for j, ref in enumerate(part.get("refs", [])):
                errs += _check_ref(ref, sheets, f"{p}/pending_parts/{k}/refs/{j}")
        for k, inh in enumerate(it.get("inheritance", [])):
            errs += _check_ref(inh["ref"], sheets, f"{p}/inheritance/{k}/ref")
            errs += _check_ref(inh["from_ref"], sheets, f"{p}/inheritance/{k}/from_ref")
        if it["id_assigned"] and it["original_id"]:
            errs.append(E("ID_CONFLICT", p, "id_assigned=true の場合 original_id はnullにしてください"))
        if it["disposition"] == "merged_duplicate":
            if not it["duplicate_of"] or it["duplicate_of"] not in item_by_id:
                errs.append(E("BAD_DUPLICATE", p, "merged_duplicate には存在する統合先 duplicate_of が必要です"))
            if not it["reason"].strip():
                errs.append(E("NO_REASON", p, "重複統合の根拠 reason が必要です"))
        elif it["duplicate_of"] is not None and it["duplicate_of"] not in item_by_id:
            errs.append(E("BAD_DUPLICATE", p, f"duplicate_of {it['duplicate_of']} が存在しません"))
        if it["disposition"] in ("excluded", "needs_question") and not it["reason"].strip():
            errs.append(E("NO_REASON", p, f"{it['disposition']} には理由 reason が必要です"))

    errs += _overlaps(items)
    cases = data["cases"]
    for c in cases:
        if not c["source_item_ids"]:
            errs.append(E("NO_SOURCE", f"cases({c['case_id']})", "source_item_ids も source_item_query の一致もありません"))
    for d in _dupes([c["case_id"] for c in cases]):
        errs.append(E("DUPLICATE_ID", "cases", f"case_id {d} が重複しています"))
    used: dict[str, list[str]] = {}
    for n, c in enumerate(cases):
        p = f"cases/{n}({c['case_id']})"
        for sid in c["source_item_ids"]:
            if sid not in item_by_id:
                errs.append(E("UNKNOWN_ITEM", p, f"source_item {sid} が存在しません"))
            else:
                used.setdefault(sid, []).append(c["case_id"])
                if item_by_id[sid]["disposition"] != "mapped":
                    errs.append(E("ITEM_NOT_MAPPED", p, f"{sid} の disposition は {item_by_id[sid]['disposition']} です"))
        if c["relation"] == "merged" and len(c["source_item_ids"]) < 2:
            errs.append(E("BAD_RELATION", p, "merged は複数の source_item_ids が必要です"))
        if c["relation"] in ("split", "merged") and not c.get("relation_reason", "").strip():
            errs.append(E("NO_REASON", p, f"{c['relation']} には relation_reason が必要です"))
    for it in items:
        if it["disposition"] == "mapped" and it["item_id"] not in used:
            errs.append(E("ITEM_UNMAPPED", f"source_items({it['item_id']})", "mapped だがどのケースにも対応していません"))
    for sid, cids in used.items():
        if len(cids) > 1 and not all(c["relation"] == "split" for c in cases if c["case_id"] in cids):
            errs.append(E("BAD_RELATION", f"source_items({sid})",
                          f"複数ケース {cids} に対応しますが relation が split ではありません"))
    # 1項目だけから分解したケースの手順数が親項目と合わない場合は警告（数え方の不整合を見つける）
    for sid, cids in used.items():
        it = item_by_id.get(sid)
        if it is None or it["step_count"] is None:
            continue
        kids = [c for c in cases if c["case_id"] in cids and c["source_item_ids"] == [sid]]
        if len(kids) > 1 and len(kids) == len(cids):
            total = sum(c["step_count"] for c in kids)
            if total != it["step_count"]:
                errs.append(E("STEP_COUNT_MISMATCH", f"source_items({sid})",
                              f"分解先 {cids} の step_count 合計 {total} が親項目の step_count {it['step_count']} と一致しません。"
                              "数え方（→区切り等）を親子で揃えるか、差の理由を relation_reason に書いてください", "warning"))
    # 統合した重複項目は source_item_ids に入れられないため、統合先ケースの文章に ID が残っているか確認する
    for it in items:
        if it["disposition"] != "merged_duplicate" or it["duplicate_of"] not in item_by_id:
            continue
        target_cases = [c for c in cases if it["duplicate_of"] in c["source_item_ids"]]
        if target_cases and not any(it["item_id"] in " ".join([c.get("relation_reason", ""), c.get("notes", ""), c.get("summary", "")])
                                    for c in target_cases):
            errs.append(E("DUPLICATE_NOT_TRACED", f"source_items({it['item_id']})",
                          f"統合先ケース {[c['case_id'] for c in target_cases]} の notes / relation_reason に {it['item_id']} の統合が書かれていません。"
                          "統合元から統合先ケースを辿れるようにしてください", "warning"))
    # parsedの領域にテスト項目が1件も無い場合は警告
    regions_with_items = {rid for it in items for rid in it["region_ids"]}
    for r in data["regions"]:
        if r["disposition"] == "parsed" and r["role"] != "data_definition" and r["region_id"] not in regions_with_items:
            errs.append(E("EMPTY_PARSED_REGION", f"regions({r['region_id']})",
                          "parsed ですがsource_itemがありません", "warning"))
    return errs


def _overlaps(items: list[dict]) -> list[dict]:
    """原項目どうしのセル範囲の重なり（同じ行を2つの項目に数えていないか）を検出する。"""
    spans: dict[tuple[str, str], list[tuple[int, int, str]]] = {}
    for it in items:
        for ref in it["refs"]:
            try:
                _, r0, _, r1 = range_boundaries(ref["range"])
            except ValueError:
                continue
            spans.setdefault((ref["workbook_id"], ref["sheet"]), []).append((r0, r1, it["item_id"]))
    errs = []
    for (wid, sheet), lst in spans.items():
        lst.sort()
        for (a0, a1, aid), (b0, b1, bid) in zip(lst, lst[1:]):
            if b0 <= a1 and aid != bid:
                errs.append(E("ITEM_OVERLAP", f"source_items({bid})",
                              f"{sheet} R{b0}-R{b1} が {aid}（R{a0}-R{a1}）と重なっています", "warning"))
    return errs


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    color: dict[str, int] = {}
    found = []

    def dfs(n, stack):
        color[n] = 1
        stack.append(n)
        for m in graph.get(n, []):
            if color.get(m) == 1:
                found.append(stack[stack.index(m):] + [m])
            elif color.get(m) is None and m in graph:
                dfs(m, stack)
        stack.pop()
        color[n] = 2

    for n in graph:
        if color.get(n) is None:
            dfs(n, [])
    return found


def validate_common_design(rd: Path) -> list[dict]:
    data, errs = _load(rd, "ai/common_design.json")
    if data is None:
        return errs
    errs = schema_errors("common_design", data)
    if errs:
        return errs
    std = read_json(rd / "standards.json")
    known_types = set(std["common"].get("type_ids") or [])
    norm, _ = _load(rd, "ai/normalized_cases.json")
    case_ids = {c["case_id"] for c in (norm or {}).get("cases", [])}
    arch_ids = [a["arch_id"] for a in data["architectures"]]
    for d in _dupes(arch_ids):
        errs.append(E("DUPLICATE_ID", "architectures", f"arch_id {d} が重複しています"))
    comps = data["components"]
    for d in _dupes([c["component_id"] for c in comps]):
        errs.append(E("DUPLICATE_ID", "components", f"component_id {d} が重複しています"))
    by_id = {c["component_id"]: c for c in comps}
    raw = read_json(rd / "raw_workbook.json")
    sheets = _sheet_index(raw)
    element_owner: dict[tuple[str, str, str], str] = {}
    for n, c in enumerate(comps):
        p = f"components/{n}({c['component_id']})"
        if c["type_id"] not in known_types:
            errs.append(E("UNKNOWN_TYPE", p, f"共通基準に無い種別IDです: {c['type_id']}"))
        for a in c["arch_ids"]:
            if a not in arch_ids:
                errs.append(E("UNKNOWN_ARCH", p, f"構成案 {a} がありません"))
        for u in c["used_by"]:
            if u not in case_ids:
                errs.append(E("UNKNOWN_CASE", p, f"used_by のケース {u} が存在しません"))
        used = set(c["used_by"])
        mentioned = sorted({m for m in re.findall(r"[A-Za-z]+-\d+", f"{c['responsibility']} {c['need_reason']}")
                            if m in case_ids and m not in used})
        if mentioned:
            errs.append(E("TEXT_CASE_NOT_IN_USED_BY", p,
                          f"responsibility/need_reason が挙げたケース {', '.join(mentioned)} が used_by にありません。"
                          "利用者に含めるか、含めない理由を need_reason に書き、挙げ方を揃えてください", "warning"))
        for fld in ("depends_on",):
            for dep in c[fld]:
                if dep not in by_id:
                    errs.append(E("UNKNOWN_COMPONENT", p, f"{fld} の {dep} が存在しません"))
                elif dep == c["component_id"]:
                    errs.append(E("SELF_DEPENDENCY", p, "自分自身へ依存しています"))
        if c["integrated_into"] is not None and c["integrated_into"] not in by_id:
            errs.append(E("UNKNOWN_COMPONENT", p, f"integrated_into {c['integrated_into']} が存在しません"))
        if c["cost_owner"] not in by_id:
            errs.append(E("UNKNOWN_COMPONENT", p, f"cost_owner {c['cost_owner']} が存在しません"))
        elif c["cost_owner"] != c["component_id"]:
            owner = by_id[c["cost_owner"]]
            if owner["cost_owner"] != owner["component_id"]:
                errs.append(E("COST_OWNER_CHAIN", p, f"計上先 {owner['component_id']} 自体が他へ計上されています"))
            if not set(c["arch_ids"]) <= set(owner["arch_ids"]):
                errs.append(E("COST_OWNER_ARCH", p, "計上先が同じ構成案に含まれていません"))
        kind = c["implementation_kind"]
        if kind == "改修" and not (c.get("change_responsibility") or "").strip():
            errs.append(E("NO_CHANGE_RESPONSIBILITY", p, "改修には変更責務 change_responsibility が必要です"))
        if kind == "既存流用":
            if c.get("reuse_verified") is None:
                errs.append(E("REUSE_UNVERIFIED", p, "既存流用には reuse_verified の明示が必要です", "warning"))
            own = c.get("reuse_integration_owner")
            if c.get("reuse_verified") and (not own or own not in by_id):
                errs.append(E("REUSE_NO_OWNER", p, "適合性確認済みの既存流用には確認・組込みの計上先が必要です"))
        if kind == "対象外" and not (c.get("exclusion_reason") or "").strip():
            errs.append(E("NO_REASON", p, "対象外には exclusion_reason が必要です"))
        for k, ref in enumerate(c.get("source_refs", [])):
            errs += _check_ref(ref, sheets, f"{p}/source_refs/{k}")
        # 同じ構成案・同じ種別で同じ構成要素を重ねて計上していないか
        if c["cost_owner"] == c["component_id"] and kind in ("新規", "改修"):
            for a in c["arch_ids"]:
                for el in c["elements"]:
                    k = (a, c["type_id"], el)
                    if k in element_owner:
                        errs.append(E("DOUBLE_COUNT", p, f"構成案{a}で要素 {el}（{c['type_id']}）が "
                                                         f"{element_owner[k]} と重複計上されています"))
                    else:
                        element_owner[k] = c["component_id"]
    for cyc in _cycles({c["component_id"]: c["depends_on"] for c in comps}):
        errs.append(E("DEPENDENCY_CYCLE", "components", f"依存関係が循環しています: {' → '.join(cyc)}"))
    errs += _component_rules(data, std)
    return errs


def _component_rules(design: dict, std: dict) -> list[dict]:
    """共通作業の立て方（共通基準 BOUND-16〜18）。必須の種別と、FLOW・COMP の最小利用数（警告）。
    種別と数はアダプター（common.component_rules）から取る。"""
    rule = std["common"].get("component_rules") or {}
    if not rule:
        return []
    errs: list[dict] = []
    comps = [c for c in design["components"] if c["implementation_kind"] != "対象外"]
    for arch in design["architectures"]:
        types = {c["type_id"] for c in comps if arch["arch_id"] in c["arch_ids"]}
        for t in rule.get("required_types") or []:
            if t not in types:
                errs.append(E("REQUIRED_COMPONENT_MISSING", f"architectures({arch['arch_id']})",
                              f"構成案 {arch['arch_id']} に {t} がありません（共通基準 構成と重複防止 BOUND-18 等）。"
                              "要件が不明なら仮定を置いて立て、仮定を質問に残してください", "warning"))
    dependents: dict[str, int] = {}
    for c in comps:
        for dep in c["depends_on"]:
            dependents[dep] = dependents.get(dep, 0) + 1
    for c in comps:
        need = (rule.get("min_users") or {}).get(c["type_id"])
        users = len(c["used_by"]) + dependents.get(c["component_id"], 0)
        if need and c["cost_owner"] == c["component_id"] and users < need:
            errs.append(E("COMPONENT_SINGLE_USE", f"components({c['component_id']})",
                          f"{c['type_id']} の利用が {users} 件です（used_by と依存部品の合計。{need} 件以上で立てる: 共通基準 BOUND-16・17）。"
                          "1ケースだけの操作列・1画面だけのUIはケースやPAGEに含めてください", "warning"))
    return errs


def validate_assessments(rd: Path) -> list[dict]:
    data, errs = _load(rd, "ai/assessments.json")
    if data is None:
        return errs
    errs = schema_errors("assessments", data)
    if errs:
        return errs
    std = read_json(rd / "standards.json")
    norm, e1 = _load(rd, "ai/normalized_cases.json")
    design, e2 = _load(rd, "ai/common_design.json")
    if e1 or e2:
        return e1 + e2
    axis_ids = [a["axis_id"] for a in std["cases"].get("axes", [])]
    status_rule = std["cases"].get("status_rule") or {}
    arch_ids = {a["arch_id"] for a in design["architectures"]}
    comps = {c["component_id"]: c for c in design["components"]}
    case_ids = {c["case_id"] for c in norm["cases"]}
    q_ids = _question_ids(rd)
    std_cells = _std_cells(rd)
    seen: dict[tuple[str, str], int] = {}
    for n, a in enumerate(data["case_assessments"]):
        p = f"case_assessments/{n}({a['case_id']})"
        if a["case_id"] not in case_ids:
            errs.append(E("UNKNOWN_CASE", p, f"ケース {a['case_id']} は存在しません"))
        for arch in a["arch_ids"]:
            if arch not in arch_ids:
                errs.append(E("UNKNOWN_ARCH", p, f"構成案 {arch} は存在しません"))
            k = (a["case_id"], arch)
            if k in seen:
                errs.append(E("DUPLICATE_ASSESSMENT", p, f"{a['case_id']}×{arch} の採点が重複しています"))
            seen[k] = n
        keys = set(a["axes"])
        if a["scope"] == "対象内" and a["feasibility"] == "feasible":
            for missing in [x for x in axis_ids if x not in keys]:
                errs.append(E("AXIS_MISSING", p, f"{missing} がありません（未判定はscore=nullで明示）"))
        for extra in sorted(keys - set(axis_ids)):
            errs.append(E("UNKNOWN_AXIS", p, f"基準に無い軸です: {extra}"))
        for ax, v in a["axes"].items():
            if v["score"] is not None and not v["evidence"].strip():
                errs.append(E("NO_EVIDENCE", f"{p}/axes/{ax}", "点数には原資料の根拠 evidence が必要です"))
            if v["score"] is not None and not v["condition"].strip():
                errs.append(E("NO_CONDITION", f"{p}/axes/{ax}", "点数には適用条件 condition が必要です"))
            for r in v.get("standard_refs", []):
                if r not in std_cells:
                    errs.append(E("BAD_STD_REF", f"{p}/axes/{ax}", f"基準Excelに存在しないセル参照です: {r}"))
        has_null = any(a["axes"].get(x, {}).get("score") is None for x in axis_ids)
        if a["scope"] == "対象内" and a["feasibility"] == "feasible" and a["info_sufficient"] and has_null:
            errs.append(E("INCONSISTENT", p, "未採点軸があるのに info_sufficient=true です"))
        if a["scope"] == "対象内" and (not a["info_sufficient"] or a["feasibility"] == "unknown") \
                and a["estimate_status"] != "要確認":
            errs.append(E("INCONSISTENT", p, "情報不足・実現性不明のケースは estimate_status=要確認 にしてください"))
        if a["feasibility"] == "impossible_confirmed" and not a.get("impossible_reason", "").strip():
            errs.append(E("NO_REASON", p, "Impossible には impossible_reason が必要です"))
        if a["scope"] != "対象内" and not a["scope_reason"].strip():
            errs.append(E("NO_REASON", p, f"{a['scope']} には scope_reason が必要です"))
        if a["estimate_status"] == "条件付き" and not a.get("conditions"):
            errs.append(E("NO_CONDITION", p, "条件付きには conditions が必要です"))
        errs += _status_rule(a, axis_ids, status_rule, p)
        errs += _ambiguity_assumption(a, status_rule, p)
        for u in a.get("uses_components", []):
            if u not in comps:
                errs.append(E("UNKNOWN_COMPONENT", p, f"uses_components {u} が存在しません"))
        for q in a.get("question_ids", []):
            if q not in q_ids:
                errs.append(E("UNKNOWN_QUESTION", p, f"question_id {q} が questions.json にありません"))
    errs += _pending_split_cases(data, norm)
    errs += _component_overlap(data, design, std)
    errs += _screen_rule(data, design, std)
    errs += _usage_consistency(data, design)
    errs += _question_links(data, design, norm, rd)
    errs += _bare_evidence_refs(data)
    errs += _grounding_checks(data, design, rd)
    errs += _invented_numbers(data, design)
    for cid in sorted(case_ids):
        for arch in sorted(arch_ids):
            if (cid, arch) not in seen:
                errs.append(E("UNASSESSED", "case_assessments", f"{cid}×{arch} の採点がありません（未算定になります）",
                              "warning"))
    allowed = {"Low", "Mid", "High", "Impossible"}
    seen_c = set()
    for n, ca in enumerate(data["common_assessments"]):
        p = f"common_assessments/{n}({ca['component_id']})"
        if ca["component_id"] in seen_c:
            errs.append(E("DUPLICATE_ASSESSMENT", p, "共通作業の判定が重複しています"))
        seen_c.add(ca["component_id"])
        if ca["component_id"] not in comps:
            errs.append(E("UNKNOWN_COMPONENT", p, f"{ca['component_id']} は common_design にありません"))
            continue
        if ca["difficulty"] is not None and ca["difficulty"] not in allowed:
            errs.append(E("BAD_DIFFICULTY", p, f"不正な難易度 {ca['difficulty']}"))
        if ca["difficulty"] is None and ca["estimate_status"] != "要確認":
            errs.append(E("INCONSISTENT", p, "難易度nullの共通作業は estimate_status=要確認 にしてください"))
        if ca["difficulty"] == "Impossible":
            if not ca.get("impossible_reason", "").strip():
                errs.append(E("NO_REASON", p, "Impossible には impossible_reason（理由・根拠・解消条件・代替案）が必要です"))
            if ca["estimate_status"] != "確定可能":
                errs.append(E("STATUS_RULE", p, "Impossible の estimate_status は 確定可能 です（共通基準 判定集計例 EX-08）"))
        if ca["estimate_status"] == "条件付き" and not ca.get("conditions"):
            errs.append(E("NO_CONDITION", p, "条件付きには conditions（仮定・影響・再見積条件）が必要です"))
        for r in ca.get("standard_refs", []):
            if r not in std_cells:
                errs.append(E("BAD_STD_REF", p, f"基準Excelに存在しないセル参照です: {r}"))
        for q in ca.get("question_ids", []):
            if q not in q_ids:
                errs.append(E("UNKNOWN_QUESTION", p, f"question_id {q} が questions.json にありません"))
    errs += _page_rule(data, comps, std)
    for cid, c in comps.items():
        if c["implementation_kind"] in ("新規", "改修") and c["cost_owner"] == cid and cid not in seen_c:
            errs.append(E("UNASSESSED", "common_assessments", f"{cid} の難易度判定がありません（未算定になります）",
                          "warning"))
    return errs


def page_expected_difficulty(profile: dict, rule: dict) -> str:
    """画面の特徴から期待難易度を求める（共通基準 BOUND-19 の仮ルール）。"""
    if profile["complex_ui"]:
        return "High"
    if profile["dynamic_list"] or profile["dialog"] or profile["file"] or profile["inputs"] >= rule["mid_inputs_min"]:
        return "Mid"
    return "Low"


def _page_rule(data: dict, comps: dict, std: dict) -> list[dict]:
    """PAGEの難易度を画面の特徴（screen_profiles）と照合する（警告）。難易度の違う画面を1部品にまとめていないかも見る。"""
    rule = std["common"].get("page_rule") or {}
    if not rule:
        return []
    errs: list[dict] = []
    for n, ca in enumerate(data["common_assessments"]):
        c = comps.get(ca["component_id"])
        if not c or c["type_id"] != rule["type_id"] or ca["difficulty"] not in ("Low", "Mid", "High"):
            continue
        p = f"common_assessments/{n}({ca['component_id']})"
        profiles = ca.get("screen_profiles")
        if not profiles:
            errs.append(E("PAGE_NO_PROFILE", p, "screen_profiles（画面ごとの入力数・一覧・ダイアログ・ファイル・複雑UI）がありません"
                                                "（共通基準 BOUND-19）", "warning"))
            continue
        got = [pr["element"] for pr in profiles]
        if sorted(got) != sorted(c["elements"]):
            errs.append(E("PAGE_PROFILE_MISMATCH", p, f"screen_profiles の画面 {sorted(got)} が elements {sorted(c['elements'])} と一致しません",
                          "warning"))
        expected = {pr["element"]: page_expected_difficulty(pr, rule) for pr in profiles}
        levels = set(expected.values())
        if len(levels) > 1:
            errs.append(E("PAGE_MIXED_DIFFICULTY", p,
                          "難易度の違う画面を1つのPAGE部品にまとめています（"
                          + "、".join(f"{k}={v}" for k, v in sorted(expected.items()))
                          + "）。難易度ごとに部品を分けてください（共通基準 BOUND-13・BOUND-19）", "warning"))
        elif ca["difficulty"] not in levels:
            errs.append(E("PAGE_DIFFICULTY_RULE", p, f"difficulty={ca['difficulty']} ですが、画面の特徴からは {levels.pop()} です"
                                                     "（共通基準 BOUND-19）", "warning"))
    return errs


def _pending_split_cases(data: dict, norm: dict) -> list[dict]:
    """原項目を分解し、一部だけが要確認になったケース（未確定部分の置き場になった疑似ケース）を警告する。
    未確定部分はケースにせず source_items の pending_parts に保留する（ケース数を水増ししない）。"""
    errs: list[dict] = []
    status: dict[str, set[str]] = {}
    for a in data["case_assessments"]:
        status.setdefault(a["case_id"], set()).add(a["estimate_status"])
    kids: dict[str, list[str]] = {}
    for c in norm["cases"]:
        if c["relation"] == "split" and len(c["source_item_ids"]) == 1:
            kids.setdefault(c["source_item_ids"][0], []).append(c["case_id"])
    for sid, cids in kids.items():
        pending = [c for c in cids if status.get(c) == {"要確認"}]
        decided = [c for c in cids if status.get(c) and "要確認" not in status[c]]
        for c in pending if decided else []:
            errs.append(E("PENDING_SPLIT_CASE", f"cases({c})",
                          f"{sid} から分解したケースのうち {c} だけが要確認です（{', '.join(decided)} は算定）。"
                          "仕様未提示の部分を切り出しただけなら、ケースにせず source_items の pending_parts に保留してください",
                          "warning"))
    return errs


def _component_overlap(data: dict, design: dict, std: dict) -> list[dict]:
    """共通部品が所有する作業（データ作成・削除、業務フローの操作列など）を、ケースの軸でも加点していないか。
    対象の軸と部品種別はアダプター（cases.component_overlap）から取る。該当する軸に overlap_note が無ければ警告する。"""
    rule = std["cases"].get("component_overlap") or {}
    pairs = rule.get("pairs") or []
    min_score = rule.get("min_score")
    if not pairs or min_score is None:
        return []
    errs: list[dict] = []
    types = {c["component_id"]: c["type_id"] for c in design["components"]}
    for n, a in enumerate(data["case_assessments"]):
        used_types: dict[str, list[str]] = {}
        for u in a.get("uses_components", []):
            if u in types:
                used_types.setdefault(types[u], []).append(u)
        for pr in pairs:
            v = a["axes"].get(pr["axis"])
            hits = [cid for t in pr["component_types"] for cid in used_types.get(t, [])]
            if v and hits and v["score"] is not None and v["score"] >= min_score and not (v.get("overlap_note") or "").strip():
                errs.append(E("AXIS_COMPONENT_OVERLAP", f"case_assessments/{n}({a['case_id']})/axes/{pr['axis']}",
                              f"{pr['axis']}={v['score']} ですが、このケースは {', '.join(hits)} を使います。"
                              "部品が所有する作業をこの軸で再び加点していないか確認し、ケース固有に残る作業を overlap_note に書いてください"
                              "（部品を呼ぶだけなら1点。個別基準 計上ルール COST-11・COST-12）", "warning"))
    return errs


def _screen_rule(data: dict, design: dict, std: dict) -> list[dict]:
    """操作手順の軸の画面の数え方（個別基準 計上ルール COST-13）。operation_screens と factors から期待点を求めて照合し、
    画面がPAGEの構成要素にあるかも確かめる（警告）。軸と画面数はアダプター（cases.screen_rule）から取る。"""
    rule = std["cases"].get("screen_rule") or {}
    if not rule:
        return []
    errs: list[dict] = []
    pages: dict[str, set[str]] = {}
    for c in design["components"]:
        if c["type_id"] == "PAGE" and c["implementation_kind"] != "対象外":
            for arch in c["arch_ids"]:
                pages.setdefault(arch, set()).update(c["elements"])
    for n, a in enumerate(data["case_assessments"]):
        v = a["axes"].get(rule["axis"])
        if not v or v["score"] not in (1, rule["factor_score"]) or v["score"] == 3:
            continue
        p = f"case_assessments/{n}({a['case_id']})/axes/{rule['axis']}"
        screens = v.get("operation_screens")
        if screens is None:
            errs.append(E("AX01_NO_SCREENS", p, "操作した画面 operation_screens がありません（個別基準 計上ルール COST-13）。"
                                                 "ケースが自分で操作する画面をPAGEの構成要素IDで列挙してください", "warning"))
            continue
        n_screens = len(set(screens))
        expected = rule["factor_score"] if n_screens >= rule["multi_screen_min"] or v.get("factors") else 1
        if v["score"] != expected:
            errs.append(E("AX01_SCREEN_RULE", p,
                          f"{rule['axis']}={v['score']} ですが、操作した画面 {n_screens} 件・要因 {v.get('factors') or 'なし'} からは "
                          f"{expected} 点です（個別基準 計上ルール COST-13）。判定だけの遷移先と共通部品に委ねた操作は数えません", "warning"))
        for arch in a["arch_ids"]:
            unknown = sorted(set(screens) - pages.get(arch, set()))
            if pages.get(arch) and unknown:
                errs.append(E("SCREEN_NOT_IN_PAGE", p, f"構成案 {arch} のPAGE構成要素に無い画面です: {', '.join(unknown)}"
                                                       "（共通基準 BOUND-15。画面の名前をPAGEの elements と揃える）", "warning"))
    return errs


def _premise_rows(rd: Path, questions: dict, norm: dict | None) -> list[dict]:
    """説明・参考領域（資料情報・前提・未確定事項など）の各行が、質問の refs か premise_reviews で扱われているか（警告）。
    前提・未確定事項の行が質問にも仮定にもならずに見落とされるのを防ぐ。"""
    if not norm:
        return []
    from .items import cell_value_text

    try:
        inv = read_json(rd / "source_inventory.json")
        raw = read_json(rd / "raw_workbook.json")
    except (OSError, ValueError):
        return []
    sheets = _sheet_index(raw)
    covered: dict[tuple[str, str], set[int]] = {}

    def cover(ref: dict) -> None:
        try:
            _, r0, _, r1 = range_boundaries(ref["range"])
        except ValueError:
            return
        covered.setdefault((ref["workbook_id"], ref["sheet"]), set()).update(range(r0, r1 + 1))

    for q in questions["items"]:
        for ref in q.get("refs", []):
            cover(ref)
    for pr in questions.get("premise_reviews", []):
        cover(pr["ref"])
    inv_by_id = {r["region_id"]: r for r in inv["regions"]}
    errs: list[dict] = []
    for r in norm.get("regions", []):
        reg = inv_by_id.get(r["region_id"])
        if r["role"] not in PREMISE_ROLES or reg is None:
            continue
        sh = sheets.get((reg["workbook_id"], reg["sheet"]))
        if sh is None:
            continue
        min_col, min_row, max_col, max_row = range_boundaries(reg["range"])
        cols = [get_column_letter(c) for c in range(min_col, max_col + 1)]
        missing = []
        for row in range(min_row, max_row + 1):
            if row in set(r.get("header_rows", [])) or row in covered.get((reg["workbook_id"], reg["sheet"]), set()):
                continue
            text = " ".join(t for c in cols if (t := cell_value_text(sh, row, c).strip()))
            if text:
                missing.append(f"{row}行「{text[:30]}」")
        if missing:
            errs.append(E("PREMISE_ROW_UNTRACED", f"regions({r['region_id']})",
                          f"{reg['sheet']} の {len(missing)} 行が質問の refs にも premise_reviews にもありません: "
                          f"{'、'.join(missing[:8])}。前提・未確定事項なら質問/仮定として起票して refs に行を入れ、"
                          "影響がない・反映済みなら premise_reviews に理由を書いてください（見出し行は regions の header_rows へ）", "warning"))
    return errs


# 前提・未確定事項が書かれやすい領域の役割（normalized_cases の regions[].role）
PREMISE_ROLES = ("description", "reference")


def _usage_consistency(data: dict, design: dict) -> list[dict]:
    """common_design の used_by と assessments の uses_components が食い違わないこと（対象外の部品は除く）。"""
    errs: list[dict] = []
    expected: dict[tuple[str, str], set[str]] = {}
    for c in design["components"]:
        if c["implementation_kind"] == "対象外":
            continue
        for arch in c["arch_ids"]:
            for u in c["used_by"]:
                expected.setdefault((u, arch), set()).add(c["component_id"])
    for n, a in enumerate(data["case_assessments"]):
        for arch in a["arch_ids"]:
            want = expected.get((a["case_id"], arch), set())
            got = set(a.get("uses_components", []))
            if want != got:
                errs.append(E("USAGE_MISMATCH", f"case_assessments/{n}({a['case_id']})",
                              f"構成案 {arch}: common_design の used_by と uses_components が一致しません"
                              f"（used_byのみ: {sorted(want - got)}、uses_componentsのみ: {sorted(got - want)}）。"
                              "どちらかを直して揃えてください"))
    return errs


def _question_links(data: dict, design: dict, norm: dict, rd: Path) -> list[dict]:
    """未解決の質問・仮定のtargetsと、各ケース/共通作業の question_ids が双方向でそろっていること（警告）。"""
    qs, _ = _load(rd, "ai/questions.json")
    if not qs:
        return []
    errs: list[dict] = []
    open_q = {q["question_id"]: q for q in qs["items"] if q["status"] != "resolved"}
    linked: dict[str, set[str]] = {}
    for a in data["case_assessments"]:
        linked.setdefault(a["case_id"], set()).update(a.get("question_ids", []))
    for ca in data["common_assessments"]:
        linked.setdefault(ca["component_id"], set()).update(ca.get("question_ids", []))
    for qid, q in open_q.items():
        for t in q["targets"]:
            if t in linked and qid not in linked[t]:
                errs.append(E("QUESTION_NOT_LINKED", f"{t}",
                              f"{qid} は targets に {t} を含みますが、{t} の question_ids にありません", "warning"))
    for tid, qids in linked.items():
        for qid in qids:
            q = open_q.get(qid)
            if q and tid not in q["targets"]:
                errs.append(E("QUESTION_TARGET_MISSING", f"{tid}",
                              f"{tid} は {qid} を参照していますが、{qid} の targets に {tid} がありません", "warning"))
    return errs


_ID_TOKEN = re.compile(r"(?<![A-Za-z0-9-])[A-Z]{2,6}-\d{1,4}(?![A-Za-z0-9])")
_SPECULATION = re.compile(r"想定|推測|と思われ|だろう|と考えられ")
# 工数・割合を表す数値。基準Excelの値の転記・独自の相場・割引率をAIが書くのを検出する
_EFFORT_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:人時|人日|人月|時間|分|hrs?|h(?![A-Za-z])|[%％]|割|倍)")
_SUM_NUMBER = re.compile(r"(?:合計|総計|計)\s*\d+(?:\.\d+)?\s*点")


def _grounding_checks(data: dict, design: dict, rd: Path) -> list[dict]:
    """基準・仮定への接地を確認する（警告）。点数の根拠セル、依存先の質問の引継ぎ、根拠中の部品参照、
    要確認ケースでの推測、POM未指定時のPAGEの状態。"""
    errs: list[dict] = []
    comps = {c["component_id"]: c for c in design["components"]}
    arch_ids = {a["arch_id"] for a in design["architectures"]}
    qs, _ = _load(rd, "ai/questions.json")
    qmap = {q["question_id"]: q for q in (qs or {"items": []})["items"]}
    comp_q = {ca["component_id"]: set(ca.get("question_ids", [])) for ca in data["common_assessments"]}
    # 全ケースが使う部品（BASE・RUN等）の仮定は案件全体の前提で、ケースごとの引継ぎ対象にしない
    all_cases = {a["case_id"] for a in data["case_assessments"]}
    global_comps = {cid for cid, c in comps.items() if all_cases and all_cases <= set(c["used_by"])}
    for n, a in enumerate(data["case_assessments"]):
        p = f"case_assessments/{n}({a['case_id']})"
        uses = set(a.get("uses_components", []))
        undetermined = a["estimate_status"] == "要確認" or not a["info_sufficient"]
        for ax, v in a["axes"].items():
            if v["score"] is not None and not v.get("standard_refs"):
                errs.append(E("NO_STANDARD_REF", f"{p}/axes/{ax}",
                              "点数には基準Excelのセル参照 standard_refs（cases:判定基準!…）が必要です。基準にない条件を独自に作らないでください",
                              "warning"))
            if undetermined and v["score"] is not None and _SPECULATION.search(v["evidence"]):
                errs.append(E("SPECULATIVE_EVIDENCE", f"{p}/axes/{ax}",
                              "要確認のケースの根拠に推測表現があります。原資料にない操作を補わず、決められない軸は null にしてください",
                              "warning"))
            for tok in sorted(set(_ID_TOKEN.findall(v["evidence"] + " " + v["condition"]))):
                c = comps.get(tok)
                if c and tok not in uses and c.get("integrated_into") not in uses:
                    errs.append(E("EVIDENCE_COMPONENT_NOT_USED", f"{p}/axes/{ax}",
                                  f"根拠が {tok} に言及していますが uses_components にありません。依存の持ち方（直接か他部品経由か）を揃えてください",
                                  "warning"))
        if a["estimate_status"] == "確定可能":
            for u in sorted(uses - global_comps):
                for qid in sorted(comp_q.get(u, set()) - set(a.get("question_ids", []))):
                    q = qmap.get(qid)
                    if q and q["status"] != "resolved" and not (set(q["targets"]) & arch_ids):
                        errs.append(E("QUESTION_NOT_INHERITED", p,
                                      f"{u} は未解決の {qid} に依存しますが、このケースは確定可能で question_ids に {qid} がありません。"
                                      "前提の仮定が崩れたときの影響を conditions と question_ids に残してください", "warning"))
    try:
        pom = read_json(rd / "manifest.json").get("config_resolved", {}).get("architecture", {}).get("pom")
    except (OSError, ValueError):
        pom = None
    if pom == "unspecified":
        for ca in data["common_assessments"]:
            c = comps.get(ca["component_id"])
            if c and c["type_id"] == "PAGE" and c["implementation_kind"] in ("新規", "改修") \
                    and ca["estimate_status"] == "確定可能":
                errs.append(E("POM_ASSUMPTION_NOT_CONDITIONAL", f"common_assessments/{ca['component_id']}",
                              "案件設定のPOMが未指定でPOM採用案を作っています。PAGE作業は条件付きにして仮定を記録してください"
                              "（共通基準 AI出力仕様 COMMON-OUT-01）", "warning"))
    return errs


def _invented_numbers(data: dict, design: dict) -> list[dict]:
    """AIが書いた判断文に工数・割合・合計点などの数値があれば検出する。
    工数・難易度・合計は基準Excelに基づきCLIが算出する。AIが数字を書き写したり創作したりしない。"""
    errs: list[dict] = []

    def scan(path: str, text: str, severity: str) -> None:
        for m in list(_EFFORT_NUMBER.finditer(text)) + list(_SUM_NUMBER.finditer(text)):
            errs.append(E("UNSOURCED_NUMBER", path,
                          f"『{m.group(0)}』は工数・割合・合計を表す数値です。基準Excelの値の転記や独自の数値をAIが書かず、"
                          "算出は calculate に任せてください（原資料の引用なら evidence に原文位置を添えてください）", severity))

    for n, a in enumerate(data["case_assessments"]):
        p = f"case_assessments/{n}({a['case_id']})"
        scan(f"{p}/rationale", a["rationale"], "error")
        for i, c in enumerate(a.get("conditions", [])):
            scan(f"{p}/conditions/{i}", c, "error")
        for ax, v in a["axes"].items():
            scan(f"{p}/axes/{ax}/evidence", v["evidence"], "warning")
            scan(f"{p}/axes/{ax}/condition", v["condition"], "error")
    for n, ca in enumerate(data["common_assessments"]):
        p = f"common_assessments/{n}({ca['component_id']})"
        scan(f"{p}/rationale", ca["rationale"], "error")
        scan(f"{p}/matched_conditions", ca["matched_conditions"], "error")
        for i, c in enumerate(ca.get("conditions", [])):
            scan(f"{p}/conditions/{i}", c, "error")
    for c in design["components"]:
        for k in ("responsibility", "need_reason", "unit_note"):
            scan(f"common_design/{c['component_id']}/{k}", c.get(k) or "", "error")
    return errs


_BARE_REF = re.compile(r"[（(][A-Z]{1,3}[0-9]+(?::[A-Z]{1,3}[0-9]+)?[）)]")


def _bare_evidence_refs(data: dict) -> list[dict]:
    """evidence のセル座標はシート名つき（例: 確認リスト!C3）にする。シート名なしの座標は警告。"""
    errs: list[dict] = []
    for n, a in enumerate(data["case_assessments"]):
        for ax, v in a["axes"].items():
            if _BARE_REF.search(v["evidence"]):
                errs.append(E("EVIDENCE_REF_NO_SHEET", f"case_assessments/{n}({a['case_id']})/axes/{ax}",
                              "evidence のセル座標にシート名がありません。『シート名!セル』形式で書き、views/*.md で座標を確認してください",
                              "warning"))
    return errs


def _ambiguity_assumption(a: dict, rule: dict, p: str) -> list[dict]:
    """あいまい度の軸が最低点（仮定なし）なのに、その軸に仮定が付いている不整合を警告する。"""
    ax_id = (rule or {}).get("ambiguity_axis")
    v = a["axes"].get(ax_id) if ax_id else None
    if v and v.get("score") is not None and v["score"] < rule["conditional_min_score"] and v.get("assumptions"):
        return [E("AXIS_ASSUMPTION_SCORE", f"{p}/axes/{ax_id}",
                  f"{ax_id} は仮定なしの点数なのに assumptions があります。案件範囲の仮定（重複統合など）は conditions と質問に書き、"
                  "この軸の仮定はあいまいさを理由に点数を上げるときだけ使ってください", "warning")]
    return []


def _status_rule(a: dict, axis_ids: list[str], rule: dict, p: str) -> list[dict]:
    """個別基準の見積もり状態の規則（v0.1 RULE-03・RULE-07）。軸IDと閾値はアダプター設定から取る。"""
    if a["scope"] != "対象内":
        return []
    if a["feasibility"] == "impossible_confirmed":
        if a["estimate_status"] != "確定可能":
            return [E("STATUS_RULE", p, "Impossible の estimate_status は 確定可能 です（個別基準 RULE-03）")]
        return []
    scores = [a["axes"].get(x, {}).get("score") for x in axis_ids]
    if not a["info_sufficient"] or a["feasibility"] != "feasible" or any(s is None for s in scores) or not rule:
        return []
    amb = a["axes"].get(rule["ambiguity_axis"], {}).get("score")
    has_assumption = bool(a.get("conditions")) or any(v.get("assumptions") for v in a["axes"].values())
    expected = "条件付き" if (amb is not None and amb >= rule["conditional_min_score"]) or has_assumption else "確定可能"
    if a["estimate_status"] != expected:
        why = (f"{rule['ambiguity_axis']}={amb}" if amb is not None and amb >= rule["conditional_min_score"]
               else ("仮定あり" if has_assumption else f"{rule['ambiguity_axis']}={amb}・仮定なし"))
        return [E("STATUS_RULE", p, f"estimate_status は {expected} です（{why}。個別基準 {rule.get('rule_ref', 'RULE-07')}）")]
    return []


def validate_questions(rd: Path) -> list[dict]:
    data, errs = _load(rd, "ai/questions.json")
    if data is None:
        return [E("MISSING_FILE", "ai/questions.json", "questions.json がありません（0件でも items: [] で作成）")]
    errs = schema_errors("questions", data)
    if errs:
        return errs
    for d in _dupes([q["question_id"] for q in data["items"]]):
        errs.append(E("DUPLICATE_ID", "items", f"question_id {d} が重複しています"))
    q_ids = {q["question_id"] for q in data["items"]}
    norm, _ = _load(rd, "ai/normalized_cases.json")
    for it in (norm or {}).get("source_items", []):
        for k, part in enumerate(it.get("pending_parts", [])):
            for q in part.get("question_ids", []):
                if q not in q_ids:
                    errs.append(E("UNKNOWN_QUESTION", f"source_items({it['item_id']})/pending_parts/{k}",
                                  f"question_id {q} が questions.json にありません"))
    errs += _premise_rows(rd, data, norm)
    return errs


def _question_ids(rd: Path) -> set[str]:
    p = rd / "ai/questions.json"
    if not p.exists():
        return set()
    try:
        return {q["question_id"] for q in read_json(p).get("items", [])}
    except (ValueError, KeyError, TypeError):
        return set()


def _std_cells(rd: Path) -> set[str]:
    """基準Excelの参照として有効な 'cases:Sheet!A1' 形式（範囲は始点セルの存在で判定）の集合を返す。"""
    p = rd / "standards_cells.json"
    if not p.exists():
        return set()
    cells = read_json(p)
    out = set(cells)
    return _RangeSet(out)


class _RangeSet(set):
    def __contains__(self, item):  # type: ignore[override]
        if super().__contains__(item):
            return True
        if ":" in item.split("!", 1)[-1]:
            head, rng = item.rsplit("!", 1)
            a, b = rng.split(":", 1)
            return super().__contains__(f"{head}!{a}") or super().__contains__(f"{head}!{b}")
        return False


def review_target_ids(rd: Path) -> set[str]:
    """意味レビューが指摘対象にできる実在IDの集合。"""
    ids: set[str] = {"overall"}
    for rel, key, fields in (
        ("ai/normalized_cases.json", None, (("regions", "region_id"), ("source_items", "item_id"), ("cases", "case_id"))),
        ("ai/common_design.json", None, (("architectures", "arch_id"), ("components", "component_id"))),
        ("ai/questions.json", None, (("items", "question_id"),)),
    ):
        p = rd / rel
        if not p.exists():
            continue
        try:
            doc = read_json(p)
        except ValueError:
            continue
        for arr, f in fields:
            ids |= {x[f] for x in doc.get(arr, []) if isinstance(x, dict) and f in x}
    return ids


def validate_semantic_review(rd: Path) -> list[dict]:
    """意味レビューの指摘の検証。形式とkind、target・relatedが実在IDであること。内容の当否は判断しない。"""
    data, errs = _load(rd, "ai/semantic_review.json")
    if data is None:
        return errs
    errs = schema_errors("semantic_review", data)
    if errs:
        return errs
    known = review_target_ids(rd)
    q_ids = _question_ids(rd)
    for n, f in enumerate(data["findings"]):
        for field, ids in (("target", [f["target"]]), ("related", f.get("related", []))):
            for i in ids:
                if i not in known:
                    errs.append(E("UNKNOWN_TARGET", f"findings/{n}/{field}",
                                  f"{i} は成果物に存在するID（case_id/component_id/item_id/region_id/question_id/arch_id）でも overall でもありません"))
        res = f.get("resolution")
        if res is None:
            errs.append(E("FINDING_UNRESOLVED", f"findings/{n}({f['target']})",
                          "指摘への対応 resolution がありません（fixed/question/rejected/deferred と note）。"
                          "mark-review --by ai の前に全指摘へ対応を記録してください", "warning"))
            continue
        if res["status"] == "question":
            if not res.get("question_ids"):
                errs.append(E("NO_QUESTION", f"findings/{n}/resolution", "status=question には起票した question_ids が必要です"))
            for q in res.get("question_ids", []):
                if q not in q_ids:
                    errs.append(E("UNKNOWN_QUESTION", f"findings/{n}/resolution",
                                  f"question_id {q} が questions.json にありません"))
    return errs


def review_resolution_counts(rd: Path) -> dict[str, int] | None:
    """意味レビュー指摘の対応状況の件数。対応未記録は unresolved。指摘ファイルが無ければNone。"""
    p = rd / "ai/semantic_review.json"
    if not p.exists():
        return None
    try:
        findings = read_json(p).get("findings", [])
    except ValueError:
        return None
    out = {"total": len(findings), "fixed": 0, "question": 0, "rejected": 0, "deferred": 0, "unresolved": 0}
    for f in findings:
        st = (f.get("resolution") or {}).get("status")
        out[st if st in out else "unresolved"] += 1
    return out


STAGE_VALIDATORS = {
    "normalize": validate_normalize,
    "common_design": validate_common_design,
    "assessments": validate_assessments,
    "questions": validate_questions,
}


_STD_CODE = re.compile(r"^読取警告 ([A-Z_]+) ")


def warning_kind(w: dict) -> str:
    """警告の集約キー。基準読取りの文字列警告は、コードまたは文言の型で分類する（無害かどうかは判断しない）。"""
    m = _STD_CODE.match(w["message"])
    if m:
        return m.group(1)
    if w["code"] == "STANDARDS" and "対象外の行として扱います" in w["message"]:
        return "STD_NON_EFFORT_ROW"
    return w["code"]


def summarize_warnings(machine: dict) -> list[dict]:
    """警告を工程・種類ごとに件数集約する。表示用で、validation.json の警告本体は変えない。"""
    groups: dict[tuple[str, str], dict] = {}
    for stage, v in machine["stages"].items():
        for w in v["warnings"]:
            g = groups.setdefault((stage, warning_kind(w)), {"stage": stage, "kind": warning_kind(w), "count": 0,
                                                              "sample": w["message"], "paths": []})
            g["count"] += 1
            if len(g["paths"]) < 5:
                g["paths"].append(w["path"])
    return sorted(groups.values(), key=lambda g: (-g["count"], g["stage"], g["kind"]))


def validate_all(rd: Path, config: dict) -> dict:
    """全工程の機械検証と計算の再現性検証。estimate.jsonはその場で再計算した結果と照合する。"""
    from .run import verify_sources_unchanged

    result: dict = {"stages": {}, "checks": []}
    for stage, fn in STAGE_VALIDATORS.items():
        errs = fn(rd)
        result["stages"][stage] = {
            "errors": [e for e in errs if e.get("severity", "error") == "error"],
            "warnings": [e for e in errs if e.get("severity") == "warning"],
        }
    std = read_json(rd / "standards.json")
    std_errs = [E("STANDARDS", "standards.json", m) for m in std.get("errors", [])]
    result["stages"]["standards"] = {"errors": std_errs,
                                     "warnings": [E("STANDARDS", "standards.json", m, "warning")
                                                  for m in std.get("warnings", [])]}
    src = verify_sources_unchanged(rd)
    result["stages"]["sources"] = {"errors": src, "warnings": []}

    est, e = _load(rd, "estimate.json")
    calc_errs = list(e)
    if est is not None and not any(result["stages"][s]["errors"] for s in ("normalize", "common_design", "assessments")):
        try:
            recomputed = calculate(std, load_normalized(rd),
                                   read_json(rd / "ai/common_design.json"), read_json(rd / "ai/assessments.json"),
                                   config)
            verdict = compare_estimate(est, recomputed)
            if verdict == "rule_version_changed":
                calc_errs.append(E("RULE_VERSION_CHANGED", "estimate.json",
                                   f"計算規則の版が変わっています（estimate: {est.get('rule_versions')}、現行: "
                                   f"{recomputed['rule_versions']}）。calculate を再実行してください"))
            elif verdict == "mismatch":
                calc_errs.append(E("RECOMPUTE_MISMATCH", "estimate.json",
                                   "estimate.json が現在の採点・基準からの再計算結果と一致しません（手編集または上流変更）"))
        except (KeyError, TypeError, ValueError) as ex:
            calc_errs.append(E("RECOMPUTE_FAILED", "estimate.json", f"再計算できません: {ex}"))
    elif est is not None:
        calc_errs.append(E("RECOMPUTE_SKIPPED", "estimate.json", "上流の検証エラーのため再計算照合を省略", "warning"))
    result["stages"]["calculate"] = {"errors": [x for x in calc_errs if x["severity"] == "error"],
                                     "warnings": [x for x in calc_errs if x["severity"] == "warning"]}
    total_err = sum(len(v["errors"]) for v in result["stages"].values())
    result["error_count"] = total_err
    result["warning_count"] = sum(len(v["warnings"]) for v in result["stages"].values())
    result["machine_validation"] = "passed" if total_err == 0 else "failed"
    return result
