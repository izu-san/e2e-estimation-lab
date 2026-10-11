"""対象サイトの読み取りだけの調査。ブラウザーは偽物（ネットワークに出ない）。"""

import json

from helpers import write_json
from test_pipeline import REF, _stage, run, run_cli, screens  # noqa: F401

from estimator.survey import crawl, parse_snapshot, run_survey, url_template

BASE = "https://shop.example"
SITE = {
    "/": ["/products", "/product_details/1", "/product_details/2", "/login", "/logout", "#top", "https://other.example/x"],
    "/products": ["/product_details/3", "/brand_products/Polo", "/brand_products/H&M"],
    "/login": ["/"],
    "/brand_products/Polo": ["/products"],
    "/product_details/1": [],
}


def snapshot(links, heading="見出し"):
    lines = [f'- heading "{heading}" [level=2] [ref=e1]', '- textbox "Email" [ref=e2]']
    lines += [f"- link [ref=e9]:\n  - /url: {u}" for u in links]
    return "\n".join(lines)


class FakeDriver:
    def __init__(self):
        self.visited = []

    def goto(self, url):
        path = url[len(BASE):] or "/"
        self.visited.append(path)
        return url, f"title {path}", snapshot(SITE.get(path, [])), None


def test_url_template_and_snapshot_parse():
    assert url_template("/") == "/"
    assert url_template("/product_details/12") == "/product_details/{*}"
    assert url_template("/brand_products/Mast%20%26%20Harbour") == "/brand_products/{*}"
    info = parse_snapshot(snapshot(["/a", "/b"]))
    assert info == {"links": ["/a", "/b"], "headings": ["見出し"], "inputs": 1}


def test_crawl_opens_one_page_per_template_and_skips_excluded():
    d = FakeDriver()
    res = crawl(BASE + "/", d, max_pages=10, exclude=["logout"])
    assert d.visited == ["/", "/products", "/product_details/1", "/login", "/brand_products/Polo"]
    assert [p["template"] for p in res["pages"]] == ["/", "/products", "/product_details/{*}", "/login", "/brand_products/{*}"]
    assert {s["template"]: s["reason"] for s in res["skipped"]} == {"/logout": "excluded"}
    res = crawl(BASE + "/", FakeDriver(), max_pages=2, exclude=[])
    assert len(res["pages"]) == 2 and any(s["reason"] == "max_pages" for s in res["skipped"])


def test_crawl_prefers_all_links_from_driver():
    class Hidden(FakeDriver):  # 折りたたみ内のリンクはスナップショットに無いが、リンク一覧にはある
        def goto(self, url):
            final, title, snap, _ = super().goto(url)
            return final, title, snap, ["/category_products/1"] if url.endswith("/") else []

    res = crawl(BASE + "/", Hidden(), max_pages=10, exclude=[])
    assert [p["template"] for p in res["pages"]] == ["/", "/category_products/{*}"]


def test_observed_screens_are_checked_against_survey(run, capsys):
    rd, _ = run
    s = screens()
    s["screens"][0].update(basis="observed", url="/products")
    write_json(rd / "ai/screens.json", s)
    assert "OBSERVED_WITHOUT_SURVEY" in _stage(capsys, "screens")[1]
    run_survey(rd, {"access": "browsable", "base_url": BASE + "/", "survey": {"exclude_url_patterns": ["logout"]}},
               driver=FakeDriver())
    doc = json.loads((rd / "survey/pages.json").read_text())
    assert (rd / "survey" / doc["pages"][0]["snapshot"]).exists() and "_snapshot_text" not in doc["pages"][0]
    code, errors, warns = _stage(capsys, "screens")
    assert not errors and "SURVEY_PAGE_UNREVIEWED" in warns  # / や /login などを一覧で扱っていない
    s["screens"][0]["url"] = "/cart"
    write_json(rd / "ai/screens.json", s)
    assert "SCREEN_URL_NOT_SURVEYED" in _stage(capsys, "screens")[1]
    s["screens"][0]["url"] = "/products"
    s["screens"][1].update(basis="observed", url="/product_details/7")  # 同じテンプレートの別データ
    s["not_counted"] = [{"name": n, "reason": "項目書に無い", "merged_into": None, "url": u}
                        for n, u in (("ホーム", "/"), ("ログイン", "/login"), ("ブランド", "/brand_products/X"))]
    write_json(rd / "ai/screens.json", s)
    code, errors, warns = _stage(capsys, "screens")
    assert not errors and "SURVEY_PAGE_UNREVIEWED" not in warns


def test_survey_requires_browsable_site(run, capsys):
    rd, _ = run
    code, out = run_cli(capsys, "survey", "--run", "t1")
    assert code == 2 and "browsable" in out["message"]


def test_browsable_site_requires_survey(run, capsys):
    rd, _ = run
    man = json.loads((rd / "manifest.json").read_text())
    man["config_resolved"]["site"] = {"access": "browsable", "base_url": BASE + "/"}
    write_json(rd / "manifest.json", man)
    assert "SURVEY_MISSING" in _stage(capsys, "screens")[1]
    run_survey(rd, man["config_resolved"]["site"], driver=FakeDriver())
    assert "SURVEY_MISSING" not in _stage(capsys, "screens")[1]
