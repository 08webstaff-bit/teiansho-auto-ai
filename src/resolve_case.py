"""STEP 2b: カテゴリー一覧から、見積書に最も近い個別事例を自動選定する。

select_case.py がカテゴリー（cases.json のキー）を 2 件選ぶ。
このモジュールは、そのうち一覧ページ（works_kw/）のものについて
実際にスクレイピングし、取得した個別事例の候補の中から
見積書内容に最も近い 1 件を Claude に「番号（index）」で選ばせる。

URL 捏造防止:
- 個別事例 URL はスクレイピング結果（実在するもの）からのみ取得
- Claude には候補の index だけを answer させ、URL 文字列は生成させない
- structured outputs で index を候補数未満の integer に制限
- 不正な index が返ったら 0 件目にフォールバック
"""

from .llm import MODEL, get_client
from .scrape import fetch_case_list, is_list_url

SYSTEM_PROMPT = (
    "あなたは丸八テント商会のベテラン営業です。"
    "カテゴリー内の施工事例候補の中から、見積書の内容に最も近いものを 1 つ選んでください。"
    "回答は候補番号（index）と、その事例を選んだ理由（日本語1〜2文）のみです。"
)


def _build_prompt(quote: dict, category_name: str, candidates: list) -> str:
    item_lines = [
        f"- {it.get('name', '')} | 仕様: {it.get('spec', '')} | 数量: {it.get('quantity', '')}"
        for it in quote.get("items", [])
    ]
    cand_lines = [f"[{i}] {c['title']}" for i, c in enumerate(candidates)]
    return (
        f"## 見積内容\n"
        f"顧客名: {quote.get('customer_name', '')}\n"
        f"案件名: {quote.get('project_name', '')}\n"
        f"業種: {quote.get('industry_type', '')}\n"
        f"見積項目:\n" + ("\n".join(item_lines) or "（明細なし）") + "\n\n"
        f"## カテゴリー「{category_name}」の施工事例候補\n"
        + "\n".join(cand_lines)
        + "\n\nこの見積に最も近い事例を 1 つ、番号で選んでください。"
    )


def _pick_index(quote: dict, category_name: str, candidates: list) -> dict:
    """Claude に候補 index を選ばせる。失敗時は例外。"""
    client = get_client()
    # structured outputs は integer の minimum/maximum を未サポートのため、
    # 有効な index を enum で列挙して範囲を強制する。
    schema = {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "enum": list(range(len(candidates))),
                "description": "選んだ事例の候補番号",
            },
            "reason": {"type": "string", "description": "選定理由（日本語1〜2文）"},
        },
        "required": ["index", "reason"],
        "additionalProperties": False,
    }
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": _build_prompt(quote, category_name, candidates)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude が個別事例の選定を拒否しました。")
    import json

    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)


def resolve_individual_case(quote: dict, case_key: str, case: dict) -> dict:
    """1 つのカテゴリーについて、個別事例を解決して返す。

    戻り値: {
      "key": case_key,
      "category_name": <カテゴリー名>,
      "url": <最終的に提示する URL>,
      "title": <事例タイトル（一覧なら個別事例名、そうでなければカテゴリー名）>,
      "thumbnail": <サムネ URL or None>,
      "reason": <個別選定理由 or "">,
      "is_individual": <個別事例まで絞れたか>,
      "resolved": <スクレイピング＆選定に成功したか>,
    }
    """
    base = {
        "key": case_key,
        "category_name": case["name"],
        "url": case["url"],
        "title": case["name"],
        "thumbnail": None,
        "reason": "",
        "is_individual": False,
        "resolved": False,
    }

    # 個別事例 / 製品ページはそのまま使う（スクレイピング対象外）
    if not is_list_url(case["url"]):
        base["resolved"] = True
        return base

    candidates = fetch_case_list(case["url"])
    if not candidates:
        # スクレイピング失敗 → カテゴリー一覧 URL のままフォールバック
        return base

    try:
        picked = _pick_index(quote, case["name"], candidates)
        idx = picked.get("index", 0)
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
            idx = 0
        chosen = candidates[idx]
        base.update(
            {
                "url": chosen["url"],
                "title": chosen["title"],
                "thumbnail": chosen.get("thumbnail"),
                "reason": picked.get("reason", ""),
                "is_individual": True,
                "resolved": True,
            }
        )
    except Exception:
        # 選定失敗 → 候補の先頭を使う（URL は実在するので捏造ではない）
        chosen = candidates[0]
        base.update(
            {
                "url": chosen["url"],
                "title": chosen["title"],
                "thumbnail": chosen.get("thumbnail"),
                "is_individual": True,
                "resolved": True,
            }
        )
    return base


def category_candidates(case: dict) -> list:
    """カテゴリー（cases.json の1件）から手動選択できる個別事例候補を返す。

    - works_kw 一覧ページ: スクレイピング結果（個別事例のリスト）
    - 個別事例 / 製品ページ: そのページ自身を1件として返す
    取得失敗時は一覧ページ自身を1件返す。
    """
    if is_list_url(case["url"]):
        cands = fetch_case_list(case["url"])
        if cands:
            return cands
        return [{"url": case["url"], "title": f"{case['name']}（一覧ページ）", "thumbnail": None}]
    return [{"url": case["url"], "title": case["name"], "thumbnail": None}]


def make_resolved_from_candidate(case_key: str, case: dict, candidate: dict, manual: bool = True) -> dict:
    """カテゴリーと候補から resolved 形式の1件を組み立てる（手動選択用）。"""
    is_list = is_list_url(case["url"])
    return {
        "key": case_key,
        "category_name": case["name"],
        "url": candidate["url"],
        "title": candidate["title"],
        "thumbnail": candidate.get("thumbnail"),
        "reason": "（営業担当が手動で選択）" if manual else "",
        "is_individual": is_list,
        "resolved": True,
        "category_reason": "",
    }


def resolve_selection(quote: dict, selection: dict, cases: dict) -> list:
    """select_cases の結果を受け取り、各カテゴリーの個別事例を解決したリストを返す。"""
    resolved = []
    for key in selection.get("selected", []):
        case = cases.get(key)
        if not case:
            continue
        result = resolve_individual_case(quote, key, case)
        # カテゴリー選定理由（一覧レベル）も保持
        result["category_reason"] = selection.get("reasons", {}).get(key, "")
        resolved.append(result)
    return resolved
