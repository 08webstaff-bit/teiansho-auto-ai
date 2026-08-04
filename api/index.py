"""Vercel サーバーレス関数のエントリポイント。

Vercel は api/ 配下の Python ファイルを関数として実行し、
ASGI アプリ（変数 app）を見つけるとそのまま処理を任せる。
中身は src/api_server.py のアプリをそのまま使う（ローカルの uvicorn と同一）。
"""

import os
import sys

# プロジェクトルートを import パスに追加して src/ を読み込めるようにする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api_server import app  # noqa: E402

__all__ = ["app"]
