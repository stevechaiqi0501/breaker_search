import streamlit as st
import pandas as pd
import openai
import json
import os
import unicodedata
import sqlite3

########################################
# 環境変数からAPIキーを取得
########################################
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai.api_key = OPENAI_API_KEY

########################################
# premise.json を読み込む関数
########################################
def load_premise():
    file_path = os.path.join(os.path.dirname(__file__), "premise.json")
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

########################################
# DB接続 (もし db.py が別途あるならそちらを利用)
########################################
DATABASE_FILE = "cutting_selection.db"
def get_connection():
    db_path = os.path.join(os.path.dirname(__file__), DATABASE_FILE)
    return sqlite3.connect(db_path)

########################################
# DB検索関数
########################################
def query_breakers(cut_depth, feed_rate, process_type):
    """
    breakers テーブル
      - 加工種別=process_type
      - 切込み最小 <= cut_depth <= 切込み最大
      - 送り量最小 <= feed_rate <= 送り量最大
    """
    conn = get_connection()
    query = """
    SELECT *
    FROM breakers
    WHERE
        加工種別 = ?
        AND 切込み最小 <= ?
        AND 切込み最大 >= ?
        AND 送り量最小 <= ?
        AND 送り量最大 >= ?
    """
    df = pd.read_sql_query(query, conn, params=[process_type, cut_depth, cut_depth, feed_rate, feed_rate])
    conn.close()
    return df

def query_materials(cutting_speed, process_type):
    """
    materials テーブル
      - 加工種別=process_type
      - 切削速度最小 <= cutting_speed <= 切削速度最大
    """
    conn = get_connection()
    query = """
    SELECT *
    FROM materials
    WHERE
        加工種別 = ?
        AND 切削速度最小 <= ?
        AND 切削速度最大 >= ?
    """
    df = pd.read_sql_query(query, conn, params=[process_type, cutting_speed, cutting_speed])
    conn.close()
    return df

########################################
# GPT呼び出し
########################################
def call_gpt_api(messages, premise_data, breaker_df, material_df):
    """
    messages: [{"role":"user","content":"..."},{"role":"assistant","content":"..."}...]
    premise_data: {"title":..., "details":...}
    breaker_df, material_df: 候補の DataFrame
    """
    premise_title = premise_data.get("title","(no title)")
    premise_details = premise_data.get("details","(no details)")

    breaker_csv = breaker_df.to_csv(index=False)
    material_csv = material_df.to_csv(index=False)

    system_prompt = f"""
前提条件:
タイトル: {premise_title}
詳細: {premise_details}

ブレーカー候補 CSV:
{breaker_csv}

素材候補 CSV:
{material_csv}

上記を踏まえ、ユーザーとのチャットを行い最適なブレーカーと素材を提案してください。
候補を選ぶ際には、前提条件(耐久性重視など)も考慮し、具体的な理由を述べてください。
"""
    # 先頭に systemメッセージ
    full_messages = [{"role":"system", "content": system_prompt}] + messages

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=full_messages
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"GPT呼び出しエラー: {str(e)}"

########################################
# 数値バリデーション
########################################
def sanitize_float(value_str):
    norm = unicodedata.normalize('NFKC', value_str).strip()
    try:
        val = float(norm)
        if val < 0:
            return None
        return val
    except:
        return None

########################################
# Streamlit セッション初期化
########################################
if "premise_data" not in st.session_state:
    st.session_state["premise_data"] = load_premise()

if "cut_depth" not in st.session_state:
    st.session_state.cut_depth = ""
if "feed_rate" not in st.session_state:
    st.session_state.feed_rate = ""
if "cut_speed" not in st.session_state:
    st.session_state.cut_speed = ""
if "process_type" not in st.session_state:
    st.session_state.process_type = ""

if "breaker_df" not in st.session_state:
    st.session_state.breaker_df = pd.DataFrame()
if "material_df" not in st.session_state:
    st.session_state.material_df = pd.DataFrame()

# GPTチャット用メッセージ履歴
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

# チャット終了フラグ
if "chat_finished" not in st.session_state:
    st.session_state.chat_finished = False


########################################
# メイン画面
########################################
st.title("ブレイカー、素材検索アプリ")

# 1) 前提条件の可視化
with st.expander("前提ファイルの内容"):
    pm = st.session_state["premise_data"]
    st.write(f"**タイトル**: {pm.get('title','')}")
    st.write(f"**詳細**: {pm.get('details','')}")

st.subheader("① 数値入力 & 加工種別選択")

col1, col2, col3 = st.columns(3)
with col1:
    st.session_state.cut_depth = st.text_input("切込み(mm)", st.session_state.cut_depth)
with col2:
    st.session_state.feed_rate = st.text_input("送り量(mm/rev)", st.session_state.feed_rate)
with col3:
    st.session_state.cut_speed = st.text_input("切削速度(m/min)", st.session_state.cut_speed)

# ★★★ 加工種別ボタンを4つに修正: 仕上げ、軽切削、中切削、粗加工 ★★★
b1, b2, b3, b4 = st.columns(4)
if b1.button("仕上げ"):
    st.session_state.process_type = "仕上げ"
if b2.button("軽切削"):
    st.session_state.process_type = "軽切削"
if b3.button("中切削"):
    st.session_state.process_type = "中切削"
if b4.button("粗加工"):
    st.session_state.process_type = "粗加工"

st.write(f"現在の加工種別: {st.session_state.process_type}")

if st.button("検索実行"):
    cd = sanitize_float(st.session_state.cut_depth)
    fr = sanitize_float(st.session_state.feed_rate)
    cs = sanitize_float(st.session_state.cut_speed)
    if cd is None or fr is None or cs is None:
        st.error("数値入力が正しくありません。正の数で入力してください。")
        st.stop()
    if not st.session_state.process_type:
        st.error("加工種別を選択してください。")
        st.stop()

    bdf = query_breakers(cd, fr, st.session_state.process_type)
    mdf = query_materials(cs, st.session_state.process_type)

    st.session_state.breaker_df = bdf
    st.session_state.material_df = mdf

    st.success("検索を実行しました。下に結果を表示します。")
    st.rerun()

st.subheader("② 検索結果表示")

if not st.session_state.breaker_df.empty:
    st.write("### ブレーカー候補")
    st.dataframe(st.session_state.breaker_df)
else:
    st.write("ブレーカー候補なし")

if not st.session_state.material_df.empty:
    st.write("### 素材候補")
    st.dataframe(st.session_state.material_df)
else:
    st.write("素材候補なし")

st.subheader("③ GPTチャットラリー (前提+候補付き)")

if st.session_state.chat_finished:
    st.write("チャットは終了しました。")
    st.stop()

# これまでのメッセージを表示
for msg in st.session_state.chat_messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.write(msg["content"])
    else:
        with st.chat_message("assistant"):
            st.write(msg["content"])

user_text = st.chat_input("追加の質問や要望をどうぞ (終了ボタンで終了)")
if user_text:
    # ユーザー発言を履歴に追加
    st.session_state.chat_messages.append({"role": "user", "content": user_text})
    # GPT呼び出し
    premise = st.session_state["premise_data"]
    bdf = st.session_state.breaker_df
    mdf = st.session_state.material_df

    gpt_reply = call_gpt_api(st.session_state.chat_messages, premise, bdf, mdf)
    st.session_state.chat_messages.append({"role": "assistant", "content": gpt_reply})
    st.rerun()

if st.button("最終決定 (チャット終了)"):
    st.session_state.chat_finished = True
    st.rerun()
