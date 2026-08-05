"""Vercel のファイル単位ルーティング用。処理は src/api_server.py の FastAPI app に委譲する。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api_server import app  # noqa: E402

__all__ = ["app"]
