"""resolve_case の個別事例解決ロジックの単体テスト（スクレイピング・API はモック）。"""

import pytest

import src.resolve_case as rc

QUOTE = {"customer_name": "テスト", "project_name": "荷捌き場テント", "industry_type": "工場", "items": []}

CANDIDATES = [
    {"url": "https://08tent.co.jp/works/83680/", "title": "上屋テント（片持ち屋根）", "thumbnail": "https://08tent.co.jp/a.jpg"},
    {"url": "https://08tent.co.jp/works/83528/", "title": "大型トラック対応 片持ちテント屋根", "thumbnail": "https://08tent.co.jp/b.jpg"},
]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """画像取得は既定でモックし、テストがネットワークに出ないようにする。"""
    monkeypatch.setattr(rc, "fetch_page_thumbnail", lambda url: "")
    # 既定では「写真は足りている」ことにして、選び直しを起こさない
    monkeypatch.setattr(rc, "fetch_case_image_urls", lambda url: ["a.jpg", "b.jpg"])


def test_non_list_case_used_as_is(monkeypatch):
    # 個別事例 URL（works/数字）はスクレイピングせずそのまま使う
    case = {"name": "工場間通路テント（常設）", "url": "https://08tent.co.jp/works/58612/"}
    result = rc.resolve_individual_case(QUOTE, "jabara_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/58612/"
    assert result["is_individual"] is False
    assert result["resolved"] is True


def test_products_page_used_as_is():
    case = {"name": "イベント用テント", "url": "https://08tent.co.jp/products/temporary-tent/"}
    result = rc.resolve_individual_case(QUOTE, "event_temporary", case)
    assert result["url"] == "https://08tent.co.jp/products/temporary-tent/"
    assert result["is_individual"] is False


def test_non_list_case_gets_thumbnail_from_og_image(monkeypatch):
    """一覧ページ以外はサムネイルを持たないので og:image で補う（画面で写真が出るように）。"""
    monkeypatch.setattr(rc, "fetch_page_thumbnail", lambda url: "https://08tent.co.jp/og.jpg")
    case = {"name": "ファーラー（巻取り式）", "url": "https://08tent.co.jp/works/41672/"}
    result = rc.resolve_individual_case(QUOTE, "awning", case)
    assert result["thumbnail"] == "https://08tent.co.jp/og.jpg"


def test_non_list_case_thumbnail_none_when_og_image_missing():
    """og:image が取れなくても処理は止めず、サムネイル無しで続行する。"""
    case = {"name": "ファーラー（巻取り式）", "url": "https://08tent.co.jp/works/41672/"}
    result = rc.resolve_individual_case(QUOTE, "awning", case)
    assert result["thumbnail"] is None
    assert result["resolved"] is True


def test_list_case_resolves_to_scraped_individual(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(
        rc, "_pick_index", lambda q, name, c, **kw: {"index": 1, "reason": "大型トラック対応のため"}
    )
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/83528/"  # index 1
    assert result["is_individual"] is True
    assert result["reason"] == "大型トラック対応のため"
    assert result["thumbnail"] == "https://08tent.co.jp/b.jpg"


def test_list_case_scrape_failure_falls_back_to_category(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: [])
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works_kw/nisabaki-tent/"
    assert result["is_individual"] is False


def test_invalid_index_from_api_falls_back_to_first(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 99, "reason": "x"})
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/83680/"  # index 0 に補正


def test_api_error_falls_back_to_first_candidate(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("API error")

    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", boom)
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/83680/"
    assert result["is_individual"] is True


def test_exclude_urls_skips_already_used_case(monkeypatch):
    """既出の事例は候補から外す（同じカテゴリーを 2 回選んだとき用）。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    # index 0 を選ぶ AI でも、除外済みなら残りから選ばれる
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "残りから"})
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(
        QUOTE, "nisabaki_tent", case, exclude_urls={"https://08tent.co.jp/works/83680/"}
    )
    assert result["url"] == "https://08tent.co.jp/works/83528/"


def test_same_category_twice_resolves_to_different_cases(monkeypatch):
    """同じカテゴリーが 2 回選ばれても、別々の事例になる。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    cases = {"nisabaki_tent": {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}}
    selection = {"selected": ["nisabaki_tent", "nisabaki_tent"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert len(resolved) == 2
    assert resolved[0]["url"] != resolved[1]["url"]
    assert resolved[0]["category_name"] == resolved[1]["category_name"]


def test_same_category_twice_with_only_one_candidate(monkeypatch):
    """候補を出し尽くしたら 2 件目は一覧ページにフォールバックする（重複させない）。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES[:1])
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    cases = {"nisabaki_tent": {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}}
    selection = {"selected": ["nisabaki_tent", "nisabaki_tent"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert resolved[0]["url"] == "https://08tent.co.jp/works/83680/"
    assert resolved[1]["url"] == "https://08tent.co.jp/works_kw/nisabaki-tent/"
    assert resolved[1]["is_individual"] is False


def test_second_category_is_pulled_into_the_first(monkeypatch):
    """1 件目のカテゴリーで 2 件まかなえるなら、商材違いの 2 件目は採用しない。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    cases = {
        "garage_tent": {"name": "ガレージテント", "url": "https://08tent.co.jp/works_kw/parking-garage/"},
        "hisashi_tent": {"name": "庇テント・軒先テント", "url": "https://08tent.co.jp/works_kw/hisashi-tent/"},
    }
    selection = {"selected": ["garage_tent", "hisashi_tent"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert [r["key"] for r in resolved] == ["garage_tent", "garage_tent"]
    assert resolved[0]["url"] != resolved[1]["url"]


def test_second_category_kept_when_first_has_only_one_case(monkeypatch):
    """1 件目が 1 件しか出せないときは、Claude が選んだ 2 件目をそのまま使う。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES[:1])
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    cases = {
        "kaihei_tent": {"name": "開閉式テント 事例一覧", "url": "https://08tent.co.jp/works_kw/kaihei-tent/"},
        "awning": {"name": "オーニング 事例一覧", "url": "https://08tent.co.jp/works_kw/awning-tent/"},
    }
    selection = {"selected": ["kaihei_tent", "awning"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert [r["key"] for r in resolved] == ["kaihei_tent", "awning"]


def test_second_category_kept_when_first_is_not_a_list(monkeypatch):
    """1 件目が一覧ページでないなら中身が 1 件なので、2 件目はそのまま残す。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    cases = {
        "solo_page": {"name": "単独の施工事例ページ", "url": "https://08tent.co.jp/works/58612/"},
        "tent_souko": {"name": "テント倉庫 事例一覧", "url": "https://08tent.co.jp/works_kw/tent-souko/"},
    }
    selection = {"selected": ["solo_page", "tent_souko"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert [r["key"] for r in resolved] == ["solo_page", "tent_souko"]


def test_category_candidates_for_list(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    case = {"name": "荷捌き場テント一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    cands = rc.category_candidates(case)
    assert len(cands) == 2
    assert cands[0]["url"] == "https://08tent.co.jp/works/83680/"


def test_category_candidates_for_individual_page(monkeypatch):
    monkeypatch.setattr(rc, "fetch_page_thumbnail", lambda url: "https://08tent.co.jp/og.jpg")
    case = {"name": "工場間通路テント", "url": "https://08tent.co.jp/works/58612/"}
    cands = rc.category_candidates(case)
    assert len(cands) == 1
    assert cands[0]["url"] == "https://08tent.co.jp/works/58612/"
    # 選び直しの候補にも写真が付く
    assert cands[0]["thumbnail"] == "https://08tent.co.jp/og.jpg"


def test_category_candidates_scrape_failure_returns_list_page(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: [])
    case = {"name": "荷捌き場テント一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    cands = rc.category_candidates(case)
    assert len(cands) == 1
    assert cands[0]["url"] == "https://08tent.co.jp/works_kw/nisabaki-tent/"


def test_make_resolved_from_candidate_manual():
    case = {"name": "荷捌き場テント一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    r = rc.make_resolved_from_candidate("nisabaki_tent", case, CANDIDATES[1], manual=True)
    assert r["url"] == "https://08tent.co.jp/works/83528/"
    assert r["is_individual"] is True
    assert "手動" in r["reason"]


def test_make_resolved_from_candidate_individual_page():
    case = {"name": "工場間通路テント", "url": "https://08tent.co.jp/works/58612/"}
    cand = {"url": "https://08tent.co.jp/works/58612/", "title": "工場間通路テント", "thumbnail": None}
    r = rc.make_resolved_from_candidate("jabara_tent", case, cand)
    assert r["is_individual"] is False


def test_resolve_selection_all_urls_are_real(monkeypatch):
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "r"})
    cases = {
        "nisabaki_tent": {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"},
        "jabara_tent": {"name": "工場間通路テント", "url": "https://08tent.co.jp/works/58612/"},
    }
    selection = {"selected": ["nisabaki_tent", "jabara_tent"], "reasons": {}}
    resolved = rc.resolve_selection(QUOTE, selection, cases)
    assert len(resolved) == 2
    for r in resolved:
        assert r["url"].startswith("https://08tent.co.jp/")
        assert "/works_kw/" not in r["url"]  # 一覧 URL は最終提示に残らない


def test_second_case_is_told_to_match_the_first(monkeypatch):
    """カテゴリーが広いので、2 件目には 1 件目と同じ商材を選ぶよう指示する。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    seen = []

    def spy(quote, name, cands, similar_to=""):
        seen.append(similar_to)
        return {"index": 0, "reason": "最も近い"}

    monkeypatch.setattr(rc, "_pick_index", spy)
    cases = {"garage_tent": {"name": "ガレージテント", "url": "https://08tent.co.jp/works_kw/parking-garage/"}}
    selection = {"selected": ["garage_tent", "garage_tent"], "reasons": {}}
    rc.resolve_selection(QUOTE, selection, cases)
    assert seen[0] == ""                       # 1 件目は指示なし
    assert seen[1] == CANDIDATES[0]["title"]   # 2 件目は 1 件目のタイトルを渡す


def test_similar_to_appears_in_the_prompt():
    prompt = rc._build_prompt(QUOTE, "ガレージテント", CANDIDATES, similar_to="アコーディオンガレージを個人邸に新設")
    assert "アコーディオンガレージを個人邸に新設" in prompt
    assert "同じ商材" in prompt


def test_prompt_has_no_similarity_note_for_the_first_case():
    prompt = rc._build_prompt(QUOTE, "ガレージテント", CANDIDATES)
    assert "参考事例 1 として" not in prompt


def test_repicks_when_the_case_has_only_one_photo(monkeypatch):
    """写真が 1 枚しかない事例は、提案書が 1 枚組になるので選び直す。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    photos = {
        "https://08tent.co.jp/works/83680/": ["only.jpg"],          # 1 枚だけ
        "https://08tent.co.jp/works/83528/": ["a.jpg", "b.jpg"],    # 2 枚ある
    }
    monkeypatch.setattr(rc, "fetch_case_image_urls", lambda url: photos[url])
    # AI は常に先頭を選ぶ。1 回目は 83680、除外後の 2 回目は 83528 になる
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/83528/"


def test_keeps_the_best_case_when_no_candidate_has_two_photos(monkeypatch):
    """どれも写真 1 枚なら、事例の適合度を優先して最初の選択を残す。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)
    monkeypatch.setattr(rc, "fetch_case_image_urls", lambda url: ["only.jpg"])
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 0, "reason": "最も近い"})
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/83680/"  # 1 回目の選択
    assert result["reason"] == "最も近い"


def test_photo_check_failure_does_not_block(monkeypatch):
    """写真の確認に失敗しても選定は止めない。"""
    monkeypatch.setattr(rc, "fetch_case_list", lambda url: CANDIDATES)

    def boom(url):
        raise RuntimeError("network error")

    monkeypatch.setattr(rc, "fetch_case_image_urls", boom)
    monkeypatch.setattr(rc, "_pick_index", lambda q, name, c, **kw: {"index": 1, "reason": "最も近い"})
    case = {"name": "荷捌き場テント 事例一覧", "url": "https://08tent.co.jp/works_kw/nisabaki-tent/"}
    result = rc.resolve_individual_case(QUOTE, "nisabaki_tent", case)
    assert result["url"] == "https://08tent.co.jp/works/83528/"
