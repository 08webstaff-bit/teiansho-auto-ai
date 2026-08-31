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
from .scrape import (
    fetch_case_image_urls,
    fetch_case_list,
    fetch_page_thumbnail,
    is_list_url,
)

# 提案書の事例スライドは写真 2 枚で組む。これを下回る事例は選び直す
REQUIRED_PHOTOS = 2
# 選び直しの上限（1 回の選定で増える通信・API 呼び出しを抑える）
MAX_REPICKS = 2

SYSTEM_PROMPT = (
    "あなたは丸八テント商会のベテラン営業です。"
    "カテゴリー内の施工事例候補の中から、見積書の内容に最も近いものを 1 つ選んでください。"
    "回答は候補番号（index）と、その事例を選んだ理由（日本語1〜2文）のみです。"
)


def _build_prompt(quote: dict, category_name: str, candidates: list, similar_to: str = "") -> str:
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
        + (
            "\n\n参考事例 1 として「" + similar_to + "」を既に選んでいます。"
            "2 件目は、それと同じ商材・同じ工法の事例を選んでください。"
            "商材の違う事例を並べると提案として弱くなります。"
            if similar_to
            else ""
        )
        + "\n\nこの見積に最も近い事例を 1 つ、番号で選んでください。"
    )


def _pick_index(quote: dict, category_name: str, candidates: list, similar_to: str = "") -> dict:
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
        messages=[
            {"role": "user", "content": _build_prompt(quote, category_name, candidates, similar_to)}
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude が個別事例の選定を拒否しました。")
    import json

    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)


def resolve_individual_case(
    quote: dict, case_key: str, case: dict, exclude_urls=(), similar_to: str = ""
) -> dict:
    """1 つのカテゴリーについて、個別事例を解決して返す。

    exclude_urls に既出の事例 URL を渡すと、それらを候補から除いて選ぶ。
    同じカテゴリーが 2 回選ばれたときに同じ事例が 2 枚並ぶのを防ぐ。

    similar_to に 1 件目の事例タイトルを渡すと、それと同じ商材の事例を選ばせる。
    カテゴリーが広い（例: ガレージテントに固定式もアコーディオン式も含まれる）ため、
    2 件目が別商材にならないようにする。

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

    # 個別事例 / 製品ページはそのまま使う（スクレイピング対象外）。
    # ただしサムネイルは持たないので、ページの og:image を代表画像として補う。
    if not is_list_url(case["url"]):
        base["thumbnail"] = fetch_page_thumbnail(case["url"]) or None
        base["resolved"] = True
        return base

    candidates = [c for c in fetch_case_list(case["url"]) if c["url"] not in exclude_urls]
    if not candidates:
        # スクレイピング失敗（または候補を出し尽くした）→ カテゴリー一覧 URL のまま
        return base

    chosen, reason = _pick_with_enough_photos(quote, case["name"], candidates, similar_to)
    base.update(
        {
            "url": chosen["url"],
            "title": chosen["title"],
            "thumbnail": chosen.get("thumbnail"),
            "reason": reason,
            "is_individual": True,
            "resolved": True,
        }
    )
    return base


def _has_enough_photos(case_url: str) -> bool:
    """事例スライドを写真 2 枚で組めるか。取得に失敗したら判定せず通す。"""
    try:
        return len(fetch_case_image_urls(case_url)) >= REQUIRED_PHOTOS
    except Exception:
        return True


def _pick_with_enough_photos(quote: dict, category_name: str, candidates: list, similar_to: str):
    """写真が 2 枚以上ある事例を選ぶ。足りなければ除外して選び直す。

    戻り値は (選んだ候補, 選定理由)。
    事例ページの写真が 1 枚しかないと提案書のスライドが 1 枚組になってしまうため、
    同じカテゴリー内で写真の揃っている事例を優先する。
    選び直しても見つからない場合は、最初に選ばれた事例をそのまま使う
    （事例の適合度のほうが写真枚数より重要なので、無理に外さない）。
    """
    remaining = list(candidates)
    first = None
    for _ in range(MAX_REPICKS + 1):
        if not remaining:
            break
        try:
            picked = _pick_index(quote, category_name, remaining, similar_to=similar_to)
            idx = picked.get("index", 0)
            if not isinstance(idx, int) or idx < 0 or idx >= len(remaining):
                idx = 0
            chosen, reason = remaining[idx], picked.get("reason", "")
        except Exception:
            # 選定失敗 → 候補の先頭を使う（URL は実在するので捏造ではない）
            chosen, reason = remaining[0], ""
        if first is None:
            first = (chosen, reason)
        if _has_enough_photos(chosen["url"]):
            return chosen, reason
        remaining = [c for c in remaining if c["url"] != chosen["url"]]

    return first if first else (candidates[0], "")


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
    return [
        {
            "url": case["url"],
            "title": case["name"],
            "thumbnail": fetch_page_thumbnail(case["url"]) or None,
        }
    ]


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


def _prefer_same_category(selected: list, cases: dict) -> list:
    """1 件目のカテゴリーで 2 件まかなえるなら、2 件目も同じカテゴリーに寄せる。

    商材の違う事例が 2 件目に並ぶと提案として弱くなる
    （例: アコーディオンガレージの見積に固定式の駐車場屋根テントが付く）。
    Claude への指示だけでは別カテゴリーが混ざることがあるため、ここで確定させる。

    1 件目が一覧ページでない、または個別事例が 1 件しか取れない場合は、
    Claude が選んだ 2 件目をそのまま使う。
    """
    keys = list(selected)
    if len(keys) < 2 or keys[0] == keys[1]:
        return keys

    first = cases.get(keys[0])
    if not first or not is_list_url(first["url"]):
        return keys
    if len(fetch_case_list(first["url"])) < 2:
        return keys

    keys[1] = keys[0]
    return keys


def resolve_selection(quote: dict, selection: dict, cases: dict) -> list:
    """select_cases の結果を受け取り、各カテゴリーの個別事例を解決したリストを返す。"""
    keys = _prefer_same_category(selection.get("selected", []), cases)

    resolved = []
    used_urls = set()
    for key in keys:
        case = cases.get(key)
        if not case:
            continue
        # 2 件目以降は 1 件目と同じ商材の事例を選ばせる
        similar_to = resolved[0]["title"] if resolved and resolved[0]["is_individual"] else ""
        result = resolve_individual_case(
            quote, key, case, exclude_urls=used_urls, similar_to=similar_to
        )
        # カテゴリー選定理由（一覧レベル）も保持
        result["category_reason"] = selection.get("reasons", {}).get(key, "")
        used_urls.add(result["url"])
        resolved.append(result)
    return resolved
