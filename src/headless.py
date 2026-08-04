"""Streamlit UI を介さず、見積書から提案書までを一気通貫で処理するオーケストレーション層。

CLI（スキルの pipeline.py）と HTTP API（api_server.py）の両方から使う「単一の入口」。
app.py の STEP1〜4 と同じ流れを、UI 抜きの純粋関数として組み立てているだけ。
"""

import re

from .extract import extract_quote
from .pptx_builder import build_proposal_pptx
from .proposal_text import generate_proposal_text
from .resolve_case import resolve_selection
from .select_case import load_cases, select_cases


def sanitize_filename(name: str) -> str:
    """ファイル名に使えない文字を除去する。空なら『無題』。"""
    return re.sub(r'[\\/:*?"<>|]', "", name or "").strip() or "無題"


def extract(filename: str, data: bytes) -> dict:
    """見積書ファイル（xlsx/PDF/画像）を構造化見積データに変換する。"""
    return extract_quote(filename, data)


def select(quote: dict) -> tuple[list, dict]:
    """見積内容から類似事例を 2 件選定し、個別事例まで解決したリストを返す。

    戻り値は (resolved, selection)。selection には fallback フラグ等が入る。
    """
    cases = load_cases()
    selection = select_cases(quote, cases)
    resolved = resolve_selection(quote, selection, cases)
    return resolved, selection


def build(quote: dict, resolved: list, output=None) -> tuple:
    """提案コンセプト文を生成し、提案書 pptx を作る。

    output が None なら pptx を bytes で、パスなら保存してパスを返す。
    戻り値は (pptx_bytes_or_path, proposal_text)。
    """
    proposal_text = generate_proposal_text(quote, resolved)
    result = build_proposal_pptx(quote, resolved, proposal_text, output=output)
    return result, proposal_text


def default_output_name(quote: dict) -> str:
    """『提案書_顧客名_案件名.pptx』形式のファイル名を組み立てる。"""
    customer = sanitize_filename(quote.get("customer_name"))
    project = sanitize_filename(quote.get("project_name"))
    return f"提案書_{customer}_{project}.pptx"


def generate_from_bytes(filename: str, data: bytes, output=None) -> dict:
    """見積書ファイルのバイト列から、抽出→事例選定→提案書生成まで一気に行う。

    返り値:
      {
        "quote": 抽出した見積データ,
        "resolved": 選定・解決した事例リスト,
        "selection": 事例選定の生結果（fallback フラグ等）,
        "proposal_text": 生成した提案コンセプト等,
        "pptx": output=None なら pptx の bytes、そうでなければ保存パス,
        "filename": 推奨ファイル名（提案書_顧客名_案件名.pptx）,
      }
    """
    quote = extract(filename, data)
    resolved, selection = select(quote)
    pptx_result, proposal_text = build(quote, resolved, output=output)
    return {
        "quote": quote,
        "resolved": resolved,
        "selection": selection,
        "proposal_text": proposal_text,
        "pptx": pptx_result,
        "filename": default_output_name(quote),
    }
