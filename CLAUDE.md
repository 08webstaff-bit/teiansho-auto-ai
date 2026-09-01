# 丸八自動提案書 — Claude Code 向けプロジェクト説明

見積書（PDF / Excel / 画像）から提案書パワーポイント（.pptx）を自動生成する、
丸八テント商会の社内営業支援アプリ。

## 絶対に守るルール（最重要）

**施工事例の URL を絶対に捏造しないこと。** `https://08tent.co.jp/works/12345/` のような
URL を、AI にもコードにも自由文字列として作らせてはならない。

URL の入手経路は次の 2 つだけ:

1. `data/cases.json` のホワイトリスト（カテゴリー一覧ページの URL）
2. カテゴリー一覧ページ（`works_kw/`）を実際にスクレイピングして得た実在の個別事例 URL

`data/cases.json` は 08tent.co.jp/works-top/ のカテゴリー 12 件と 1 対 1 で対応させる。
サイト側のカテゴリーが増減したときはここを合わせる（全件が `works_kw/` の一覧ページ）。
一覧は**全ページを辿る**（1 ページ目 20 件だけだと該当事例を取りこぼす。
実際、駐車場・車庫のアコーディオンガレージは 2 ページ目にある）。

この方針は 3 段構えで実装されている。変更するときも必ず維持すること。

| 段 | 内容 |
|---|---|
| 1 | Claude には「キー」か「候補番号」だけを答えさせ、URL 文字列を生成させない |
| 2 | structured outputs の `enum` で、API レベルでホワイトリスト外の値を返せなくする |
| 3 | コード側でバリデーションし、不正ならリトライ → デフォルト/先頭候補にフォールバック |

補足: structured outputs は integer の `minimum`/`maximum` に非対応。範囲を縛るときは `enum` を使う。

## 処理の流れ

```
見積書ファイル
  ↓ src/extract.py        Claude API で構造化抽出（顧客名・案件名・明細・合計・業種）
見積データ（画面で修正可）
  ↓ src/select_case.py    cases.json からカテゴリーを 2 件選定
  ↓ src/resolve_case.py   一覧ページをスクレイピングし、個別事例を 1 件に絞り込み
選定事例（画面で選び直し可）
  ↓ src/proposal_text.py  コンセプト文・施工イメージを生成
  ↓ src/scrape.py         個別事例ページから施工写真を取得
  ↓ src/pptx_builder.py   提案書 pptx を組み立て
提案書（.pptx）
```

`src/headless.py` が UI 抜きの共通オーケストレーション層。
Streamlit・Web API・外部スキルはすべてここを経由するので、ロジックの二重管理はしない。

入口はもう 1 つある。**見積検索AI（mitsumori-search-ai）からの引き継ぎ**では、
見積内容が URL のフラグメント（`#quote=<base64url>`）で渡ってくるため、
`extract.py` を通さず STEP2「内容確認」から始まる（`index.html` の `importFromHash()`）。
渡ってくる JSON は `QUOTE_SCHEMA` と同じ形。外から来る値なので `normalizeIncomingQuote()`
で型と業種（`INDUSTRY` の値かどうか）を必ず検証してから `S.quote` に入れること。
`QUOTE_SCHEMA` のフィールドを変えるときは、見積検索AI 側の送信処理
（`index.html` の `buildProposalPayload()`）も合わせて直す。

## 画面は 2 系統（ロジックは共通）

| 用途 | 入口 | 起動 |
|---|---|---|
| 本番（営業担当が使う） | `index.html` + `api/index.py` | Vercel |
| 開発・動作確認 | `app.py` | `.venv/bin/streamlit run app.py` |

ローカルで本番と同じ画面を見る場合:
`.venv/bin/python -m uvicorn src.api_server:app --port 8600` → http://localhost:8600

## 開発時の注意

- **仮想環境の Python を使う**（`.venv/bin/python`）。システムの `python3` では依存が入っていない。
- **テスト**: `.venv/bin/python -m pytest tests/`（74 件。API・ネットワークを使わないよう全てモック化されている）
- **APIキー**: `.env` の `ANTHROPIC_API_KEY` から読む。コードに直書きしない。`.env` は Git 管理外。
- **依存の追加先**:
  - 本番でも使う → `requirements.txt`（Streamlit や pandas は入れない。Vercel のサイズ上限対策）
  - ローカル専用 → `requirements-dev.txt`
- **キャッシュ**: `cache/` に事例一覧と画像を保存。Vercel など書き込み不可の環境では自動で一時領域に切り替わる。

## デプロイ（Vercel）

手順は `DEPLOY.md` を参照。要点だけ:

- Application Preset は **FastAPI**
- 環境変数 `ANTHROPIC_API_KEY` の登録が必須（未登録だと起動はするが処理が失敗する）
- **API のパスは `/api` を付けない**（`/extract`, `/select` など）。Vercel の構成上 `/api/*` は届かない。
  画面側は `/health` で疎通確認して使える入口を自動判定している。
- 過去にハマった点:
  - `vercel.json` に rewrite を書くとパスが壊れて全て 404 になる → 書かない
  - デプロイごとに固有 URL が発行され、古い URL は古いビルドのまま固定される
    → 動作確認は必ず本番 URL で行う
  - ブラウザが `index.html` をキャッシュして修正が反映されないことがある
    → `vercel.json` の headers で no-cache を付与済み

## スライドの内容についての決まり

- 事例スライドに「選定理由」は載せない（社内向け情報であり、顧客が見ると不自然なため）。
  選定理由はアプリ画面にのみ表示する。
- デザインは白ベース＋コーポレートカラー `#0070E0`、フォントは游ゴシック。
- 工場間通路テント（仮設・レール無）を提案する場合は、オプションでウェイト設置を必ず提案する。
- 事例スライドの写真は必ず 2 枚。写真が 1 枚しかない事例は同じカテゴリー内で選び直す
  （`_pick_with_enough_photos`）。どの候補も 1 枚しかない場合だけ、事例の適合度を優先して
  最初の選択を残す。写真は事例ページの og:image と、同じ番号プレフィックスの画像から取る
  （記事番号と画像のファイル名が一致しない事例があるため、番号は og:image から読む）。
- 参考事例 2 は参考事例 1 と同じ商材にそろえる。商材の違う事例が並ぶと提案として弱くなるため、
  `_prefer_same_category`（同じカテゴリーに寄せる）と `_pick_index` の `similar_to`
  （1 件目と同じ商材を選ばせる）の 2 段で担保している。
