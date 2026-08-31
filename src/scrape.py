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
from concurrent.futures import ThreadPoolExecutor
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
LIST_MAX_PAGES = 12  # 一覧ページを辿る上限（現状の最大は 9 ページ）
LIST_FETCH_WORKERS = 6  # ページ取得の並列数（Vercel の 60 秒上限に収めるため）
PAGE_LINK_RE = re.compile(r"/page/(\d+)/")


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


def page_url(list_url: str, page: int) -> str:
    """一覧ページの N ページ目の URL を組み立てる。

    カテゴリー一覧は /works_kw/slug/page/2/、検索結果は &paged=2 形式。
    ここで作るのは一覧ページの URL だけで、個別事例 URL は組み立てない
    （個別事例 URL は必ずページ内のリンクから取る）。
    """
    if page <= 1:
        return list_url
    if "/works_kw/" in list_url:
        base = list_url if list_url.endswith("/") else list_url + "/"
        return f"{base}page/{page}/"
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}paged={page}"


def _get_html(url: str):
    """ページ HTML を返す。取得できなければ None（最終ページの次は 404 になる）。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception:
        return None
    return resp.text


def _last_page(html: str) -> int:
    """一覧ページ内のページ送りリンクから最終ページ番号を読む。無ければ 1。"""
    nums = [int(n) for n in PAGE_LINK_RE.findall(html)]
    return min(max(nums), LIST_MAX_PAGES) if nums else 1


def _fetch_all_pages(list_url: str) -> list:
    """一覧の全ページから個別事例を集める（重複除去・ページ順）。

    カテゴリー一覧は最終ページ番号が HTML から分かるので、2 ページ目以降は
    並列に取得する（逐次だと 9 ページで 25 秒近くかかり、Vercel の
    60 秒上限に対して余裕がなくなるため）。
    """
    first = _get_html(page_url(list_url, 1))
    if first is None:
        return []

    cases = parse_case_list(first, list_url)
    seen = {c["url"] for c in cases}

    last = _last_page(first) if "/works_kw/" in list_url else 1
    if last > 1:
        pages = list(range(2, last + 1))
        with ThreadPoolExecutor(max_workers=LIST_FETCH_WORKERS) as pool:
            htmls = list(pool.map(lambda p: _get_html(page_url(list_url, p)), pages))
        for page, html in zip(pages, htmls):
            if not html:
                continue
            for case in parse_case_list(html, page_url(list_url, page)):
                if case["url"] not in seen:
                    seen.add(case["url"])
                    cases.append(case)
        return cases

    # ページ番号が読めない形式（検索結果など）は、新着が無くなるまで逐次で辿る
    for page in range(2, LIST_MAX_PAGES + 1):
        url = page_url(list_url, page)
        html = _get_html(url)
        if not html:
            break
        added = [c for c in parse_case_list(html, url) if c["url"] not in seen]
        if not added:
            break
        seen.update(c["url"] for c in added)
        cases.extend(added)
    return cases


def fetch_case_list(list_url: str, use_cache: bool = True) -> list:
    """一覧ページから個別事例のリストを返す（全ページを辿る）。

    戻り値: [{"url": ..., "title": ..., "thumbnail": ...}, ...]（重複除去済み）
    取得に失敗した場合は空リストを返す（呼び出し側でフォールバック）。

    1 ページ目だけだと新しい 20 件しか見えず、カテゴリー内の該当事例を
    取りこぼす（例: 駐車場・車庫のアコーディオンガレージは 2 ページ目）。
    そのため新しい事例が出てこなくなるまでページを辿る。
    """
    can_cache = _ensure_dir(LIST_CACHE_DIR)
    cache_file = _cache_path(list_url)

    if use_cache and can_cache and cache_file.exists():
        if time.time() - cache_file.stat().st_mtime < CACHE_TTL_SEC:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    cases = _fetch_all_pages(list_url)
    if not cases:
        return []

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


def _image_prefix(og_image_url: str, case_url: str) -> str:
    """その事例の写真を見分けるためのファイル名プレフィックス（例: "39880"）。

    記事番号と写真のファイル名が一致しない事例がある
    （例: /works/42821/ の写真は 39880_1.jpg 〜 39880_6.jpg）。
    og:image はその事例の代表写真なので、そのファイル名から番号を取るのが確実。
    取れない場合だけ URL の事例番号にフォールバックする。
    """
    if og_image_url:
        m = re.match(r"(\d+)[_-]", og_image_url.rsplit("/", 1)[-1])
        if m:
            return m.group(1)
    return _case_number(case_url)


def fetch_case_image_urls(case_url: str) -> list:
    """個別事例ページから施工写真 URL（メイン＋サブ）を取得する。

    - og:image をメイン写真として先頭に
    - 同じ番号プレフィックス（例: 39880_）の uploads 画像をサブに
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
    og_url = urljoin(case_url, og["content"]) if og and og.get("content") else ""
    if og_url:
        urls.append(og_url)

    num = _image_prefix(og_url, case_url)
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "/wp-content/uploads/" not in src or src.lower().endswith((".svg", ".png")):
            continue
        # この事例に紐づく写真のみ（番号プレフィックス）。sで終わる縮小版は本体を優先
        fname = src.rsplit("/", 1)[-1]
        if num and not re.match(rf"{num}[_-]", fname):
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
