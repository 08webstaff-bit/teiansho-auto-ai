"""scrape の HTML パース・URL 判定の単体テスト（ネットワークアクセスなし）。"""

from src.scrape import is_list_url, parse_case_list

SAMPLE_HTML = """
<html><body>
<article>
  <a href="/works/83680/"><img src="/wp-content/uploads/2026/07/83680_1-300x225.jpg"></a>
  <a href="/works/83680/">前面・側面カーテン式の上屋テント（片持ち屋根）</a>
  <a href="/works/83680/">続きを読む</a>
</article>
<article>
  <a href="https://08tent.co.jp/works/83528/"><img data-src="/wp-content/uploads/2026/07/83528_12-300x225.jpg"></a>
  <a href="https://08tent.co.jp/works/83528/">大型トラック対応・荷捌き用片持ちテント屋根</a>
  <a href="https://08tent.co.jp/works/83528/">続きを読む</a>
</article>
<a href="/works_kw/nisabaki-tent/page/2/">次のページ</a>
<a href="/products/temporary-tent/">製品一覧</a>
</body></html>
"""


def test_is_list_url():
    assert is_list_url("https://08tent.co.jp/works_kw/tent-souko/")
    assert not is_list_url("https://08tent.co.jp/works/83528/")
    assert not is_list_url("https://08tent.co.jp/products/warehouse/")


def test_is_list_url_accepts_works_search():
    """施工事例の検索結果ページも個別事例が並ぶので一覧として扱う。"""
    assert is_list_url(
        "https://08tent.co.jp/?post_type=works&works_list=&s=%E3%82%A2%E3%82%B3"
        "%E3%83%BC%E3%83%87%E3%82%A3%E3%82%AA%E3%83%B3%E3%82%AC%E3%83%AC%E3%83%BC%E3%82%B8"
        "&vkfs_form_id=59148"
    )
    # 検索語なし・他ポストタイプの検索は対象外
    assert not is_list_url("https://08tent.co.jp/?post_type=works&works_list=&s=")
    assert not is_list_url("https://08tent.co.jp/?post_type=post&s=テント")
    assert not is_list_url("https://08tent.co.jp/?s=テント")


def test_parse_case_list_handles_search_result_page():
    """検索結果ページも works_kw と同じパーサーで個別事例を抜き出せる。"""
    search_url = "https://08tent.co.jp/?post_type=works&s=%E3%82%A2%E3%82%B3"
    cases = parse_case_list(SAMPLE_HTML, search_url)
    assert len(cases) == 2
    for c in cases:
        assert c["url"].startswith("https://08tent.co.jp/works/")


def test_parse_case_list_extracts_individual_cases():
    cases = parse_case_list(SAMPLE_HTML, "https://08tent.co.jp/works_kw/nisabaki-tent/")
    assert len(cases) == 2
    urls = [c["url"] for c in cases]
    assert "https://08tent.co.jp/works/83680/" in urls
    assert "https://08tent.co.jp/works/83528/" in urls


def test_parse_case_list_urls_are_absolute_and_trailing_slash():
    cases = parse_case_list(SAMPLE_HTML, "https://08tent.co.jp/works_kw/nisabaki-tent/")
    for c in cases:
        assert c["url"].startswith("https://08tent.co.jp/works/")
        assert c["url"].endswith("/")


def test_parse_case_list_picks_title_not_read_more():
    cases = parse_case_list(SAMPLE_HTML, "https://08tent.co.jp/works_kw/nisabaki-tent/")
    by_url = {c["url"]: c for c in cases}
    assert "上屋テント" in by_url["https://08tent.co.jp/works/83680/"]["title"]
    assert by_url["https://08tent.co.jp/works/83680/"]["title"] != "続きを読む"


def test_parse_case_list_captures_thumbnail():
    cases = parse_case_list(SAMPLE_HTML, "https://08tent.co.jp/works_kw/nisabaki-tent/")
    for c in cases:
        assert c["thumbnail"] and c["thumbnail"].startswith("https://08tent.co.jp/")


def test_parse_case_list_ignores_pagination_and_products():
    cases = parse_case_list(SAMPLE_HTML, "https://08tent.co.jp/works_kw/nisabaki-tent/")
    urls = [c["url"] for c in cases]
    assert not any("/works_kw/" in u for u in urls)
    assert not any("/products/" in u for u in urls)


def test_page_url_for_category_list():
    from src.scrape import page_url

    base = "https://08tent.co.jp/works_kw/parking-garage/"
    assert page_url(base, 1) == base
    assert page_url(base, 2) == "https://08tent.co.jp/works_kw/parking-garage/page/2/"
    assert page_url(base, 3) == "https://08tent.co.jp/works_kw/parking-garage/page/3/"


def test_page_url_for_search_result():
    from src.scrape import page_url

    base = "https://08tent.co.jp/?post_type=works&s=%E3%82%A2"
    assert page_url(base, 1) == base
    assert page_url(base, 2) == base + "&paged=2"


def test_fetch_case_list_follows_pages(monkeypatch):
    """1 ページ目だけだと該当事例を取りこぼすので、全ページを辿る。"""
    import src.scrape as sc

    page2 = SAMPLE_HTML.replace("83680", "70001").replace("83528", "70002")

    class Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def fake_get(url, **kw):
        if url.endswith("/page/2/"):
            return Resp(page2)
        if "/page/" in url:
            raise RuntimeError("404")  # 3 ページ目以降は存在しない
        return Resp(SAMPLE_HTML)

    monkeypatch.setattr(sc.requests, "get", fake_get)
    monkeypatch.setattr(sc, "_ensure_dir", lambda p: False)  # キャッシュ無効
    cases = sc.fetch_case_list("https://08tent.co.jp/works_kw/nisabaki-tent/")
    urls = [c["url"] for c in cases]
    assert len(cases) == 4
    assert "https://08tent.co.jp/works/70001/" in urls


def test_fetch_case_list_stops_when_page_repeats(monkeypatch):
    """同じ内容が返り続けるサイトでも無限には辿らない。"""
    import src.scrape as sc

    class Resp:
        text = SAMPLE_HTML

        def raise_for_status(self):
            pass

    monkeypatch.setattr(sc.requests, "get", lambda url, **kw: Resp())
    monkeypatch.setattr(sc, "_ensure_dir", lambda p: False)
    cases = sc.fetch_case_list("https://08tent.co.jp/works_kw/nisabaki-tent/")
    assert len(cases) == 2
