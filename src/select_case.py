"""STEP 2: 見積内容から cases.json のホワイトリスト内の事例キーを 2 件選定する。

URL 捏造対策の 3 段構え:
1. Claude には cases.json の「キー」だけを回答させる（URL 文字列は一切生成させない）
2. structured outputs のスキーマで selected を enum（キー一覧）に制限 → API レベルで
   ホワイトリスト外の文字列は返せない
3. さらにコード側でバリデーションし、不正キーはリトライ → 失敗時はカテゴリ別
   デフォルトキーにフォールバック
"""

import json
from pathlib import Path

from .llm import MODEL, get_client

CASES_PATH = Path(__file__).resolve().parent.parent / "data" / "cases.json"

# 業種・施設タイプ別のフォールバック用デフォルトキー（cases.json のキーのみ）
CATEGORY_DEFAULTS = {
    "工場": ["factory_passage_permanent", "factory_jabara_permanent"],
    "商業施設": ["commercial_updown_shade", "commercial_w_awning"],
    "教育施設": ["school_shade_garden", "school_shade_pool"],
    "イベント": ["event_temporary", "event_one_touch"],
    "倉庫・物流": ["warehouse", "factory_passage_permanent"],
    "その他": ["event_temporary", "warehouse"],
}

SYSTEM_PROMPT = (
    "あなたは丸八テント商会のベテラン営業兼プランナーです。"
    "見積内容を分析し、提示された事例キー一覧の中から最適な事例キーを 2 つ選んでください。"
    "キー以外の文字列や URL は絶対に出力しないでください。"
    "ぴったり該当する事例がない場合は、カテゴリの近い products ページのキーを選んでください。"
    "各キーの選定理由は、営業担当が顧客に説明できるよう日本語 1〜2 文で書いてください。"
)


def load_cases() -> dict:
    with open(CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


def build_selection_schema(cases: dict) -> dict:
    """key の値を cases.json のキーの enum に固定したスキーマを作る。

    ※ reasons をキー別の個別プロパティにするとスキーマが複雑になりすぎて
    API に 400 (Schema is too complex) で拒否されるため、{key, reason} の
    配列というフラットな形にしている。
    """
    keys = sorted(cases.keys())
    return {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "description": "選定した事例（必ず2件）",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "enum": keys,
                            "description": "事例キー（一覧にあるもののみ）",
                        },
                        "reason": {
                            "type": "string",
                            "description": "この事例を選んだ理由（日本語1〜2文）",
                        },
                    },
                    "required": ["key", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["selected"],
        "additionalProperties": False,
    }


def _build_user_prompt(quote: dict, cases: dict) -> str:
    case_lines = []
    for key, case in cases.items():
        line = f"- {key}: {case['name']} / キーワード: {', '.join(case.get('keywords', []))}"
        if case.get("note"):
            line += f" / 備考: {case['note']}"
        case_lines.append(line)

    item_lines = []
    for item in quote.get("items", []):
        item_lines.append(
            f"- {item.get('name', '')} | 仕様: {item.get('spec', '')} | 数量: {item.get('quantity', '')}"
        )

    return (
        "## 見積内容\n"
        f"顧客名: {quote.get('customer_name', '')}\n"
        f"案件名: {quote.get('project_name', '')}\n"
        f"業種・施設タイプ（推定）: {quote.get('industry_type', '')}\n"
        f"見積項目:\n" + ("\n".join(item_lines) or "（明細なし）") + "\n\n"
        "## 事例キー一覧\n" + "\n".join(case_lines) + "\n\n"
        "この見積に最も合う事例キーを 2 つ選び、それぞれの選定理由を書いてください。"
    )


def validate_selection(result: dict, cases: dict) -> list:
    """選定結果を検証し、有効なキーのリスト（重複除去）を返す。2 件未満なら ValueError。

    result["selected"] はキー文字列のリスト、または {key, reason} の dict の
    リストのどちらでも受け付ける。
    """
    selected = result.get("selected") or []
    valid = []
    for entry in selected:
        key = entry.get("key") if isinstance(entry, dict) else entry
        if key in cases and key not in valid:
            valid.append(key)
    if len(valid) < 2:
        raise ValueError(f"有効な事例キーが 2 件選定されませんでした: {selected}")
    return valid[:2]


def fallback_selection(quote: dict, cases: dict) -> dict:
    """API 選定に失敗した場合、業種別デフォルトキーで結果を組み立てる。"""
    industry = quote.get("industry_type", "その他")
    keys = CATEGORY_DEFAULTS.get(industry, CATEGORY_DEFAULTS["その他"])
    keys = [k for k in keys if k in cases][:2]
    return {
        "selected": keys,
        "reasons": {k: f"{industry}向けの標準事例として選定（自動フォールバック）" for k in keys},
        "fallback": True,
    }


def _call_claude(quote: dict, cases: dict) -> dict:
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": build_selection_schema(cases)}},
        messages=[{"role": "user", "content": _build_user_prompt(quote, cases)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude が事例選定を拒否しました。")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text)


def select_cases(quote: dict, cases: dict = None, max_retries: int = 1) -> dict:
    """事例を 2 件選定して返す。

    戻り値: {"selected": [key1, key2], "reasons": {key: 理由}, "fallback": bool}
    """
    if cases is None:
        cases = load_cases()

    last_error = None
    for _ in range(max_retries + 1):
        try:
            result = _call_claude(quote, cases)
            valid_keys = validate_selection(result, cases)
            reasons = {}
            for entry in result.get("selected") or []:
                if isinstance(entry, dict) and entry.get("key") in valid_keys:
                    reasons[entry["key"]] = entry.get("reason", "")
            return {
                "selected": valid_keys,
                "reasons": {k: reasons.get(k, "") for k in valid_keys},
                "fallback": False,
            }
        except Exception as e:  # バリデーション失敗・API エラーはリトライ
            last_error = e

    result = fallback_selection(quote, cases)
    result["error"] = str(last_error)
    return result
