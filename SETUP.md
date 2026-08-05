# 別のパソコン・別アカウントで同じ環境を作る手順

このリポジトリを別の環境に持っていき、まったく同じアプリを動かすための手順です。
はじめての方でも進められるよう、ひとつずつ書いています。

> **Git に入っていないもの**（各自で用意が必要）
> - `.env`（APIキー）… 手順 4 で作ります
> - `.venv`（Python の部品置き場）… 手順 5 で作ります
> - `cache/`（事例写真の一時保存）… 自動で作られます

---

## 1. 必要なソフトを入れる

| ソフト | 用途 | 入手先 |
|---|---|---|
| GitHub Desktop | コードの取得・更新 | https://desktop.github.com/ |
| Python 3.9 以上 | アプリの実行 | Mac は最初から入っています（下で確認） |

**Python が入っているか確認**（ターミナルを開いて実行）:

```bash
python3 --version
```

`Python 3.9.x` のように表示されれば OK です。
「command not found」と出たら https://www.python.org/downloads/ から入れてください。

---

## 2. リポジトリを取得する（クローン）

非公開リポジトリの場合、まず**元の持ち主から共同編集者（Collaborator）に招待**してもらいます。
招待メールのリンクから承諾してください。

そのあと GitHub Desktop で:

1. **File → Clone repository**
2. 一覧から `teiansho-auto-ai` を選ぶ
3. **Local path** に保存先を選ぶ（例: `書類` フォルダの中）
4. **Clone** をクリック

---

## 3. ターミナルでフォルダを開く

GitHub Desktop のメニューから **Repository → Open in Terminal** を選ぶと、
そのフォルダが開いた状態でターミナルが起動します。以降のコマンドはここに貼り付けます。

---

## 4. APIキーを設定する

Anthropic の API キーが必要です。https://platform.claude.com/ で発行できます
（元の環境と同じキーを使い回すこともできますが、環境ごとに分けるのがおすすめです）。

まず設定ファイルの雛形をコピーします。

```bash
cp .env.example .env
```

次に `.env` をテキストエディットで開きます。

```bash
open -e .env
```

中の `sk-ant-xxxxxxxxxxxxxxxx` の部分を、自分のキーに書き換えて保存してください
（`ANTHROPIC_API_KEY=` の部分と `=` は消さないこと）。

> `.env` は Git に含まれないため、キーが外部に出ることはありません。

---

## 5. Python の部品を入れる

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

2 つめは数分かかります。完了するまで待ってください。

---

## 6. 動くか確認する

まずテストを実行します。

```bash
.venv/bin/python -m pytest tests/
```

`51 passed` と表示されれば、コードは正しく動く状態です。

次に画面を起動します。

```bash
.venv/bin/python -m uvicorn src.api_server:app --port 8600
```

ブラウザで http://localhost:8600 を開き、見積書をアップロードして
提案書がダウンロードできれば成功です。

止めるときはターミナルで `Control + C` を押します。

> 開発用の別画面（Streamlit 版）を使う場合:
> `.venv/bin/streamlit run app.py`

---

## 7. Claude Code で開く

このフォルダを Claude Code で開くと、`CLAUDE.md` を読んで
プロジェクトの決まりごと（特に「URL を捏造しない」設計）を把握した状態で作業できます。

---

## 8. 自分のアカウントで公開する（任意）

社内に配る URL を自分で持ちたい場合は、`DEPLOY.md` の手順で Vercel に公開します。
その際 **環境変数 `ANTHROPIC_API_KEY` の登録を忘れないでください**（忘れると処理が失敗します）。

---

## 困ったとき

| 症状 | 対処 |
|---|---|
| `command not found: python3` | Python を入れる（手順 1） |
| テストで `ModuleNotFoundError` | 手順 5 をやり直す。`.venv/bin/python` を使っているか確認 |
| 画面は出るが処理でエラー | `.env` のキーが正しいか確認（手順 4） |
| 公開後、修正が反映されない | ブラウザで `Command + Shift + R`（スーパーリロード） |
