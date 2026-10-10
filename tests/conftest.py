import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from helpers import build_cases_standard, build_common_standard  # noqa: E402

REAL_ADAPTER = ROOT / "config" / "standards_adapter.yaml"


def _test_adapter() -> Path:
    """人工基準用のアダプター。正本向けの承認済みフィンガープリントだけを外したコピー。"""
    import tempfile

    import yaml

    d = yaml.safe_load(REAL_ADAPTER.read_text(encoding="utf-8"))
    for k in ("cases", "common"):
        d[k]["approved_text_fingerprint"] = None
    p = Path(tempfile.mkdtemp(prefix="estimator-adapter-")) / "standards_adapter.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return p


ADAPTER = _test_adapter()


@pytest.fixture
def std_files(tmp_path):
    c = build_cases_standard(tmp_path / "cases_v0.1.xlsx")
    m = build_common_standard(tmp_path / "common_v0.1.xlsx")
    return c, m


@pytest.fixture
def standards(std_files):
    from estimator.standards import load_adapter, load_standards, strip_private

    std = load_standards(*std_files, load_adapter(ADAPTER))
    assert std["errors"] == []
    return strip_private(std)


@pytest.fixture(autouse=True)
def _isolated_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTIMATOR_RUNS_DIR", str(tmp_path / "runs"))
