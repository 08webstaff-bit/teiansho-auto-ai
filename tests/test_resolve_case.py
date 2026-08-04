"""resolve_case の個別事例解決ロジックの単体テスト（スクレイピング・API はモック）。"""

import pytest

import src.resolve_case as rc

QUOTE = {"customer_name": "テスト", "project_name": "荷捌き場テント", "industry_type": "工場", "items": []}

CANDIDATES = [
    {"url": "https://08tent.co.jp/works/83680/", "title": "上屋テント（片持ち屋根）", "thumbnail": "https://08tent.co.jp/a.jpg"},
    {"url": "https://08tent.co.jp/works/83528/", "title": "大型トラック対応 片持ちテント屋根", "thumbnail": "https://08tent.co.jp/b.jpg"},
]


def test_non_list_case_used_as_is(monkeypatch):
    # 個別事例 URL（works/数字）はスクレイピングせずそのまま使う
    case = {"name": "工場間通路テント（常設）", "url": "https://08tent.co.jp/works/58612/"}
    result = rc.resolve_individual_case(QUOTE, "factory_passage_permanent", case)
    assert result["url"] == "https://08tent.co.jp/works/58612/"
    assert result["is_individual"] is False
    assert result["resolved"] is True


def test_products_page_used_as_is():
    case = {"name": "イベント用テント", "url": "https://08tent.co.jp/products/temporary-tent/"}
    result = rc.resolve_individual_case(QUOTE, "event_temporary", case)
    assert result["url"] == "https://08tent.co.jp/products/temporary-tent/"
    assert result["is_individual"] is False


def test_list_case_resolves_to_scraped_individual(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(
        rc, "_pick_index", lambda q, name, c: {"index": 1, "reason": "大型トラック対応のため"}
    )
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent_list", case)
    assert result["url"] == "https://08tent.co.jp/works/83528/"  # index 1
    assert result["is_individual"] is True
    assert result["reason"] == "大型トラック対応のため"
    assert result["thumbnail"] == "https://08tent.co.jp/b.jpg"


def test_list_case_scrape_failure_falls_back_to_category(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: [])
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent_list", case)
    assert result["url"] == "https://08tent.co.jp/works_kw/nisabaki-tent/"
    assert result["is_individual"] is False


def test_invalid_index_from_api_falls_back_to_first(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c: {"index": 99, "reason": "x"})
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent_list", case)
    assert result["url"] == "https://08tent.co.jp/works/83680/"  # index 0 に補正


def test_api_error_falls_back_to_first_candidate(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("API error")

    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", boom)
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent_list", case)
    assert result["url"] == "https://08tent.co.jp/works/83680/"
    assert result["is_individual"] is True


def test_category_candidates_for_list(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    case = {"name": "荷捌き場テント一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    cands = rc.category_candidates(case)
    assert len(cands) == 2
    assert cands[0]["url"] == "https://08tent.co.jp/works/83680/"


def test_category_candidates_for_individual_page():
    case = {"name": "工場間通路テント", "url": "https://08tent.co.jp/works/58612/"}
    cands = rc.category_candidates(case)
    assert len(cands) == 1
    assert cands[0]["url"] == "https://08tent.co.jp/works/58612/"


def test_category_candidates_scrape_failure_returns_list_page(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: [])
    case = {"name": "荷捌き場テント一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    cands = rc.category_candidates(case)
    assert len(cands) == 1
    assert cands[0]["url"] == "https://08tent.co.jp/works_kw/nisabaki-tent/"


def test_make_resolved_from_candidate_manual():
    case = {"name": "荷捌き場テント一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    r = rc.make_resolved_from_candidate("nisabaki_tent_list", case, CANDIDATES[1], manual=True)
    assert r["url"] == "https://08tent.co.jp/works/83528/"
    assert r["is_individual"] is True
    assert "手動" in r["reason"]


def test_make_resolved_from_candidate_individual_page():
    case = {"name": "工場間通路テント", "url": "https://08tent.co.jp/works/58612/"}
    cand = {"url": "https://08tent.co.jp/works/58612/", "title": "工場間通路テント", "thumbnail": None}
    r = rc.make_resolved_from_candidate("factory_passage_permanent", case, cand)
    assert r["is_individual"] is False


def test_resolve_selection_all_urls_are_real(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c: {"index": 0, "reason": "r"})
    cases = {
        "nisabaki_tent_list": {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"},
        "factory_passage_permanent": {"name": "工場間通路テント", "url": "https://08tent.co.jp/works/58612/"},
    }
    selection = {"selected": ["nisabaki_tent_list", "factory_passage_permanent"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert len(resolved) == 2
    for r in resolved:
        assert r["url"].startswith("https://08tent.co.jp/")
        assert "/works_kw/" not in r["url"]  # 一覧 URL は最終提示に残らない
