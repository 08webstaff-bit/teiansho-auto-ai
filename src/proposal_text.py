"""提案スライド用のテキスト（コンセプト文・解決策イメージ）を Claude で生成する。"""

import json

from .llm import MODEL, get_client

SYSTEM_PROMPT = (
    "あなたはテント・膜構造メーカー「丸八テント商会」のベテラン提案営業です。"
    "見積内容と選定した類似事例をもとに、顧客向け提案書のテキストを作成します。"
    "誇張や事実にない実績は書かず、丸八テント商会の強み（自社施工・膜構造の専門性・"
    "オーダーメイド対応）を踏まえた、落ち着いた提案調の日本語で書いてください。"
)

SCHEMA = {
    "type": "object",
    "properties": {
        "title_suggestion": {
            "type": "string",
            "description": "提案書の案件タイトル案（20文字程度、簡潔に）",
        },
        "concept": {
            "type": "string",
            "description": "提案コンセプト文。顧客の課題→丸八の解決アプローチの流れで300文字程度。",
        },
        "solution_images": {
            "type": "array",
            "description": "施工イメージ案を2つ。各50文字程度の箇条書き。",
            "items": {"type": "string"},
        },
    },
    "required": ["title_suggestion", "concept", "solution_images"],
    "additionalProperties": False,
}

FALLBACK = {
    "title_suggestion": "ご提案書",
    "concept": (
        "この度はお見積のご依頼をいただき誠にありがとうございます。"
        "丸八テント商会は自社施工による膜構造・テントの専門メーカーとして、"
        "お客様の課題に合わせた最適なご提案を行ってまいります。"
        "本案件につきましても、現地状況とご要望を踏まえ、耐久性と使い勝手を"
        "両立した施工をご提案いたします。"
    ),
    "solution_images": [
        "ご要望に合わせたオーダーメイド設計での施工イメージ",
        "メンテナンス性と耐久性を考慮した仕様のご提案",
    ],
}


def _build_prompt(quote: dict, resolved_cases: list) -> str:
    item_lines = [
        f"- {it.get('name', '')} | 仕様: {it.get('spec', '')} | 数量: {it.get('quantity', '')}"
        for it in quote.get("items", [])
    ]
    case_lines = [
        f"- {c.get('title', '')}（{c.get('category_name', '')}）" for c in resolved_cases
    ]
    return (
        "## 見積内容\n"
        f"顧客名: {quote.get('customer_name', '')}\n"
        f"案件名: {quote.get('project_name', '')}\n"
        f"業種・施設タイプ: {quote.get('industry_type', '')}\n"
        f"見積項目:\n" + ("\n".join(item_lines) or "（明細なし）") + "\n"
        f"合計金額: {quote.get('total_amount') or '（未記入）'}\n\n"
        "## 選定した類似事例\n" + ("\n".join(case_lines) or "（なし）") + "\n\n"
        "この案件の提案書テキスト（タイトル案・コンセプト文・施工イメージ案2つ）を作成してください。"
    )


def generate_proposal_text(quote: dict, resolved_cases: list) -> dict:
    """コンセプト文などを生成。API 失敗時は無難なフォールバック文を返す。"""
    try:
        client = get_client()
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": _build_prompt(quote, resolved_cases)}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("refusal")
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        # 施工イメージが2つ未満なら補完
        imgs = data.get("solution_images") or []
        while len(imgs) < 2:
            imgs.append(FALLBACK["solution_images"][len(imgs)])
        data["solution_images"] = imgs[:2]
        return data
    except Exception:
        result = dict(FALLBACK)
        if quote.get("project_name"):
            result["title_suggestion"] = quote["project_name"]
        return result
