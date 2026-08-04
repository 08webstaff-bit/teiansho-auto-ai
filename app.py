"""丸八自動提案書 — 見積書から提案スライドを自動生成する社内アプリ。

起動: streamlit run app.py
"""

import pandas as pd
import streamlit as st

from datetime import datetime

from src.extract import INDUSTRY_TYPES, extract_quote
from src.llm import api_key_available
from src.pptx_builder import build_proposal_pptx
from src.proposal_text import generate_proposal_text
from src.resolve_case import (
    category_candidates,
    make_resolved_from_candidate,
    resolve_selection,
)
from src.select_case import load_cases, select_cases

st.set_page_config(page_title="丸八自動提案書", page_icon="⛺", layout="wide")

CORPORATE_BLUE = "#0070E0"


def is_list_fallback(resolved_case: dict) -> bool:
    """一覧 URL のまま（個別事例に絞れなかった）かどうか。"""
    return "/works_kw/" in resolved_case["url"]


def _get_candidates(case_key: str, case: dict) -> list:
    """カテゴリーの個別事例候補を取得（session_state にキャッシュ）。"""
    cache = st.session_state.setdefault("candidates_cache", {})
    if case_key not in cache:
        cache[case_key] = category_candidates(case)
    return cache[case_key]


def render_case_editor(slot: int, current: dict, cases: dict) -> dict:
    """事例1件を、カテゴリー・個別事例を選び直せる形で表示し、選択結果を返す。"""
    keys = list(cases.keys())
    with st.container(border=True):
        st.markdown(f"##### 参考事例 {slot + 1}")

        col_cat, col_case = st.columns(2)
        with col_cat:
            cat_key = st.selectbox(
                "カテゴリー",
                keys,
                index=keys.index(current["key"]) if current["key"] in keys else 0,
                format_func=lambda k: cases[k]["name"],
                key=f"cat_{slot}",
            )

        case = cases[cat_key]
        candidates = _get_candidates(cat_key, case)

        # カテゴリーが変わったら個別事例は先頭にリセット（widget key にカテゴリーを含める）
        default_idx = 0
        if cat_key == current["key"]:
            for idx, c in enumerate(candidates):
                if c["url"] == current["url"]:
                    default_idx = idx
                    break
        # 選択肢はタイトル文字列そのもの（番号付きで一意化）にして、
        # 内部値と表示のズレによる不具合を防ぐ
        labels = [f"{i + 1}. {c['title'][:45]}" for i, c in enumerate(candidates)]
        with col_case:
            if len(candidates) > 1:
                chosen_label = st.selectbox(
                    "個別事例",
                    labels,
                    index=default_idx,
                    key=f"case_{slot}_{cat_key}",
                )
                case_idx = labels.index(chosen_label)
            else:
                case_idx = 0
                st.text_input("個別事例", value=labels[0], disabled=True, key=f"caseone_{slot}_{cat_key}")

        chosen = candidates[case_idx]
        # 手動変更されたか（AI選定と URL が異なるか）
        manual = chosen["url"] != current["url"]
        result = make_resolved_from_candidate(cat_key, case, chosen, manual=manual)
        if not manual:
            # 変更なし → AI の選定理由を維持
            result["reason"] = current.get("reason", "")
            result["category_reason"] = current.get("category_reason", "")

        # プレビュー
        if chosen.get("thumbnail"):
            cols = st.columns([1, 2])
            with cols[0]:
                st.image(chosen["thumbnail"], width="stretch", caption="サムネイル")
            body = cols[1]
        else:
            body = st.container()
        with body:
            st.markdown(f"**{chosen['title']}**")
            st.markdown(f"🔗 [{chosen['url']}]({chosen['url']})")
            reason = result.get("reason") or result.get("category_reason")
            if reason:
                st.markdown(f"選定理由: {reason}")
            note = case.get("note")
            if note:
                st.info(f"営業メモ: {note}")
            if is_list_fallback(result):
                st.warning("一覧ページから個別事例を取得できませんでした。カテゴリー一覧ページのまま掲載されます。")
    return result

st.markdown(
    f"<h1 style='color:{CORPORATE_BLUE};'>⛺ 丸八自動提案書</h1>"
    "<p>見積書をアップロードすると、内容の抽出 → 類似事例の選定 → 提案スライド生成まで自動で行います。</p>",
    unsafe_allow_html=True,
)

if not api_key_available():
    st.error(
        "ANTHROPIC_API_KEY が設定されていません。"
        "プロジェクト直下の `.env` に `ANTHROPIC_API_KEY=sk-ant-...` を記載して再起動してください。"
    )

# ---------------------------------------------------------------- STEP 1
st.header("STEP 1: 見積書アップロード")

uploaded = st.file_uploader(
    "見積書ファイル（PDF / Excel / JPG / PNG）",
    type=["pdf", "xlsx", "xlsm", "xls", "jpg", "jpeg", "png"],
)

if uploaded is not None and st.button("見積書を読み取る", type="primary", key="btn_extract"):
    with st.spinner("Claude が見積書を解析しています…（30秒ほどかかる場合があります）"):
        try:
            quote = extract_quote(uploaded.name, uploaded.getvalue())
            st.session_state["quote"] = quote
            st.session_state.pop("selection", None)  # 再抽出時は選定結果をリセット
            st.success("読み取りが完了しました。内容を確認・修正してください。")
        except Exception as e:
            st.error(f"読み取りに失敗しました: {e}")

# ---------------------------------------------------------- 抽出結果の編集
if "quote" in st.session_state:
    quote = st.session_state["quote"]

    st.subheader("抽出内容の確認・修正")
    st.caption("読み取れなかった項目は空欄になっています。営業担当の判断で修正してください。")

    col1, col2 = st.columns(2)
    with col1:
        customer_name = st.text_input("顧客名（会社名・施設名）", value=quote["customer_name"])
        project_name = st.text_input("案件名・工事名", value=quote["project_name"])
    with col2:
        industry_type = st.selectbox(
            "業種・施設タイプ",
            INDUSTRY_TYPES,
            index=INDUSTRY_TYPES.index(quote["industry_type"]),
            help=quote.get("industry_reason") or None,
        )
        total_amount = st.number_input(
            "合計金額（円）",
            min_value=0,
            value=int(quote["total_amount"] or 0),
            step=1000,
        )

    items_df = pd.DataFrame(
        quote["items"] or [{"name": "", "spec": "", "quantity": "", "unit_price": None, "amount": None}]
    )
    edited_df = st.data_editor(
        items_df,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("品名"),
            "spec": st.column_config.TextColumn("仕様"),
            "quantity": st.column_config.TextColumn("数量"),
            "unit_price": st.column_config.NumberColumn("単価（円）", format="%.0f"),
            "amount": st.column_config.NumberColumn("金額（円）", format="%.0f"),
        },
    )

    # 編集内容を反映した最新の見積データ
    current_quote = {
        "customer_name": customer_name,
        "project_name": project_name,
        "industry_type": industry_type,
        "industry_reason": quote.get("industry_reason", ""),
        "total_amount": total_amount or None,
        "items": edited_df.fillna("").to_dict("records"),
    }
    st.session_state["quote_edited"] = current_quote

    # ------------------------------------------------------------ STEP 2
    st.header("STEP 2: 類似事例の選定")
    st.caption("cases.json に登録済みの事例 URL の中からのみ選定します（URL の捏造はシステム上できません）。")

    if st.button("この内容で事例を選定する", type="primary", key="btn_select"):
        cases = load_cases()
        with st.spinner("Claude がカテゴリーを選定しています…"):
            selection = select_cases(current_quote, cases)
        with st.spinner("一覧ページから最適な個別事例を選定しています…"):
            resolved = resolve_selection(current_quote, selection, cases)
        st.session_state["selection"] = selection
        st.session_state["resolved_cases"] = resolved

    if "resolved_cases" in st.session_state:
        selection = st.session_state["selection"]
        resolved = st.session_state["resolved_cases"]
        cases = load_cases()

        if selection.get("fallback"):
            st.warning(
                "AI によるカテゴリー選定に失敗したため、業種別の標準カテゴリーを表示しています。"
                f"（詳細: {selection.get('error', '')}）"
            )
        else:
            st.success("事例を 2 件選定しました。")

        st.caption(
            "AI が選んだ事例です。正しくない場合は、下のプルダウンでカテゴリーや個別事例を選び直せます。"
        )
        for i in range(len(resolved)):
            resolved[i] = render_case_editor(i, resolved[i], cases)
        st.session_state["resolved_cases"] = resolved

        # 選定事例が変わったら、既存の生成済み pptx は破棄（古いファイルを渡さない）
        current_urls = tuple(r["url"] for r in resolved)
        if st.session_state.get("pptx_source_urls") != current_urls:
            st.session_state.pop("pptx_bytes", None)

        # -------------------------------------------------------- STEP 4
        st.header("STEP 4: 提案スライド生成")
        st.caption(
            "表紙・提案コンセプト・解決策イメージ・参考事例（写真付き）・お見積・裏表紙の"
            "6構成の提案書（.pptx）を生成します。"
        )
        st.warning("⚠️ 生成前に、上記の抽出内容と選定事例が正しいかご確認ください。承認のうえ生成します。")

        if st.button("この内容で提案書を生成する", type="primary", key="btn_pptx"):
            with st.spinner("提案コンセプト文を生成し、事例写真を取得しています…"):
                proposal_text = generate_proposal_text(current_quote, resolved)
                pptx_bytes = build_proposal_pptx(current_quote, resolved, proposal_text)
            st.session_state["pptx_bytes"] = pptx_bytes
            st.session_state["proposal_text"] = proposal_text
            st.session_state["pptx_source_urls"] = tuple(r["url"] for r in resolved)

        if "pptx_bytes" in st.session_state:
            st.success("提案書を生成しました。下のボタンからダウンロードできます。")
            with st.expander("生成された提案コンセプト文を確認"):
                pt = st.session_state["proposal_text"]
                st.markdown(f"**タイトル案:** {pt.get('title_suggestion', '')}")
                st.markdown(f"**コンセプト:** {pt.get('concept', '')}")
                for i, s in enumerate(pt.get("solution_images", []), 1):
                    st.markdown(f"**施工イメージ案{i}:** {s}")

            customer = (current_quote.get("customer_name") or "提案書").replace("/", "_")
            fname = f"提案書_{customer}_{datetime.now():%Y%m%d}.pptx"
            st.download_button(
                "📥 提案書（.pptx）をダウンロード",
                data=st.session_state["pptx_bytes"],
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                type="primary",
            )
