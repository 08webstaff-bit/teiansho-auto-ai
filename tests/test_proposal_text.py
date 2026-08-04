"""proposal_text のフォールバック挙動の単体テスト（API はモック）。"""

import src.proposal_text as pt

QUOTE = {"customer_name": "テスト", "project_name": "荷捌き場テント新設", "industry_type": "工場", "items": []}


def test_fallback_on_api_error(monkeypatch):
    def boom():
        raise RuntimeError("no api")

    monkeypatch.setattr(pt, "get_client", boom)
    result = pt.generate_proposal_text(QUOTE, [])
    # フォールバックでも必須キーが揃い、施工イメージは2件
    assert result["concept"]
    assert len(result["solution_images"]) == 2
    # 案件名があればタイトル案に反映
    assert result["title_suggestion"] == "荷捌き場テント新設"


def test_prompt_includes_quote_and_cases():
    resolved = [{"title": "大型トラック対応テント", "category_name": "荷捌き場テント一覧"}]
    prompt = pt._build_prompt(QUOTE, resolved)
    assert "荷捌き場テント新設" in prompt
    assert "大型トラック対応テント" in prompt
