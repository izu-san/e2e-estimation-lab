"""CLI入口。各工程を独立して呼べる。意味判断（ai/*.json の作成）はClaude Codeセッションが行う。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import extract as extract_mod
from .calculate import calculate, calc_common_example
from .io_utils import now_iso, read_json, sha256_file, write_json, write_text
from .items import load_normalized
from .run import (AI_FILES, ROOT, RunError, environment_info, harness_fingerprint, load_config, load_state,
                  log_command, mark_stage, new_run_id, refresh_state, run_dir, runs_root, verify_sources_unchanged,
                  _file_record, _resolve)
from .schemas import schema_errors
from .standards import digest_exclude_patterns, load_adapter, load_standards, standards_text, strip_private
from .validate import (STAGE_VALIDATORS, review_resolution_counts, summarize_warnings, validate_all,
                       validate_semantic_review)


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# ------------------------------------------------------------------ init-run

def cmd_init_run(a) -> int:
    cfg = load_config(a.config)
    if a.project:
        man = yaml.safe_load(Path(_resolve(a.project)).read_text(encoding="utf-8"))
        errs = schema_errors("project_manifest", man)
        if errs:
            raise RunError("案件マニフェストの形式エラー: " + json.dumps(errs, ensure_ascii=False))
        inputs = [(_resolve(i["path"]), i.get("role")) for i in man["inputs"]]
        stem = man["project_name"]
    else:
        inputs = [(_resolve(a.input), None)]
        stem = Path(a.input).stem
    missing = [str(p) for p, _ in inputs if not p.exists()]
    run_id = a.run_id or new_run_id(stem)
    rd = runs_root() / run_id
    if rd.exists():
        raise RunError(f"run {run_id} は既に存在します")
    (rd / "ai").mkdir(parents=True)
    (rd / "logs").mkdir()

    adapter_path = _resolve(cfg["standards"]["adapter"])
    cases_p, common_p = _resolve(cfg["standards"]["cases"]), _resolve(cfg["standards"]["common"])
    adapter = load_adapter(adapter_path)
    std = load_standards(cases_p, common_p, adapter)
    cells = []
    for key in ("cases", "common"):
        wb = std[key].get("_workbook")
        if wb:
            write_text(rd / "standards_text" / f"{key}.md", standards_text(std[key]))
            write_text(rd / "standards_text" / f"{key}.digest.md",
                       standards_text(std[key], digest_exclude_patterns(adapter[key])))
            cells += [f"{key}:{sh['name']}!{c['ref']}" for sh in wb["sheets"] for c in sh["cells"]]
    write_json(rd / "standards_cells.json", sorted(cells))
    write_json(rd / "standards.json", strip_private(std))

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": now_iso(),
        "mode": "project_manifest" if a.project else "single_input",
        "project_manifest": _file_record(_resolve(a.project)) if a.project else None,
        "inputs": [{**_file_record(p), "workbook_id": f"W{i}", "role": role} for i, (p, role) in enumerate(inputs, 1)],
        "missing_inputs": missing,
        "standards": {
            "cases": {**_file_record(cases_p), "version": (std["cases"].get("version") or {}).get("value")},
            "common": {**_file_record(common_p), "version": (std["common"].get("version") or {}).get("value")},
            "adapter": _file_record(adapter_path),
        },
        "config": _file_record(Path(cfg["_config_path"])),
        "config_resolved": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "harness": harness_fingerprint(),
        "environment": environment_info(),
    }
    write_json(rd / "manifest.json", manifest)
    status = "done" if not missing and not std["errors"] else "done_with_errors"
    mark_stage(rd, "init", status, error_count=len(std["errors"]) + len(missing))
    log_command(rd, "init-run", status)
    _out({"run_id": run_id, "run_dir": str(rd), "missing_inputs": missing,
          "standards_errors": std["errors"], "standards_warnings": std["warnings"]})
    return 0 if status == "done" else 2


def cmd_extract(a) -> int:
    rd = run_dir(a.run)
    src = verify_sources_unchanged(rd)
    if src:
        _out({"errors": src})
        return 2
    cfg = read_json(rd / "manifest.json")["config_resolved"]
    res = extract_mod.extract(rd, chunk_rows=cfg["execution"].get("chunk_rows", 80))
    mark_stage(rd, "extract", "done" if not res["constraints"] else "done_with_constraints",
               error_count=len(res["constraints"]))
    log_command(rd, "extract", "ok", res)
    _out(res)
    return 0


def cmd_survey(a) -> int:
    from .survey import SurveyError, run_survey

    rd = run_dir(a.run)
    site = read_json(rd / "manifest.json")["config_resolved"].get("site") or {}
    try:
        doc = run_survey(rd, site)
    except SurveyError as e:
        log_command(rd, "survey", "failed", {"message": str(e)})
        _out({"status": "failed", "message": str(e)})
        return 2
    res = {"status": "done", "pages": len(doc["pages"]), "skipped": len(doc["skipped"]), "errors": doc["errors"],
           "file": str(rd / "survey" / "pages.json"),
           "templates": [f"{p['template']}  {p['title']}" for p in doc["pages"]]}
    log_command(rd, "survey", "ok", {k: res[k] for k in ("pages", "skipped")})
    _out(res)
    return 0


def cmd_render(a) -> int:
    rd = run_dir(a.run)
    raw = read_json(rd / "raw_workbook.json")
    from .workbook_reader import render_sheet

    lo, hi = (None, None)
    if a.rows:
        lo, hi = (int(x) for x in a.rows.split("-"))
    for wb in raw["workbooks"]:
        if a.workbook and wb["workbook_id"] != a.workbook:
            continue
        for sh in wb["sheets"]:
            if a.sheet and a.sheet not in (sh["name"], str(sh["index"])):
                continue
            print(f"# {wb['workbook_id']} {wb['file_name']}")
            print(render_sheet(sh, lo, hi, a.max_len))
            print()
    return 0


def cmd_profile(a) -> int:
    """列ごとの値の分布を表示する。大規模資料で、全行を読まずに繰返し構造（観点×データ等）を把握するため。"""
    from collections import Counter

    from openpyxl.utils import get_column_letter

    from .items import cell_value_text

    rd = run_dir(a.run)
    raw = read_json(rd / "raw_workbook.json")
    sh = next((s for wb in raw["workbooks"] if not a.workbook or wb["workbook_id"] == a.workbook
               for s in wb["sheets"] if a.sheet in (s["name"], str(s["index"]))), None)
    if sh is None:
        raise RunError(f"シートが見つかりません: {a.sheet}")
    lo, hi = (int(x) for x in a.rows.split("-")) if a.rows else (1, sh["max_row"])
    cols = a.columns.split(",") if a.columns else [get_column_letter(i) for i in range(1, sh["max_col"] + 1)]
    out = {"sheet": sh["name"], "rows": [lo, hi], "columns": {}}
    for col in cols:
        vals = [cell_value_text(sh, r, col) for r in range(lo, hi + 1)]
        nonempty = [v for v in vals if v.strip()]
        cnt = Counter(v[: a.max_len] for v in nonempty)
        out["columns"][col] = {
            "header": cell_value_text(sh, a.header_row, col) if a.header_row else None,
            "nonempty": len(nonempty), "distinct": len(cnt),
            "top": [[v, n] for v, n in cnt.most_common(a.top)],
        }
    if a.group_by:
        gcols = a.group_by.split(",")
        combos = Counter(tuple(cell_value_text(sh, r, c)[: a.max_len] for c in gcols) for r in range(lo, hi + 1)
                         if any(cell_value_text(sh, r, c).strip() for c in gcols))
        out["group_by"] = {"columns": gcols, "distinct": len(combos),
                           "top": [[list(k), n] for k, n in combos.most_common(a.top)]}
    _out(out)
    return 0


def cmd_status(a) -> int:
    rd = run_dir(a.run)
    state = refresh_state(rd)
    files = {rel: (rd / rel).exists() for rel in AI_FILES.values()}
    _out({"run_dir": str(rd), "stages": {k: {kk: vv for kk, vv in v.items() if kk not in ("inputs", "outputs")}
                                         for k, v in state["stages"].items()},
          "ai_files": files, "source_changes": verify_sources_unchanged(rd)})
    return 0


def _max_repairs(rd: Path) -> int:
    return read_json(rd / "manifest.json")["config_resolved"]["execution"].get("max_repair_attempts", 2)


def cmd_validate_stage(a) -> int:
    rd = run_dir(a.run)
    stage = a.stage
    errs = (validate_semantic_review if stage == "semantic_review" else STAGE_VALIDATORS[stage])(rd)
    hard = [e for e in errs if e.get("severity", "error") == "error"]
    state = load_state(rd)
    st = state["stages"].get(stage, {})
    failures = st.get("failures", 0) + (1 if hard else 0)
    limit = 1 + _max_repairs(rd)  # 初回提出 + 修正上限
    if not hard:
        status = "validated"
    elif failures >= limit:
        status = "failed_repair_limit"
    else:
        status = "failed"
    if stage in STAGE_VALIDATORS and stage != "questions":  # questions・semantic_review は工程状態に載せない
        mark_stage(rd, stage, status, failures=failures, error_count=len(hard))
    log_command(rd, f"validate-stage {stage}", status, {"errors": len(hard)})
    msg = None
    if status == "failed":
        msg = f"エラーを修正して再提出してください（残り修正回数 {limit - failures}）。検証器・基準は変更しないこと。"
    elif status == "failed_repair_limit":
        msg = "修正上限に達しました。これ以上修正せず、未算定・失敗として状態を残してください。"
    _out({"stage": stage, "status": status, "errors": hard, "warnings": [e for e in errs if e not in hard],
          "message": msg})
    return 0 if not hard else 1


def cmd_calculate(a) -> int:
    rd = run_dir(a.run)
    state = refresh_state(rd)
    blockers = []
    for stage in ("normalize", "screens", "common_design", "assessments"):
        errs = STAGE_VALIDATORS[stage](rd)
        hard = [e for e in errs if e.get("severity", "error") == "error"]
        schema = [e for e in hard if e["code"] in ("SCHEMA", "MISSING_FILE", "INVALID_JSON")]
        if schema or (hard and state["stages"].get(stage, {}).get("status") != "failed_repair_limit"):
            blockers.append({"stage": stage, "errors": hard[:30], "count": len(hard)})
    std = read_json(rd / "standards.json")
    if std["errors"]:
        blockers.append({"stage": "standards", "errors": std["errors"]})
    if blockers:
        mark_stage(rd, "calculate", "blocked")
        _out({"status": "blocked", "blockers": blockers,
              "message": "先に validate-stage でエラーを解消してください（上限到達済みの工程は除く）"})
        return 1
    cfg = read_json(rd / "manifest.json")["config_resolved"]
    est = calculate(std, load_normalized(rd), read_json(rd / "ai/common_design.json"),
                    read_json(rd / "ai/assessments.json"), cfg)
    write_json(rd / "estimate.json", est)
    mark_stage(rd, "calculate", "done")
    log_command(rd, "calculate", "ok")
    _out({"status": "done", "architectures": [{"arch_id": x["arch_id"], "subtotals": x["subtotals"],
                                               "counts": x["counts"],
                                               "estimate_completeness": x["estimate_completeness"]}
                                              for x in est["architectures"]]})
    return 0


def _semantic_status(rd: Path) -> str:
    """意味レビューの状態。AIレビューは記録（mark-review）があるときだけ「済」とし、
    自己レビュー・未対応の指摘・レビュー後の見積もり変更を併記する（「済」が指摘なしと誤読されないように）。"""
    human = rd / "review" / "human_review.json"
    if human.exists():
        return "人確認済"
    rec_p = rd / "review" / "ai_review.json"
    counts = review_resolution_counts(rd)
    if counts is None or not rec_p.exists():
        return "未実施"
    rec = read_json(rec_p)
    notes = []
    if rec.get("context") == "self":
        notes.append("自己レビュー")
    open_n = counts["deferred"] + counts["unresolved"]
    if open_n:
        notes.append(f"未対応{open_n}件")
    est = rd / "estimate.json"
    if rec.get("estimate_sha256") and est.exists() and sha256_file(est) != rec["estimate_sha256"]:
        notes.append("レビュー記録後に見積もり変更")
    return "AIレビュー済" + (f"（{'・'.join(notes)}）" if notes else "")


def cmd_validate(a) -> int:
    rd = run_dir(a.run)
    cfg = read_json(rd / "manifest.json")["config_resolved"]
    machine = validate_all(rd, cfg)
    est = read_json(rd / "estimate.json") if (rd / "estimate.json").exists() else None
    state = load_state(rd)
    repair = {s: {"failures": state["stages"].get(s, {}).get("failures", 0),
                  "status": state["stages"].get(s, {}).get("status")}
              for s in ("normalize", "screens", "common_design", "assessments")}
    exec_ok = est is not None and not machine["stages"]["sources"]["errors"] and \
        not machine["stages"]["standards"]["errors"] and \
        not any(e["code"] in ("RECOMPUTE_MISMATCH", "RECOMPUTE_FAILED", "RULE_VERSION_CHANGED") for e in machine["stages"]["calculate"]["errors"])
    validation = {
        "schema_version": 1,
        "validated_at": now_iso(),
        "status": {
            "execution_status": "処理成功" if exec_ok else "処理失敗",
            "machine_validation": machine["machine_validation"],
            "estimate_completeness": {x["arch_id"]: x["estimate_completeness"] for x in (est or {}).get("architectures", [])},
            "semantic_review_status": _semantic_status(rd),
        },
        "repair": repair,
        "machine": machine,
        "estimate_sha256": sha256_file(rd / "estimate.json") if est is not None else None,
    }
    write_json(rd / "validation.json", validation)
    mark_stage(rd, "validate", "passed" if machine["machine_validation"] == "passed" else "failed",
               error_count=machine["error_count"])
    log_command(rd, "validate", validation["status"])
    _out({"status": validation["status"], "error_count": machine["error_count"],
          "warning_count": machine["warning_count"],
          "warning_summary": summarize_warnings(machine),
          "errors": [e for v in machine["stages"].values() for e in v["errors"]][:50]})
    return 0 if machine["machine_validation"] == "passed" else 1


def cmd_export(a) -> int:
    rd = run_dir(a.run)
    val = read_json(rd / "validation.json")
    if val.get("estimate_sha256") != sha256_file(rd / "estimate.json"):
        _out({"status": "blocked", "message": "estimate.json が検証後に変更されています。validate を再実行してください"})
        return 1
    res = export_mod.export(rd)
    mark_stage(rd, "export", "done")
    log_command(rd, "export", "ok", res)
    _out({"status": "done", **res, "validation": val["status"]})
    return 0


def _refresh_review_outputs(rd: Path) -> None:
    """レビュー記録後、既に出力済みの validation.json / summary.md / estimate.xlsx に状態を反映する。"""
    vp = rd / "validation.json"
    if not vp.exists():
        return
    val = read_json(vp)
    val.setdefault("status", {})["semantic_review_status"] = _semantic_status(rd)
    write_json(vp, val)
    if (rd / "summary.md").exists():
        export_mod.export(rd)


def cmd_mark_review(a) -> int:
    rd = run_dir(a.run)
    rec = {"reviewed_at": now_iso(), "by": a.by, "reviewer": a.reviewer, "note": a.note,
           "estimate_sha256": sha256_file(rd / "estimate.json") if (rd / "estimate.json").exists() else None}
    if a.by == "human":
        write_json(rd / "review" / "human_review.json", rec)
    else:
        p = rd / "ai" / "semantic_review.json"
        if not p.exists():
            raise RunError("ai/semantic_review.json（指摘一覧）を先に作成してください")
        errs = validate_semantic_review(rd)
        bad = [e for e in errs if e.get("severity", "error") == "error"]
        if bad:
            raise RunError("ai/semantic_review.json の検証エラー: " + "; ".join(f"{e['path']} {e['message']}" for e in bad[:5])
                           + "（validate-stage --stage semantic_review で詳細確認）")
        unresolved = [e["path"] for e in errs if e["code"] == "FINDING_UNRESOLVED"]
        if unresolved:
            raise RunError(f"対応が未記録の指摘が {len(unresolved)} 件あります（{', '.join(unresolved[:5])}）。"
                           "各指摘に resolution（fixed/question/rejected/deferred と note）を書いてから記録してください。"
                           "直したら calculate → validate → export をやり直してから記録します")
        if not a.context:
            raise RunError("--by ai には --context independent|self が必要です"
                           "（independent=見積もり作成と別コンテキストのレビュー役、self=作成者本人のレビュー）")
        rec["context"] = a.context
        write_json(rd / "review" / "ai_review.json", rec)
    log_command(rd, "mark-review", a.by)
    _refresh_review_outputs(rd)
    _out({"semantic_review_status": _semantic_status(rd)})
    return 0


def cmd_inspect_standards(a) -> int:
    cfg = load_config(a.config)
    adapter = load_adapter(_resolve(a.adapter or cfg["standards"]["adapter"]))
    std = load_standards(_resolve(cfg["standards"]["cases"]), _resolve(cfg["standards"]["common"]), adapter)
    if a.show_text:
        for k in ("cases", "common"):
            print(standards_text(std[k]))
            print()
    summary = {}
    for k in ("cases", "common"):
        s = std[k]
        summary[k] = {kk: s.get(kk) for kk in ("file", "sha256", "version", "effort_table_location", "thresholds",
                                               "axes", "text_fingerprint", "text_approval", "errors", "warnings")}
        summary[k]["effort"] = {kk: {x: v[x] for x in ("low", "std", "high")} | {"unit": v.get("unit"), "ref": v["refs"]["std"]}
                                for kk, v in (s.get("effort") or {}).items()}
        if k == "common" and s.get("example"):
            summary[k]["example"] = s["example"] | {"recalculated": calc_common_example(s["example"], s)}
    _out(summary)
    return 0 if not std["errors"] else 2


def cmd_evaluate(a) -> int:
    from .evaluate import evaluate_suite

    res = evaluate_suite(_resolve(a.suite))
    _out(res)
    return 0 if res["status"] == "passed" else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="estimator", description="E2E自動化工数見積もりハーネス")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-run", help="実行IDを発行し、入力・基準のハッシュと基準値を記録する")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--input", help="顧客項目書(.xlsx) 1ファイル。1ファイル=1案件")
    g.add_argument("--project", help="複数ファイルで1案件とする案件マニフェスト(YAML)")
    s.add_argument("--config", required=True)
    s.add_argument("--run-id")
    s.set_defaults(fn=cmd_init_run)

    s = sub.add_parser("extract", help="Excelの構造抽出（セル・結合・非表示・図形・領域候補）")
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_extract)

    s = sub.add_parser("survey", help="対象サイトの読み取りだけの調査（site.access=browsable のときだけ。open/goto のみ）")
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_survey)

    s = sub.add_parser("render", help="抽出済みシートを座標つきテキストで表示（AIの読解用）")
    s.add_argument("--run", required=True)
    s.add_argument("--workbook")
    s.add_argument("--sheet", help="シート名または番号")
    s.add_argument("--rows", help="例: 1-80")
    s.add_argument("--max-len", type=int)
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("profile", help="列ごとの値の分布（件数・種類数・上位値）を表示（大規模資料の構造把握用）")
    s.add_argument("--run", required=True)
    s.add_argument("--sheet", required=True, help="シート名または番号")
    s.add_argument("--workbook")
    s.add_argument("--rows", help="例: 5-304")
    s.add_argument("--header-row", type=int)
    s.add_argument("--columns", help="例: B,F,G")
    s.add_argument("--group-by", help="組合せを数える列。例: B,G")
    s.add_argument("--top", type=int, default=15)
    s.add_argument("--max-len", type=int, default=80)
    s.set_defaults(fn=cmd_profile)

    s = sub.add_parser("status", help="工程の状態と、上流変更による無効化を表示")
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("validate-stage", help="AI提出JSONを工程単位で検証（修正回数を記録）")
    s.add_argument("--run", required=True)
    s.add_argument("--stage", required=True, choices=list(STAGE_VALIDATORS) + ["semantic_review"])
    s.set_defaults(fn=cmd_validate_stage)

    s = sub.add_parser("calculate", help="採点と基準から工数を決定的に計算")
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_calculate)

    s = sub.add_parser("validate", help="全体の機械検証と再計算照合 → validation.json")
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("export", help="estimate.xlsx・summary.md・annotated/*_見積付き.xlsx を出力")
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("mark-review", help="意味レビューの状態を記録（human=人確認済）")
    s.add_argument("--run", required=True)
    s.add_argument("--by", choices=["ai", "human"], required=True)
    s.add_argument("--reviewer")
    s.add_argument("--note")
    s.add_argument("--context", choices=["independent", "self"],
                   help="--by ai のとき必須。independent=別コンテキストのレビュー役, self=作成者本人")
    s.set_defaults(fn=cmd_mark_review)

    s = sub.add_parser("inspect-standards", help="基準Excelの読取り結果を確認（アダプター調整用）")
    s.add_argument("--config", required=True)
    s.add_argument("--adapter")
    s.add_argument("--show-text", action="store_true", help="基準の全シートを座標つきで表示")
    s.set_defaults(fn=cmd_inspect_standards)

    s = sub.add_parser("evaluate", help="評価スイートを実行")
    s.add_argument("--suite", required=True)
    s.set_defaults(fn=cmd_evaluate)
    return p


from . import export as export_mod  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except RunError as e:
        _out({"status": "error", "message": str(e)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
