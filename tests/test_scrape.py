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
