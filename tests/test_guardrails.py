"""Hooks・設定生成のテスト（Claude Code本体を使わない範囲）。実機の権限テストは scripts/permission_check.sh。"""

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import ROOT

HOOKS = ROOT / "scripts" / "hooks"


def hook(name, payload, env_extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ESTIMATOR_")}
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-B", str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                       text=True, env=env, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout) if p.stdout.strip() else None


def est_env(rd):
    return {"ESTIMATOR_MODE": "estimate", "ESTIMATOR_RUN_DIR": str(rd)}


def test_guard_inactive_in_dev_mode(tmp_path):
    out = hook("pre_tool_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(ROOT / "src/x.py")}})
    assert out is None


def test_guard_denies_outside_run(tmp_path):
    rd = tmp_path / "runs" / "r1"
    rd.mkdir(parents=True)
    for target in (ROOT / "inputs/a.xlsx", ROOT / "src/estimator/validate.py", tmp_path / "runs/other/x.json",
                   rd / ".." / "other.json"):
        out = hook("pre_tool_guard.py", {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}, est_env(rd))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", target
    out = hook("pre_tool_guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(rd / "ai/a.json")}},
               est_env(rd))
    assert out is None
    out = hook("pre_tool_guard.py", {"tool_name": "Write", "tool_input": {"file_path": "ai/b.json"}, "cwd": str(rd)},
               est_env(rd))
    assert out is None


def test_post_validate_reports_schema_errors(tmp_path):
    rd = tmp_path / "r1"
    (rd / "ai").mkdir(parents=True)
    f = rd / "ai" / "assessments.json"
    f.write_text(json.dumps({"schema_version": 1, "case_assessments": [{"case_id": "C", "effort": 3}],
                             "common_assessments": []}))
    out = hook("post_tool_validate.py", {"tool_name": "Write", "tool_input": {"file_path": str(f)}}, est_env(rd))
    assert "スキーマエラー" in out["hookSpecificOutput"]["additionalContext"]
    other = rd / "notes.json"
    other.write_text("{}")
    assert hook("post_tool_validate.py", {"tool_name": "Write", "tool_input": {"file_path": str(other)}}, est_env(rd)) is None


def test_stop_hook_limited(tmp_path):
    rd = tmp_path / "r1"
    rd.mkdir()
    outs = [hook("stop_check.py", {"stop_hook_active": False}, est_env(rd)) for _ in range(3)]
    assert outs[0]["decision"] == "block" and outs[1]["decision"] == "block" and outs[2] is None
    assert hook("stop_check.py", {"stop_hook_active": True}, est_env(rd)) is None
    assert hook("stop_check.py", {"stop_hook_active": False}) is None  # 開発モードでは何もしない


def _gen_settings(rd, *extra):
    p = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/make_session_settings.py"), "--run-dir", str(rd), *extra],
                       capture_output=True, text=True, check=True)
    out = Path(p.stdout.strip())
    return out, json.loads(out.read_text())


def test_session_settings_generation(tmp_path):
    """既定はOS非依存（権限ルール＋Hook）。sandboxは含めない。"""
    rd = ROOT / "runs" / "zz-settings-test"
    try:
        rd.mkdir(parents=True, exist_ok=True)
        out, s = _gen_settings(rd)
        assert "sandbox" not in s
        assert s["permissions"]["defaultMode"] == "dontAsk"
        assert f"Edit(/{ROOT}/inputs/**)" in s["permissions"]["deny"]
        assert f"Edit(/{rd}/**)" in s["permissions"]["allow"]
        # Bashは scripts/estimator のみ（sandboxが無くても任意コマンドで保護対象を書換えられない根拠）
        assert [a for a in s["permissions"]["allow"] if a.startswith("Bash(")] == [
            f"Bash({ROOT}/scripts/estimator *)", "Bash(scripts/estimator *)"]
        assert "Agent(estimate-reviewer)" in s["permissions"]["allow"]  # 独立した意味レビュー用
        # AgentはdontAskでも許可なしで通るため、読取り専用のレビュー役以外は個別にdenyする
        assert {"Agent(general-purpose)", "Agent(Explore)", "Agent(Plan)"} <= set(s["permissions"]["deny"])
        assert {"PreToolUse", "PostToolUse", "Stop"} <= set(s["hooks"])
        assert s["env"]["ESTIMATOR_RUN_DIR"] == str(rd)
        assert not any(t in out.read_text() for t in ("{ROOT}", "{RUN_DIR}", "{SESSIONS_DIR}"))
        out.unlink()
    finally:
        _cleanup_settings(rd)


def test_session_settings_with_sandbox(tmp_path):
    """--sandbox で OSサンドボックスの設定が追加される（既定の権限ルールは維持）。"""
    rd = ROOT / "runs" / "zz-settings-sb-test"
    try:
        rd.mkdir(parents=True, exist_ok=True)
        out, s = _gen_settings(rd, "--sandbox")
        sb = s["sandbox"]
        assert sb["enabled"] and sb["failIfUnavailable"] and not sb["allowUnsandboxedCommands"]
        assert f"{ROOT}/src" in sb["filesystem"]["denyWrite"]
        assert "Bash(dangerouslyDisableSandbox:true)" in s["permissions"]["deny"]
        assert f"Edit(/{ROOT}/inputs/**)" in s["permissions"]["deny"]
        assert f"Edit(/{rd}/**)" in s["permissions"]["allow"]
        assert not any(t in out.read_text() for t in ("{ROOT}", "{RUN_DIR}", "{SESSIONS_DIR}"))
        out.unlink()
    finally:
        _cleanup_settings(rd)


def _cleanup_settings(rd):
    if rd.exists():
        rd.rmdir()
    sessions = ROOT / "runs" / ".sessions"
    if sessions.exists() and not any(sessions.iterdir()):
        sessions.rmdir()


def test_reviewer_agent_is_read_only():
    text = (ROOT / ".claude/agents/estimate-reviewer.md").read_text(encoding="utf-8")
    front = text.split("---")[1]
    tools = [l for l in front.splitlines() if l.startswith("tools:")][0].split(":", 1)[1]
    assert {t.strip() for t in tools.split(",")} <= {"Read", "Grep", "Glob"}  # 書込み・実行系を持たせない
