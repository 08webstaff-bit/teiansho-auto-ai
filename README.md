# 丸八自動提案書

見積書（PDF / Excel / 画像）をアップロードするだけで、提案用パワーポイント（.pptx）を自動生成する丸八テント商会の社内アプリです。

## 現在の実装状況

| STEP | 内容 | 状況 |
|---|---|---|
| 1 | 見積書アップロード → Claude API で構造化抽出 → 画面上で編集 | ✅ 実装済み |
| 2a | カテゴリーの自動選定（ホワイトリスト方式・URL 捏造防止） | ✅ 実装済み |
| 2b | カテゴリー一覧をスクレイピング → 見積内容に最も近い個別事例を自動選定 | ✅ 実装済み |
| 3 | 個別事例ページから施工写真（メイン＋サブ）を取得＆キャッシュ | ✅ 実装済み |
| 4 | python-pptx による提案スライド生成（6構成）＋ダウンロード | ✅ 実装済み |

これで見積書アップロードから提案書（.pptx）ダウンロードまで一気通貫で動作します。

## 生成される提案書の構成（6ページ）

1. **表紙** — 「◯◯様 御中／ご提案書」＋案件タイトル案＋「提案：株式会社丸八テント商会」
2. **提案コンセプト** — Claude が生成した約300文字のコンセプト文（顧客の課題→解決アプローチ）
3. **解決策のイメージ** — 施工イメージ案を2つ
4. **参考類似事例** — 事例ごとに1ページ（施工写真＋タイトル＋選定理由＋事例ページ URL）
5. **お見積内容** — 抽出した明細を表形式＋合計金額
6. **裏表紙** — 会社情報・お問い合わせ

デザイン: 白ベース＋コーポレートカラー #0070E0、游ゴシック。

## 使い方は 2 通り

| 使い方 | 対象 | 起動 |
|---|---|---|
| **ブラウザ版（Vercel）** | 営業担当（本番） | `index.html` + `api/index.py`。公開手順は [DEPLOY.md](DEPLOY.md) |
| **Streamlit 版** | 開発・動作確認用 | `streamlit run app.py` |

どちらも `src/` の同じロジック（抽出・事例選定・pptx生成）を使っています。

## セットアップ

```bash
cd teiansho-auto-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # 本番用 requirements.txt + Streamlit・テスト
```

### API キーの設定

`.env.example` をコピーして `.env` を作成し、Anthropic API キーを記載します。

```bash
cp .env.example .env
# .env を編集して ANTHROPIC_API_KEY=sk-ant-... を設定
```

API キーはコードにハードコードせず、必ず `.env` から読み込みます（`.env` は `.gitignore` 済み）。

## 起動方法

```bash
streamlit run app.py
```

ブラウザで http://localhost:8501 が開きます。

## API サーバー（見積検索AI との連携用）

見積検索AI（mitsumori-search-ai）の画面から「⛺ 提案書を作成（pptx）」ボタンで
提案書を生成するには、この提案書 API を起動しておきます（見積書 xlsx を受け取り pptx を返す）。

```bash
.venv/bin/python -m uvicorn src.api_server:app --port 8600
```

- `GET /api/health` … 疎通確認（見積検索AI 側の起動チェックに使用）
- `POST /api/proposal` … 見積書ファイル（multipart `file`）を受け取り、抽出→事例選定→
  提案書生成を一気に行って `.pptx` を返す。選定事例は `X-Proposal-Meta` ヘッダに含める。

処理の中身は Streamlit 版（`app.py`）と共通の `src/headless.py` に集約しており、
UI 版・API 版・スキル（mitsumori-to-teiansho）が同じロジックを使います。
API キーは Streamlit 版と同じく `.env` から読み込むため、必ずこのディレクトリ直下で起動してください。

## テスト

```bash
pytest tests/ -v
```

API を呼ばない単体テスト（バリデーション・フォールバック・ファイル処理）のみ実行されます。

## 事例選定の 2 段構え

1. **カテゴリー選定（STEP 2a）**: 見積内容から `data/cases.json` のキー（カテゴリー）を 2 件選定
2. **個別事例の絞り込み（STEP 2b）**: カテゴリーが一覧ページ（`works_kw/`）の場合、そのページを
   スクレイピングして実在する個別事例（`works/数字/`）を取得し、見積内容に最も近い 1 件を選定

これにより「大型トラック対応の荷捌きテント」のような具体的な個別事例まで自動で辿り着きます。

### 手動での選び直し

AI の選定が正しくない場合は、提案書生成の前に画面上で選び直せます。

- **カテゴリー変更**: プルダウンで別のカテゴリー（cases.json のキー）を選択
- **個別事例変更**: そのカテゴリー内の実在事例の中から、サムネイル付きで別の事例を選択

選び直すと写真プレビューも更新され、既に生成済みの提案書は自動で無効化されます（古いファイルを渡さないため）。

## URL 捏造防止の設計（最重要）

施工事例の URL は、**AI に一切生成させず**、以下のいずれかからのみ取得します。

- カテゴリー URL: `data/cases.json` のホワイトリスト
- 個別事例 URL: カテゴリー一覧ページを**実際にスクレイピングして得た実在する URL**

具体的には 3 段構えで捏造を防いでいます。

1. Claude には **キー / 候補番号（index）だけ**を回答させ、URL 文字列は一切生成させない
2. structured outputs（JSON スキーマの enum）で、API レベルでホワイトリスト外の値を返せないよう強制
3. さらにコード側でバリデーションし、不正な場合はリトライ → デフォルト / 先頭候補にフォールバック

## ディレクトリ構成

```
teiansho-auto-ai/
├── app.py                 # Streamlit アプリ本体
├── data/cases.json        # 事例 URL ホワイトリスト
├── src/
│   ├── llm.py             # Claude API クライアント共通設定
│   ├── extract.py         # STEP 1: 見積書の構造化抽出
│   ├── select_case.py     # STEP 2a: カテゴリー選定（バリデーション・フォールバック付き）
│   ├── scrape.py          # 一覧スクレイピング・STEP 3 施工写真取得＆キャッシュ
│   ├── resolve_case.py    # STEP 2b: 一覧から個別事例を絞り込み
│   ├── proposal_text.py   # STEP 4: コンセプト文・施工イメージ生成
│   └── pptx_builder.py    # STEP 4: 提案スライド生成
├── cache/
│   ├── lists/             # カテゴリー一覧のスクレイピング結果（24h キャッシュ）
│   └── images/            # 事例写真のローカルキャッシュ
├── tests/                 # pytest 単体テスト
├── requirements.txt
└── .env.example
```
