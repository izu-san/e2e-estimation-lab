"""実行(run)の作成・状態管理・再開時の無効化判定。"""

from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from . import CASE_RULE_VERSION, COMMON_RULE_VERSION, __version__
from .io_utils import now_iso, read_json, sha256_file, write_json
from .schemas import schema_errors

ROOT = Path(__file__).resolve().parents[2]

# 工程の順序と、各工程が読む上流ファイル（相対パス）
STAGES = ["init", "extract", "normalize", "screens", "common_design", "assessments", "calculate", "validate", "export"]
AI_FILES = {
    "normalize": "ai/normalized_cases.json",
    "screens": "ai/screens.json",
    "common_design": "ai/common_design.json",
    "assessments": "ai/assessments.json",
    "questions": "ai/questions.json",
}
STAGE_INPUTS = {
    "extract": ["manifest.json"],
    "normalize": ["source_inventory.json", "raw_workbook.json"],
    "screens": ["ai/normalized_cases.json", "survey/pages.json"],
    "common_design": ["ai/normalized_cases.json", "ai/screens.json"],
    "assessments": ["ai/normalized_cases.json", "ai/screens.json", "ai/common_design.json", "standards.json"],
    "calculate": ["standards.json", "ai/normalized_cases.json", "ai/common_design.json", "ai/assessments.json"],
    "validate": ["estimate.json", "ai/questions.json"],
    "export": ["estimate.json", "validation.json"],
}
STAGE_OUTPUTS = {
    "init": ["manifest.json", "standards.json"],
    "extract": ["raw_workbook.json", "source_inventory.json"],
    "normalize": ["ai/normalized_cases.json"],
    "screens": ["ai/screens.json"],
    "common_design": ["ai/common_design.json"],
    "assessments": ["ai/assessments.json"],
    "calculate": ["estimate.json"],
    "validate": ["validation.json"],
    "export": ["estimate.xlsx", "summary.md"],
}

DEFAULT_CONFIG: dict[str, Any] = {
    "target": {"automation_tool": "playwright", "language": "typescript", "browsers": ["chromium"], "environments": 1},
    "architecture": {"pom": "unspecified", "existing_assets": "unknown"},
    "scope": {"excluded_type_ids": [], "notes": []},
    "uncertainty": {"allow_explicit_assumptions": True, "on_unresolved": "continue_as_pending"},
    "execution": {"site_interaction": False, "max_repair_attempts": 2, "chunk_rows": 80},
    "site": {"access": "unavailable", "base_url": None,
             "survey": {"max_pages": 40}},
}


class RunError(Exception):
    pass


def _resolve(p: str | Path, base: Path = ROOT) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (base / p)


def load_config(path: str | Path) -> dict:
    path = _resolve(path)
    if not path.exists():
        raise RunError(f"設定ファイルが見つかりません: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    errs = schema_errors("config", raw)
    if errs:
        raise RunError("設定ファイルの形式エラー: " + json.dumps(errs, ensure_ascii=False))
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in raw.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    cfg.setdefault("standards", {}).setdefault("adapter", "config/standards_adapter.yaml")
    cfg["_config_path"] = str(path)
    return cfg


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:40] or "input"


def new_run_id(stem: str) -> str:
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{_slug(stem)}-{secrets.token_hex(2)}"


def runs_root() -> Path:
    return _resolve(os.environ.get("ESTIMATOR_RUNS_DIR", "runs"))


def run_dir(run: str) -> Path:
    p = Path(run)
    if p.exists() and p.is_dir():
        return p.resolve()
    p = runs_root() / run
    if not p.is_dir():
        raise RunError(f"runが見つかりません: {run}")
    return p.resolve()


def _git_rev() -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "src", "schemas", "config",
                                ".claude", "scripts"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip() + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _file_record(p: Path) -> dict:
    return {"path": str(p), "file_name": p.name, "exists": p.exists(),
            "sha256": sha256_file(p) if p.exists() else None, "size": p.stat().st_size if p.exists() else None}


def harness_fingerprint() -> dict:
    files = sorted([*ROOT.glob("src/estimator/*.py"), *ROOT.glob("schemas/*.json"),
                    *ROOT.glob(".claude/skills/estimate-e2e/**/*.md")])
    from .io_utils import sha256_json
    return {
        "harness_version": __version__,
        "rule_versions": {"cases": CASE_RULE_VERSION, "common": COMMON_RULE_VERSION},
        "source_sha256": sha256_json({str(f.relative_to(ROOT)): sha256_file(f) for f in files}),
        "git_rev": _git_rev(),
    }


# ---------------------------------------------------------------- state

def load_state(rd: Path) -> dict:
    p = rd / "stage_state.json"
    if p.exists():
        return read_json(p)
    return {"schema_version": 1, "stages": {s: {"status": "pending"} for s in STAGES}, "history": []}


def save_state(rd: Path, state: dict) -> None:
    write_json(rd / "stage_state.json", state)


def file_hashes(rd: Path, rels: list[str]) -> dict[str, str | None]:
    return {r: (sha256_file(rd / r) if (rd / r).exists() else None) for r in rels}


def mark_stage(rd: Path, stage: str, status: str, **extra) -> dict:
    state = load_state(rd)
    st = state["stages"].setdefault(stage, {})
    st.update(status=status, updated_at=now_iso(),
              inputs=file_hashes(rd, STAGE_INPUTS.get(stage, [])),
              outputs=file_hashes(rd, STAGE_OUTPUTS.get(stage, [])))
    st.update(extra)
    state["history"].append({"at": now_iso(), "stage": stage, "status": status,
                             **{k: v for k, v in extra.items() if k in ("attempt", "error_count")}})
    save_state(rd, state)
    return state


def refresh_state(rd: Path) -> dict:
    """上流成果物のハッシュ変化を検出し、変わった工程より下流を stale にする。"""
    state = load_state(rd)
    stale_from: int | None = None
    for i, s in enumerate(STAGES):
        st = state["stages"].get(s, {})
        if st.get("status") in (None, "pending"):
            continue
        changed_in = any(file_hashes(rd, [r])[r] != h for r, h in (st.get("inputs") or {}).items())
        changed_out = any(file_hashes(rd, [r])[r] != h for r, h in (st.get("outputs") or {}).items())
        if stale_from is not None and i > stale_from:
            if st.get("status") != "stale":
                st["status"] = "stale"
                st["stale_reason"] = f"上流工程 {STAGES[stale_from]} が変更されました"
        elif changed_in or changed_out:
            if s in AI_FILES and changed_out and not changed_in:
                st["status"] = "modified"  # AI提出ファイルが検証後に変更された
                st["stale_reason"] = "提出ファイルが前回検証後に変更されました（再検証が必要）"
            else:
                st["status"] = "stale"
                st["stale_reason"] = "入力または出力のハッシュが記録と異なります"
            stale_from = i
    save_state(rd, state)
    return state


def verify_sources_unchanged(rd: Path) -> list[dict]:
    """manifestに記録した入力・基準ファイルのハッシュと現物を比較する。"""
    man = read_json(rd / "manifest.json")
    errs = []
    for rec in man["inputs"] + [man["standards"]["cases"], man["standards"]["common"], man["standards"]["adapter"],
                                man["config"]]:
        p = Path(rec["path"])
        cur = sha256_file(p) if p.exists() else None
        if rec.get("sha256") and cur != rec["sha256"]:
            errs.append({"code": "SOURCE_CHANGED", "path": rec["path"],
                         "message": f"実行開始時からファイルが変更・削除されています (start={rec['sha256']}, now={cur})"})
    return errs


def log_command(rd: Path, cmd: str, result: str, detail: Any = None) -> None:
    (rd / "logs").mkdir(exist_ok=True)
    with open(rd / "logs" / "commands.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": now_iso(), "cmd": cmd, "result": result, "detail": detail},
                           ensure_ascii=False, default=str) + "\n")


def environment_info() -> dict:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "model": os.environ.get("ESTIMATOR_MODEL") or os.environ.get("ANTHROPIC_MODEL"),
        "claude_code_version": os.environ.get("ESTIMATOR_CLAUDE_VERSION"),
        "mode": os.environ.get("ESTIMATOR_MODE", "dev"),
    }
