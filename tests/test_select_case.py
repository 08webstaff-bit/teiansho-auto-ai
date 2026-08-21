"""select_case のバリデーション・フォールバックの単体テスト（API 呼び出しなし）。"""

import pytest

from src.select_case import (
    CATEGORY_DEFAULTS,
    build_selection_schema,
    fallback_selection,
    load_cases,
    validate_selection,
)


@pytest.fixture
def cases():
    return load_cases()


def test_cases_json_has_the_12_site_categories(cases):
    """cases.json は 08tent.co.jp/works-top/ のカテゴリーと 1 対 1 で対応させる。"""
    assert len(cases) == 12
    assert set(cases) == {
        "tent_souko", "kaihei_tent", "nisabaki_tent", "jabara_tent",
        "partition", "small_tent", "parasol", "shade",
        "design_tent", "awning", "hisashi_tent", "garage_tent",
    }


def test_all_categories_are_scrapable_list_pages(cases):
    """全カテゴリーが一覧ページ。個別事例はスクレイピングで選べる必要がある。"""
    from src.scrape import is_list_url

    for key, case in cases.items():
        assert is_list_url(case["url"]), key


def test_all_case_urls_are_whitelisted_domain(cases):
    for key, case in cases.items():
        assert case["url"].startswith("https://08tent.co.jp/"), key


def test_garage_category_covers_accordion(cases):
    """アコーディオン式ガレージはガレージテントのカテゴリー内にある（2 ページ目）。"""
    case = cases["garage_tent"]
    assert "アコーディオン" in case["keywords"]
    assert "アコーディオン" in case.get("note", "")


def test_schema_enum_matches_case_keys(cases):
    schema = build_selection_schema(cases)
    enum = schema["properties"]["selected"]["items"]["properties"]["key"]["enum"]
    assert set(enum) == set(cases.keys())


def test_validate_selection_accepts_key_reason_dicts(cases):
    result = {
        "selected": [
            {"key": "jabara_tent", "reason": "伸縮式通路のため"},
            {"key": "nisabaki_tent", "reason": "荷捌き用途の比較用"},
        ]
    }
    assert validate_selection(result, cases) == ["jabara_tent", "nisabaki_tent"]


def test_validate_selection_accepts_valid_keys(cases):
    result = {"selected": ["tent_souko", "awning"]}
    assert validate_selection(result, cases) == ["tent_souko", "awning"]


def test_validate_selection_rejects_unknown_key(cases):
    result = {"selected": ["tent_souko", "fake_key_12345"]}
    with pytest.raises(ValueError):
        validate_selection(result, cases)


def test_validate_selection_dedupes_non_list_category():
    """一覧ページ以外は中身が 1 件しかないので、重複させると同じ事例が 2 枚並ぶ。"""
    only_page = {"solo": {"name": "単独ページ", "url": "https://08tent.co.jp/works/58612/"}}
    result = {"selected": ["solo", "solo"]}
    with pytest.raises(ValueError):
        validate_selection(result, only_page)


def test_validate_selection_allows_same_list_category_twice(cases):
    """一覧カテゴリーは 2 回選べる。商材違いの事例を無理に 2 件目に出さないため。"""
    result = {"selected": ["garage_tent", "garage_tent"]}
    assert validate_selection(result, cases) == ["garage_tent", "garage_tent"]


def test_validate_selection_truncates_to_two(cases):
    result = {"selected": ["tent_souko", "awning", "parasol"]}
    assert len(validate_selection(result, cases)) == 2


def test_category_defaults_all_exist_in_cases(cases):
    for industry, keys in CATEGORY_DEFAULTS.items():
        for key in keys:
            assert key in cases, f"{industry} のデフォルトキー {key} が cases.json にない"


def test_fallback_selection_returns_two_keys(cases):
    quote = {"industry_type": "工場"}
    result = fallback_selection(quote, cases)
    assert len(result["selected"]) == 2
    assert result["fallback"] is True
    assert all(k in cases for k in result["selected"])


def test_fallback_selection_unknown_industry(cases):
    quote = {"industry_type": "宇宙開発"}
    result = fallback_selection(quote, cases)
    assert result["selected"] == CATEGORY_DEFAULTS["その他"]
