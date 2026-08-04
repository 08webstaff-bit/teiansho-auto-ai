"""STEP 1: 見積書（PDF / Excel / 画像）から Claude API で項目を構造化抽出する。"""

import base64
import io
import json
from typing import Optional

from .llm import MODEL, get_client

INDUSTRY_TYPES = ["工場", "商業施設", "教育施設", "イベント", "倉庫・物流", "その他"]

# structured outputs で JSON スキーマを強制するため、抽出結果は必ずこの形で返る
QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "customer_name": {
            "type": "string",
            "description": "顧客名（会社名・施設名）。不明なら空文字。",
        },
        "project_name": {
            "type": "string",
            "description": "案件名・工事名。不明なら空文字。",
        },
        "items": {
            "type": "array",
            "description": "見積の明細行。読み取れた行のみ。",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "品名"},
                    "spec": {"type": "string", "description": "仕様・規格。無ければ空文字。"},
                    "quantity": {"type": "string", "description": "数量（単位込みで可。例: 1式, 2張）。不明なら空文字。"},
                    "unit_price": {
                        "anyOf": [{"type": "number"}, {"type": "null"}],
                        "description": "単価（円）。不明なら null。",
                    },
                    "amount": {
                        "anyOf": [{"type": "number"}, {"type": "null"}],
                        "description": "金額（円）。不明なら null。",
                    },
                },
                "required": ["name", "spec", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        },
        "total_amount": {
            "anyOf": [{"type": "number"}, {"type": "null"}],
            "description": "合計金額（税抜。判別できる方を優先し、税込しか無ければ税込）。不明なら null。",
        },
        "industry_type": {
            "type": "string",
            "enum": INDUSTRY_TYPES,
            "description": "顧客の業種・施設タイプの推定。",
        },
        "industry_reason": {
            "type": "string",
            "description": "業種推定の根拠（1文）。",
        },
    },
    "required": [
        "customer_name",
        "project_name",
        "items",
        "total_amount",
        "industry_type",
        "industry_reason",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "あなたはテント・膜構造メーカー「丸八テント商会」の営業事務のベテランです。"
    "渡された見積書から情報を正確に抽出してください。"
    "読み取れない項目は空文字または null にし、推測で数値を埋めないでください。"
    "金額のカンマや「¥」「円」は取り除き、数値として返してください。"
)

EMPTY_QUOTE = {
    "customer_name": "",
    "project_name": "",
    "items": [],
    "total_amount": None,
    "industry_type": "その他",
    "industry_reason": "",
}


def extract_excel_text(data: bytes) -> str:
    """openpyxl で Excel の全セルをタブ区切りテキスト化する。"""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    lines = []
    for ws in wb.worksheets:
        lines.append(f"=== シート: {ws.title} ===")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(c.strip() for c in cells):
                lines.append("\t".join(cells).rstrip())
    return "\n".join(lines)


def extract_pdf_text(data: bytes) -> str:
    """pdfplumber で PDF のテキストを補助的に抽出する（失敗しても空文字を返す）。"""
    try:
        import pdfplumber

        texts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                texts.append(page.extract_text() or "")
        return "\n".join(texts).strip()
    except Exception:
        return ""


def _build_content_blocks(filename: str, data: bytes) -> list:
    """ファイル種別に応じて Claude に渡す content ブロックを組み立てる。"""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    instruction = {
        "type": "text",
        "text": "この見積書から情報を抽出してください。",
    }

    if ext == "pdf":
        blocks = [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(data).decode(),
                },
            }
        ]
        aux_text = extract_pdf_text(data)
        if aux_text:
            blocks.append(
                {
                    "type": "text",
                    "text": f"参考: PDF から機械抽出したテキスト:\n{aux_text[:8000]}",
                }
            )
        blocks.append(instruction)
        return blocks

    if ext in ("jpg", "jpeg", "png"):
        media_type = "image/png" if ext == "png" else "image/jpeg"
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(data).decode(),
                },
            },
            instruction,
        ]

    if ext in ("xlsx", "xlsm", "xls"):
        text = extract_excel_text(data)
        return [
            {"type": "text", "text": f"以下は Excel 見積書の内容です:\n{text[:30000]}"},
            instruction,
        ]

    raise ValueError(f"未対応のファイル形式です: .{ext}（PDF / Excel / JPG / PNG に対応）")


def normalize_quote(quote: dict) -> dict:
    """抽出結果に欠けがあっても画面表示できるよう補完する（エラーで止めない）。"""
    result = dict(EMPTY_QUOTE)
    result.update({k: v for k, v in (quote or {}).items() if v is not None or k in ("total_amount",)})
    if result.get("industry_type") not in INDUSTRY_TYPES:
        result["industry_type"] = "その他"
    items = []
    for item in result.get("items") or []:
        items.append(
            {
                "name": str(item.get("name") or ""),
                "spec": str(item.get("spec") or ""),
                "quantity": str(item.get("quantity") or ""),
                "unit_price": item.get("unit_price"),
                "amount": item.get("amount"),
            }
        )
    result["items"] = items
    return result


def extract_quote(filename: str, data: bytes) -> dict:
    """見積書ファイルを Claude API で解析し、正規化済みの dict を返す。"""
    client = get_client()
    content = _build_content_blocks(filename, data)

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": QUOTE_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude がこのファイルの処理を拒否しました。内容をご確認ください。")

    text = next((b.text for b in response.content if b.type == "text"), "")
    return normalize_quote(json.loads(text))
