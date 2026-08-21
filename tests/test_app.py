"""Streamlit AppTest によるアプリ全体フローの結合テスト（Claude API はモック）。"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.pptx_builder as pb
import src.proposal_text as ptmod
import src.resolve_case as rc
import src.select_case as sc

APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")

SAMPLE_QUOTE = {
    "customer_name": "株式会社テスト工業",
    "project_name": "第2工場 通路テント新設工事",
    "industry_type": "工場",
    "industry_reason": "工場間通路テントの見積のため",
    "total_amount": 1650000,
    "items": [
        {
            "name": "工場間通路テント",
            "spec": "W3000×L10000 常設・レール有",
            "quantity": "1式",
            "unit_price": 1500000,
            "amount": 1500000,
        },
        {
            "name": "施工費",
            "spec": "",
            "quantity": "1式",
            "unit_price": 150000,
            "amount": 150000,
        },
    ],
}


def _make_app(quote=None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    if quote is not None:
        at.session_state["quote"] = quote
    return at


def test_app_boots_without_quote():
    at = _make_app().run()
    assert not at.exception


def test_edit_form_renders_extracted_quote():
    at = _make_app(SAMPLE_QUOTE).run()
    assert not at.exception
    assert at.text_input[0].value == "株式会社テスト工業"
    assert at.text_input[1].value == "第2工場 通路テント新設工事"
    assert at.selectbox[0].value == "工場"
    assert at.number_input[0].value == 1650000


def _patch_selection(monkeypatch, fallback=False):
    monkeypatch.setattr(
        sc,
        "select_cases",
        lambda quote, cases=None, max_retries=1: {
            "selected": ["nisabaki_tent", "jabara_tent"],
            "reasons": {
                "nisabaki_tent": "荷捌き用途に合致するため。",
                "jabara_tent": "工場内の常設ニーズに合致するため。",
            },
            "fallback": fallback,
            **({"error": "テスト用エラー"} if fallback else {}),
        },
    )

    def fake_resolve(quote, selection, cases):
        return [
            {
                "key": "nisabaki_tent",
                "category_name": "荷捌き場テント 事例一覧",
                "url": "https://08tent.co.jp/works/83528/",
                "title": "大型トラック対応・荷捌き用片持ちテント屋根",
                "thumbnail": None,
                "reason": "大型トラック対応の仕様が一致するため。",
                "is_individual": True,
                "resolved": True,
                "category_reason": "荷捌き用途に合致するため。",
            },
            {
                "key": "jabara_tent",
                "category_name": "ジャバラ（伸縮式）テント",
                "url": "https://08tent.co.jp/works/83680/",
                "title": "前面・側面カーテン式の上屋テント",
                "thumbnail": None,
                "reason": "工場内の常設ニーズに合致するため。",
                "is_individual": True,
                "resolved": True,
                "category_reason": "工場内の常設ニーズに合致するため。",
            },
        ]

    monkeypatch.setattr(rc, "resolve_selection", fake_resolve)

    # 手動選び直し UI が呼ぶ候補取得をモック（ネットワークを使わない）
    def fake_category_candidates(case):
        if "/works_kw/" in case["url"]:
            return [
                {"url": "https://08tent.co.jp/works/83528/", "title": "大型トラック対応・荷捌き用片持ちテント屋根", "thumbnail": None},
                {"url": "https://08tent.co.jp/works/83680/", "title": "前面・側面カーテン式の上屋テント", "thumbnail": None},
            ]
        return [{"url": case["url"], "title": case["name"], "thumbnail": None}]

    monkeypatch.setattr(rc, "category_candidates", fake_category_candidates)


def test_case_selection_flow_with_mocked_api(monkeypatch):
    _patch_selection(monkeypatch)
    at = _make_app(SAMPLE_QUOTE).run()
    at.button(key="btn_select").click().run()
    assert not at.exception

    page_text = " ".join(md.value for md in at.markdown)
    # 一覧ページではなく個別事例 URL が表示される
    assert "https://08tent.co.jp/works/83528/" in page_text
    assert "https://08tent.co.jp/works/83680/" in page_text
    assert "大型トラック対応・荷捌き用片持ちテント屋根" in page_text
    # 一覧 URL は最終提示に残らない
    assert "/works_kw/" not in page_text


def test_fallback_result_shows_warning(monkeypatch):
    _patch_selection(monkeypatch, fallback=True)
    at = _make_app(SAMPLE_QUOTE).run()
    at.button(key="btn_select").click().run()
    assert not at.exception
    assert len(at.warning) >= 1


def test_pptx_generation_flow(monkeypatch):
    _patch_selection(monkeypatch)
    monkeypatch.setattr(
        ptmod,
        "generate_proposal_text",
        lambda quote, resolved: {
            "title_suggestion": "荷捌き場テント新設のご提案",
            "concept": "テスト用コンセプト文。",
            "solution_images": ["イメージ1", "イメージ2"],
        },
    )
    monkeypatch.setattr(pb, "build_proposal_pptx", lambda q, r, t: b"PK\x03\x04dummy-pptx")

    at = _make_app(SAMPLE_QUOTE).run()
    at.button(key="btn_select").click().run()
    at.button(key="btn_pptx").click().run()
    assert not at.exception

    # ダウンロードボタンが表示されている
    assert len(at.get("download_button")) >= 1
    page_text = " ".join(md.value for md in at.markdown)
    assert "テスト用コンセプト文。" in page_text
