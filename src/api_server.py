"""提案書生成 HTTP API。

2 つの使い方をひとつの FastAPI アプリで提供する。

1. ステップ実行（ブラウザ版 index.html から利用）
   /api/extract → /api/select → /api/candidates → /api/generate
   抽出内容の確認・修正、事例の選び直しを挟める。

2. 一発生成（見積検索AI からの連携で利用）
   /api/proposal に見積書を投げると提案書 pptx がそのまま返る。

中身の処理は src/headless.py（Streamlit UI と同じ流れ）に委譲する。

ローカル起動（teiansho-auto-ai ルートで、venv の python を使う）:

    .venv/bin/python -m uvicorn src.api_server:app --port 8600

Vercel では api/index.py がこの app を読み込む。
APIキーは .env か環境変数 ANTHROPIC_API_KEY から読まれる。
"""

import json
import urllib.parse

from fastapi import APIRouter, Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .headless import build, default_output_name, extract, generate_from_bytes, select
from .llm import api_key_available
from .resolve_case import category_candidates, make_resolved_from_candidate
from .select_case import load_cases

PPTX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

app = FastAPI(title="丸八 提案書生成 API", version="2.0")

# 見積検索AI はローカルでは http://localhost:<port> から配信される。
# ポートは環境により変わる（8000 等）ので localhost 全体を許可する。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
    # フロントが提案書ファイル名と選定事例メタを読めるように公開する
    expose_headers=["Content-Disposition", "X-Proposal-Meta"],
)

router = APIRouter()


def _require_api_key() -> None:
    if not api_key_available():
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY が未設定です。Vercel の環境変数（またはローカルの .env）を確認してください。",
        )


@router.get("/health")
def health() -> dict:
    """疎通確認。見積検索AI 側の起動チェックに使う。"""
    return {"status": "ok", "api_key": api_key_available()}


# ---------------------------------------------------------------- ステップ実行


@router.post("/extract")
async def api_extract(file: UploadFile = File(...)) -> dict:
    """STEP 1: 見積書ファイルから見積内容を構造化抽出する。"""
    _require_api_key()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空のファイルです。")
    try:
        return {"quote": extract(file.filename or "quote.xlsx", data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"見積書の読み取りに失敗しました: {e}")


@router.post("/select")
def api_select(quote: dict = Body(..., embed=True)) -> dict:
    """STEP 2: 見積内容から類似事例を 2 件選定し、個別事例まで解決する。"""
    _require_api_key()
    try:
        resolved, selection = select(quote)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"事例の選定に失敗しました: {e}")
    return {"resolved": resolved, "selection": selection}


@router.get("/cases")
def api_cases() -> dict:
    """選び直し用のカテゴリー一覧（cases.json のホワイトリスト）。"""
    cases = load_cases()
    return {
        "cases": [
            {"key": k, "name": v["name"], "url": v["url"], "note": v.get("note", "")}
            for k, v in cases.items()
        ]
    }


@router.get("/candidates")
def api_candidates(key: str) -> dict:
    """指定カテゴリー内の個別事例候補（実在するページのみ）を返す。"""
    cases = load_cases()
    case = cases.get(key)
    if not case:
        raise HTTPException(status_code=404, detail=f"未登録のカテゴリーです: {key}")
    try:
        candidates = category_candidates(case)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"事例候補の取得に失敗しました: {e}")
    return {"key": key, "category_name": case["name"], "candidates": candidates}


@router.post("/pick")
def api_pick(
    key: str = Body(...),
    candidate: dict = Body(...),
) -> dict:
    """選び直した事例を、提案書生成で使える形（resolved 1 件）に組み立てる。"""
    cases = load_cases()
    case = cases.get(key)
    if not case:
        raise HTTPException(status_code=404, detail=f"未登録のカテゴリーです: {key}")
    return {"resolved": make_resolved_from_candidate(key, case, candidate, manual=True)}


@router.post("/generate")
def api_generate(
    quote: dict = Body(...),
    resolved: list = Body(...),
) -> Response:
    """STEP 4: 確定した見積内容と事例から提案書 pptx を生成して返す。"""
    _require_api_key()
    try:
        pptx_bytes, proposal_text = build(quote, resolved)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"提案書の生成に失敗しました: {e}"})

    filename = default_output_name(quote)
    encoded = urllib.parse.quote(filename)
    meta = json.dumps({"proposal_text": proposal_text}, ensure_ascii=False)
    return Response(
        content=pptx_bytes,
        media_type=PPTX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "X-Proposal-Meta": urllib.parse.quote(meta),
        },
    )


# ---------------------------------------------------------------- 一発生成


def _proposal_meta(result: dict) -> dict:
    """フロント表示用の軽量メタ（顧客名・案件名・選定事例）を組み立てる。"""
    quote = result["quote"]
    cases = []
    for r in result["resolved"]:
        cases.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "reason": r.get("reason") or r.get("category_reason") or "",
            }
        )
    return {
        "customer_name": quote.get("customer_name"),
        "project_name": quote.get("project_name"),
        "industry_type": quote.get("industry_type"),
        "total_amount": quote.get("total_amount"),
        "fallback": result["selection"].get("fallback", False),
        "cases": cases,
    }


@router.post("/proposal")
async def create_proposal(file: UploadFile = File(...)) -> Response:
    """見積書ファイル（xlsx/PDF/画像）を受け取り、提案書 pptx を返す。"""
    _require_api_key()

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="空のファイルです。")

    try:
        result = generate_from_bytes(file.filename or "quote.xlsx", data)
    except Exception as e:  # 抽出・選定・生成のいずれかで失敗
        return JSONResponse(status_code=500, content={"error": f"提案書の生成に失敗しました: {e}"})

    pptx_bytes = result["pptx"]
    filename = result["filename"]
    # 日本語ファイル名は RFC 5987 の filename* でエンコードして渡す
    encoded = urllib.parse.quote(filename)
    meta = json.dumps(_proposal_meta(result), ensure_ascii=False)

    return Response(
        content=pptx_bytes,
        media_type=PPTX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
            "X-Proposal-Meta": urllib.parse.quote(meta),
        },
    )


# ルートは /api 付き・無しの両方で受ける。
# （Vercel の rewrite 経由でパスが変わっても動くようにするための保険）
app.include_router(router, prefix="/api")
app.include_router(router)


@app.get("/", include_in_schema=False)
def index() -> Response:
    """ローカル起動時に画面（index.html）を返す。

    Vercel では index.html が静的ファイルとして配信されるため、この経路は通らない。
    """
    from pathlib import Path

    html = Path(__file__).resolve().parent.parent / "index.html"
    if not html.exists():
        return JSONResponse({"status": "ok", "hint": "index.html が見つかりません"})
    return Response(content=html.read_text(encoding="utf-8"), media_type="text/html")
