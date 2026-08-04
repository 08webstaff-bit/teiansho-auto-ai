"""Claude API クライアントの共通設定。"""

import os

import anthropic
from dotenv import load_dotenv

MODEL = "claude-opus-4-8"

_client = None


def api_key_available() -> bool:
    load_dotenv()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def get_client() -> anthropic.Anthropic:
    """ANTHROPIC_API_KEY を .env / 環境変数から読み込んでクライアントを返す。"""
    global _client
    if _client is None:
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY が設定されていません。"
                ".env ファイルに ANTHROPIC_API_KEY=sk-ant-... を記載してください。"
            )
        _client = anthropic.Anthropic()
    return _client
