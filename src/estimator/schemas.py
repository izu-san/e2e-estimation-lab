"""JSON Schema検証。schemas/ 配下を読み、$refを解決する。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


@lru_cache(maxsize=None)
def _registry() -> Registry:
    resources = []
    for p in SCHEMA_DIR.glob("*.schema.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        resources.append((p.name, Resource.from_contents(doc)))
    return Registry().with_resources(resources)


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    doc = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(doc, registry=_registry())


def schema_errors(name: str, data) -> list[dict]:
    """エラーを {path, message} のリストで返す（AIへ具体的に返すため）。"""
    errs = sorted(_validator(name).iter_errors(data), key=lambda e: list(e.absolute_path))
    return [{"code": "SCHEMA", "path": "/" + "/".join(str(p) for p in e.absolute_path), "message": e.message}
            for e in errs]
