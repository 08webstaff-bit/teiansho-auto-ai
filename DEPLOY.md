# Vercel へのデプロイ手順

ブラウザで使えるように公開する手順です。1回だけ設定すれば、以降は更新のたびに自動反映されます。

## 1. GitHub にアップロード

このフォルダ（`teiansho-auto-ai`）を GitHub のリポジトリにアップロードします。
**private（非公開）で構いません。**

ターミナルで、このフォルダに移動してから実行します。

```bash
git init
git add .
git commit -m "提案書AI ブラウザ版"
```

そのあと GitHub でリポジトリを作り、表示される `git remote add ...` と `git push ...` を実行します。

> `.env`（APIキー）は `.gitignore` に入れてあるのでアップロードされません。
> キーは次の手順で Vercel 側に登録します。

## 2. Vercel に接続

1. https://vercel.com にログイン（他アプリと同じアカウント）
2. **Add New... → Project**
3. 1 で作ったリポジトリを **Import**
4. 設定はすべて既定のままで **Deploy**

## 3. APIキーを登録（重要）

デプロイ後、そのプロジェクトの
**Settings → Environment Variables** で以下を追加します。

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...`（お手元の `.env` と同じ値） |

環境は Production / Preview / Development すべてにチェックを入れてください。

登録したら **Deployments → 最新のデプロイ → Redeploy** で再デプロイします。
（環境変数は再デプロイ後に反映されます）

## 4. 動作確認

発行された URL（`https://～.vercel.app`）を開き、見積書をアップロードして
提案書がダウンロードできれば完了です。この URL を営業担当の方に共有してください。

---

## 更新のしかた

コードを直して GitHub に push すると、Vercel が自動で再デプロイします。

```bash
git add .
git commit -m "修正内容"
git push
```

## 構成メモ

| ファイル | 役割 |
|---|---|
| `index.html` | 画面（ブラウザ側）。Vercel が静的ファイルとして配信 |
| `api/index.py` | サーバー処理の入口。`src/api_server.py` を読み込む |
| `src/` | 抽出・事例選定・スクレイピング・pptx生成のロジック（Streamlit版と共通） |
| `data/cases.json` | 事例URLのホワイトリスト |
| `vercel.json` | 実行時間 60秒・`/api/*` のルーティング設定 |
| `requirements.txt` | Vercel にインストールされる依存（Streamlit は含めない） |
| `requirements-dev.txt` | ローカル開発用（Streamlit・テストを含む） |

## 制限事項

- **アップロードは 4.4MB まで**（Vercel の仕様）。スマホ写真は自動で縮小してから送信します。
  大きい PDF はページを分けるか、Excel をお使いください。
- **処理時間は 1 リクエスト 60 秒まで**。抽出・選定・生成をそれぞれ別の通信に分けているため、
  通常の見積書であれば収まります。
- 事例ページのキャッシュはリクエストごとに消えます（動作に支障はありません）。

## ローカルでの動かし方

```bash
# 初回のみ
.venv/bin/pip install -r requirements-dev.txt

# ブラウザ版と同じ画面をローカルで確認
.venv/bin/python -m uvicorn src.api_server:app --port 8600
# → http://localhost:8600

# Streamlit 版（従来の管理用UI）
.venv/bin/streamlit run app.py
```
