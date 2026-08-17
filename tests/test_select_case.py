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


def test_cases_json_has_29_entries(cases):
    assert len(cases) == 29


def test_all_case_urls_are_whitelisted_domain(cases):
    for key, case in cases.items():
        assert case["url"].startswith("https://08tent.co.jp/"), key


def test_accordion_garage_is_registered_and_scrapable(cases):
    """アコーディオン式ガレージは parking_garage_list に 1 件も無いため専用エントリが要る。"""
    from src.scrape import is_list_url

    case = cases["accordion_garage_list"]
    assert "アコーディオン" in case["name"]
    assert "アコーディオン" in case["keywords"]
    # 検索結果ページなので、スクレイピング対象として認識される必要がある
    assert is_list_url(case["url"])


def test_schema_enum_matches_case_keys(cases):
    schema = build_selection_schema(cases)
    enum = schema["properties"]["selected"]["items"]["properties"]["key"]["enum"]
    assert set(enum) == set(cases.keys())


def test_validate_selection_accepts_key_reason_dicts(cases):
    result = {
        "selected": [
            {"key": "factory_jabara_permanent", "reason": "常設ジャバラのため"},
            {"key": "factory_jabara_temp", "reason": "仮設比較用"},
        ]
    }
    assert validate_selection(result, cases) == [
        "factory_jabara_permanent",
        "factory_jabara_temp",
    ]


def test_validate_selection_accepts_valid_keys(cases):
    result = {"selected": ["warehouse", "event_temporary"]}
    assert validate_selection(result, cases) == ["warehouse", "event_temporary"]


def test_validate_selection_rejects_unknown_key(cases):
    result = {"selected": ["warehouse", "fake_key_12345"]}
    with pytest.raises(ValueError):
        validate_selection(result, cases)


def test_validate_selection_dedupes_non_list_category(cases):
    """製品ページは中身が 1 件しかないので、重複させると同じ事例が 2 枚並ぶ。"""
    result = {"selected": ["warehouse", "warehouse"]}
    with pytest.raises(ValueError):
        validate_selection(result, cases)


def test_validate_selection_allows_same_list_category_twice(cases):
    """一覧カテゴリーは 2 回選べる。商材違いの事例を無理に 2 件目に出さないため。"""
    result = {"selected": ["accordion_garage_list", "accordion_garage_list"]}
    assert validate_selection(result, cases) == [
        "accordion_garage_list",
        "accordion_garage_list",
    ]


def test_validate_selection_truncates_to_two(cases):
    result = {"selected": ["warehouse", "event_temporary", "event_one_touch"]}
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
