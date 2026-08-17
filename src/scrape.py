"""カテゴリー一覧ページから個別施工事例（URL・タイトル・サムネ）を取得する。

08tent.co.jp の works_kw/ 一覧ページには個別事例（/works/数字/）が並んでいる。
そこから実在する個別事例だけを抜き出してキャッシュする。

重要: 個別事例の URL は必ずこのスクレイピング結果（実在するもの）からのみ扱い、
コードや AI が数字を組み立てて URL を生成することは一切しない。
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def _cache_root() -> Path:
    """キャッシュの保存先。

    Vercel などのサーバーレス環境ではプロジェクト配下が読み取り専用のため、
    書き込み可能な一時ディレクトリを使う（実行ごとに消えるが動作に支障はない）。
    """
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return Path(tempfile.gettempdir()) / "teiansho_cache"
    return Path(__file__).resolve().parent.parent / "cache"


CACHE_DIR = _cache_root()
LIST_CACHE_DIR = CACHE_DIR / "lists"
IMAGE_CACHE_DIR = CACHE_DIR / "images"


def _ensure_dir(path: Path) -> bool:
    """キャッシュ用ディレクトリを用意する。作れなければ False（キャッシュ無しで続行）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False

WORKS_RE = re.compile(r"/works/\d+/?$")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MaruhachiTeianBot/1.0)"}
CACHE_TTL_SEC = 60 * 60 * 24  # 24時間


def is_list_url(url: str) -> bool:
    """スクレイピング対象（複数の個別事例が並ぶページ）かどうか。

    対象は 2 種類:
    - カテゴリー一覧ページ（/works_kw/～）
    - 施工事例の検索結果ページ（?post_type=works&s=キーワード）
      works_kw のカテゴリーが用意されていない商材（アコーディオンガレージ等）を
      拾うために使う。どちらも中身は /works/数字/ のリンクなので同じパーサーで扱える。
    """
    if "/works_kw/" in url:
        return True
    query = parse_qs(urlparse(url).query)
    return query.get("post_type") == ["works"] and bool(query.get("s"))


def _cache_path(list_url: str) -> Path:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", list_url).strip("_")
    return LIST_CACHE_DIR / f"{slug}.json"


def fetch_case_list(list_url: str, use_cache: bool = True) -> list:
    """一覧ページから個別事例のリストを返す。

    戻り値: [{"url": ..., "title": ..., "thumbnail": ...}, ...]（重複除去済み）
    取得に失敗した場合は空リストを返す（呼び出し側でフォールバック）。
    """
    can_cache = _ensure_dir(LIST_CACHE_DIR)
    cache_file = _cache_path(list_url)

    if use_cache and can_cache and cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < CACHE_TTL_SEC:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    try:
        resp = requests.get(list_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception:
        return []

    cases = parse_case_list(resp.text, list_url)
    try:
        cache_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return cases


def parse_case_list(html: str, base_url: str) -> list:
    """一覧ページの HTML から個別事例を構造化して抜き出す。

    各事例は複数の <a>（サムネ / タイトル / 続きを読む）に分かれているので
    URL 単位でまとめ、タイトルとサムネイルを補完する。
    """
    soup = BeautifulSoup(html, "html.parser")
    by_url = {}
    order = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not WORKS_RE.search(href):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if not url.endswith("/"):
            url += "/"

        entry = by_url.setdefault(url, {"url": url, "title": "", "thumbnail": None})
        if url not in order:
            order.append(url)

        img = a.find("img")
        if img and not entry["thumbnail"]:
            src = img.get("src") or img.get("data-src")
            if src:
                entry["thumbnail"] = urljoin(base_url, src)

        text = a.get_text(strip=True)
        # カテゴリラベル・「続きを読む」以外の、最も情報量のあるテキストをタイトルに
        if text and text not in ("続きを読む", "詳しく見る") and "施設" not in text[:6]:
            if len(text) > len(entry["title"]):
                entry["title"] = text

    return [by_url[u] for u in order if by_url[u]["title"]]


def fetch_page_thumbnail(page_url: str) -> str:
    """個別事例ページ／製品ページの代表画像（og:image）を 1 枚返す。取得できなければ空文字。

    一覧ページ由来の事例はサムネイルが取れるが、cases.json に直接登録された
    /works/数字/ や /products/～ はサムネイルを持たないため、画面で写真が出ない。
    その穴を埋めるために使う。
    """
    if not page_url:
        return ""
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception:
        return ""

    og = BeautifulSoup(resp.text, "html.parser").find("meta", property="og:image")
    if og and og.get("content"):
        return urljoin(page_url, og["content"])
    return ""


def _case_number(case_url: str) -> str:
    m = re.search(r"/works/(\d+)/?", case_url)
    return m.group(1) if m else ""


def fetch_case_image_urls(case_url: str) -> list:
    """個別事例ページから施工写真 URL（メイン＋サブ）を取得する。

    - og:image をメイン写真として先頭に
    - 事例番号プレフィックス（例: 83528_）の uploads 画像をサブに
    取得失敗時は空リスト。
    """
    try:
        resp = requests.get(case_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    urls = []

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        urls.append(urljoin(case_url, og["content"]))

    num = _case_number(case_url)
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "/wp-content/uploads/" not in src or src.lower().endswith((".svg", ".png")):
            continue
        # この事例に紐づく写真のみ（番号プレフィックス）。sで終わる縮小版は本体を優先
        fname = src.rsplit("/", 1)[-1]
        if num and not fname.startswith(f"{num}_"):
            continue
        full = urljoin(case_url, src)
        # 300x225 等のサムネサイズ表記を外して原寸を狙う
        full = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", full)
        if full not in urls:
            urls.append(full)

    return urls


def fetch_case_images(case_url: str, max_images: int = 3, use_cache: bool = True) -> list:
    """個別事例ページの施工写真をローカルに保存し、ローカルパスのリストを返す。

    取得失敗時は空リスト（呼び出し側でプレースホルダーにフォールバック）。
    """
    paths = []
    for url in fetch_case_image_urls(case_url)[:max_images]:
        p = download_image(url, use_cache=use_cache)
        if p:
            paths.append(p)
    return paths


def download_image(image_url: str, use_cache: bool = True) -> str:
    """事例サムネイル/写真をローカルに保存してパスを返す。失敗時は空文字。"""
    if not image_url:
        return ""
    if not _ensure_dir(IMAGE_CACHE_DIR):
        return ""
    slug = re.sub(r"[^a-zA-Z0-9.]+", "_", image_url.rsplit("/", 1)[-1]).strip("_")
    dest = IMAGE_CACHE_DIR / slug

    if use_cache and dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        resp = requests.get(image_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return str(dest)
    except Exception:
        return ""
