"""対象サイトの読み取りだけの調査（閲覧できる案件のみ）。

playwright-cli でページを開き（goto）、ページ構造（アクセシビリティスナップショット）を保存するだけで、
クリック・入力・送信はしない。同じサイト内のリンクを幅優先でたどり、URLの形（テンプレート）ごとに1ページだけ開く。
結果は runs/<id>/survey/pages.json。画面一覧（ai/screens.json）で basis=observed の根拠になる。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from .io_utils import now_iso, write_json

ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = ROOT / "tools" / "site-survey"
CLI = TOOL_DIR / "node_modules" / ".bin" / "playwright-cli"
CLI_CONFIG = TOOL_DIR / "cli.config.json"

_URL = re.compile(r"^\s*- /url: \"?(.*?)\"?\s*$")
_HEADING = re.compile(r"^\s*- heading \"(.+?)\" \[level=([1-3])\]")
_INPUT = re.compile(r"^\s*- (textbox|combobox|checkbox|radio|spinbutton|searchbox)\b")
_LINKS_JS = "() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href')))]"
_PAGE_URL = re.compile(r"^- Page URL: (.+)$", re.M)
_PAGE_TITLE = re.compile(r"^- Page Title: (.*)$", re.M)
_SNAPSHOT = re.compile(r"^- \[Snapshot\]\((.+?)\)$", re.M)


DEFAULT_EXCLUDE = ["logout", "delete", "remove", "signout"]


class SurveyError(Exception):
    pass


def url_template(path: str) -> str:
    """URLのパスをテンプレートにする。2つ目以降のセグメントは可変として {*} に置き換える
    （/product_details/1 と /product_details/2 は同じ画面の別データ）。"""
    segs = [s for s in unquote(path).split("/") if s]
    if not segs:
        return "/"
    return "/" + "/".join([segs[0]] + ["{*}"] * (len(segs) - 1))


def parse_snapshot(text: str) -> dict:
    links, headings, inputs = [], [], 0
    for line in text.splitlines():
        if m := _URL.match(line):
            links.append(m.group(1))
        elif m := _HEADING.match(line):
            headings.append(m.group(1))
        if _INPUT.match(line):
            inputs += 1
    return {"links": links, "headings": headings[:15], "inputs": inputs}


class PlaywrightCliDriver:
    """playwright-cli の open / goto / snapshot / eval（リンクの列挙）/ close だけを使う（クリック・入力などは呼ばない）。"""

    def __init__(self, session: str, workdir: Path, timeout: int = 60):
        if not CLI.exists():
            raise SurveyError(f"playwright-cli がありません: {CLI}（開発モードで `npm install --prefix tools/site-survey` と "
                              "`tools/site-survey/node_modules/.bin/playwright install chromium` を実行）")
        self.session, self.workdir, self.timeout = session, workdir, timeout

    def _run(self, *args: str) -> str:
        cmd = [str(CLI), f"-s={self.session}", *args]
        try:
            p = subprocess.run(cmd, cwd=self.workdir, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as e:
            raise SurveyError(f"playwright-cli がタイムアウトしました: {' '.join(args)}") from e
        if p.returncode != 0:
            raise SurveyError(f"playwright-cli {args[0]} が失敗しました: {(p.stderr or p.stdout)[-500:]}")
        return p.stdout

    def open(self) -> None:
        self._run("open", f"--config={CLI_CONFIG}")

    def goto(self, url: str) -> tuple[str, str, str, list[str] | None]:
        """(最終URL, タイトル, スナップショット本文, ページ内の全リンク)。リンクは折りたたまれた要素も含めて
        読み取り専用の式（a[href] の列挙）で取る。スナップショットは表示中の要素しか含まないため。"""
        out = self._run("goto", url)
        final = (_PAGE_URL.search(out) or [None, url])[1].strip()
        title = (_PAGE_TITLE.search(out) or [None, ""])[1].strip()
        snap = _SNAPSHOT.search(out)
        if snap is None:
            self._run("snapshot", "--filename=_current.yml")
            path = self.workdir / "_current.yml"
        else:
            path = self.workdir / snap.group(1)
        return final, title, path.read_text(encoding="utf-8"), self._links()

    def _links(self) -> list[str] | None:
        out = self._run("eval", _LINKS_JS)
        m = re.search(r"^### Result\s*\n(.*?)(?:\n### |\Z)", out, re.S | re.M)
        try:
            return [x for x in json.loads(m.group(1)) if isinstance(x, str)] if m else None
        except ValueError:
            return None

    def close(self) -> None:
        try:
            self._run("close")
        except SurveyError:
            pass


def crawl(base_url: str, driver, *, max_pages: int, exclude: list[str]) -> dict:
    """同じオリジンのリンクを幅優先でたどり、テンプレートごとに1ページだけ開く。"""
    origin = urlsplit(base_url)
    excl = [re.compile(p, re.I) for p in exclude]
    queue: deque[tuple[str, str | None]] = deque([(base_url, None)])
    seen_templates: set[str] = set()
    pages, skipped, errors = [], {}, []
    while queue:
        url, found_on = queue.popleft()
        u = urlsplit(url)
        tpl = url_template(u.path)
        if tpl in seen_templates:
            continue
        if len(pages) >= max_pages:
            skipped.setdefault(tpl, {"template": tpl, "url": url, "reason": "max_pages"})
            continue
        seen_templates.add(tpl)
        try:
            final, title, snap, all_links = driver.goto(url)
        except Exception as e:  # noqa: BLE001  1ページの失敗で調査全体を止めない
            errors.append({"url": url, "message": str(e)[:300]})
            continue
        info = parse_snapshot(snap)
        pages.append({"url": url, "final_url": final, "template": tpl, "final_template": url_template(urlsplit(final).path),
                      "title": title, "headings": info["headings"], "inputs": info["inputs"],
                      "found_on": found_on, "snapshot": f"snapshots/{len(pages) + 1:03d}.yml", "_snapshot_text": snap})
        for link in all_links if all_links is not None else info["links"]:
            if link.startswith("#") or link.startswith(("mailto:", "tel:", "javascript:")):
                continue
            nxt = urlsplit(urljoin(final, link))
            if (nxt.scheme, nxt.netloc) != (origin.scheme, origin.netloc):
                continue
            clean = f"{nxt.scheme}://{nxt.netloc}{nxt.path or '/'}"
            ntpl = url_template(nxt.path)
            if any(p.search(nxt.path) for p in excl):
                skipped.setdefault(ntpl, {"template": ntpl, "url": clean, "reason": "excluded"})
                continue
            if ntpl not in seen_templates:
                queue.append((clean, url))
    return {"pages": pages, "skipped": sorted(skipped.values(), key=lambda s: s["template"]), "errors": errors}


def run_survey(rd: Path, site: dict, driver=None) -> dict:
    if site.get("access") != "browsable" or not site.get("base_url"):
        raise SurveyError("案件設定の site.access が browsable で、site.base_url があるときだけ調査します")
    out_dir = rd / "survey"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "snapshots").mkdir(parents=True)
    work = out_dir / ".work"
    work.mkdir()
    opts = site.get("survey") or {}
    own = driver is None
    if own:
        driver = PlaywrightCliDriver(f"est-{rd.name[-24:]}", work)
        driver.open()
    started = now_iso()
    try:
        res = crawl(site["base_url"], driver, max_pages=int(opts.get("max_pages", 40)),
                    exclude=list(opts.get("exclude_url_patterns", DEFAULT_EXCLUDE)))
    finally:
        if own:
            driver.close()
    for p in res["pages"]:
        (out_dir / p["snapshot"]).write_text(p.pop("_snapshot_text"), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    doc = {"schema_version": 1, "base_url": site["base_url"], "tool": "playwright-cli（読み取りのみ: open/goto/snapshot/eval(リンク列挙)/close）",
           "started_at": started, "finished_at": now_iso(), **res}
    write_json(out_dir / "pages.json", doc)
    return doc


def surveyed_pages(rd: Path) -> list[set[str]] | None:
    """調査で開いたページごとのテンプレートの組（開いたURLと最終URLの形）。調査していなければ None。"""
    from .io_utils import read_json

    p = rd / "survey" / "pages.json"
    if not p.exists():
        return None
    return [{pg["template"], pg["final_template"]} for pg in read_json(p)["pages"]]


def template_of(url: str) -> str:
    return url_template(urlsplit(url).path)
