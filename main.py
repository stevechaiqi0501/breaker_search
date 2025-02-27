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
# DB接続
########################################
DATABASE_FILE = "cutting_selection.db"
def get_connection():
    db_path = os.path.join(os.path.dirname(__file__), DATABASE_FILE)
    return sqlite3.connect(db_path)

########################################
# DB検索関数
# 未入力 (= None) の項目は WHERE条件を付与せず全許容
########################################
def query_breakers(cut_depth, feed_rate, process_type):
    """
    breakers テーブル
      - 加工種別 = process_type      (未入力なら絞り込まず)
      - 切込み最小 <= cut_depth <= 切込み最大 (未入力なら絞り込まず)
      - 送り量最小 <= feed_rate <= 送り量最大 (未入力なら絞り込まず)
    """
    conn = get_connection()
    base_query = "SELECT * FROM breakers"
    conditions = []
    params = []

    # 加工種別
    if process_type is not None:
        conditions.append("加工種別 = ?")
        params.append(process_type)

    # 切込み
    if cut_depth is not None:
        conditions.append("切込み最小 <= ?")
        conditions.append("切込み最大 >= ?")
        params.extend([cut_depth, cut_depth])

    # 送り量
    if feed_rate is not None:
        conditions.append("送り量最小 <= ?")
        conditions.append("送り量最大 >= ?")
        params.extend([feed_rate, feed_rate])

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    df = pd.read_sql_query(base_query, conn, params=params)
    conn.close()
    return df

def query_materials(cutting_speed, process_type):
    """
    materials テーブル
      - 加工種別 = process_type                (未入力なら絞り込まず)
      - 切削速度最小 <= cutting_speed <= 切削速度最大 (未入力なら絞り込まず)
    """
    conn = get_connection()
    base_query = "SELECT * FROM materials"
    conditions = []
    params = []

    # 加工種別
    if process_type is not None:
        conditions.append("加工種別 = ?")
        params.append(process_type)

    # 切削速度
    if cutting_speed is not None:
        conditions.append("切削速度最小 <= ?")
        conditions.append("切削速度最大 >= ?")
        params.extend([cutting_speed, cutting_speed])

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    df = pd.read_sql_query(base_query, conn, params=params)
    conn.close()
    return df

########################################
# GPT呼び出し
########################################
def call_gpt_api(messages, premise_data, breaker_df, material_df):
    premise_title = premise_data.get("title","(no title)")
    premise_details = premise_data.get("details","(no details)")

    breaker_csv = breaker_df.to_csv(index=False)
    material_csv = material_df.to_csv(index=False)

    system_prompt = f"""
あなたは切削加工分野に詳しいアシスタントです。
以下の「前提条件」「CSVデータ」「ユーザーの入力値」を最優先に参照し、それ以外の不明な情報は勝手に補完・創作しないでください。
もし不明な点があれば、その旨を明示してください。
また、前提条件に反する記述や、CSVに記載のないデータを勝手に参照しないでください。

【前提条件】
タイトル: {premise_title}
詳細: {premise_details}

【ユーザーの入力値】
- 切込み(mm): {st.session_state.cut_depth}
- 送り量(mm/rev): {st.session_state.feed_rate}
- 切削速度(m/min): {st.session_state.cut_speed}
- 加工種別: {st.session_state.process_type}

【ブレーカー候補 CSV】
{breaker_csv}

【素材候補 CSV】
{material_csv}

【指示】
1. 上記の前提条件・入力値・CSVをすべて踏まえ、ユーザーとのチャットを行い、最適なブレーカーと素材を提案してください。
2. 候補を選ぶ際は、前提条件を必ず尊重し、CSVにある情報のみを根拠として理由を述べてください。
3. 候補の素材・ブレーカーは、CSVに該当するものを**すべて列挙**してください。  
   - 万一「推奨範囲を少し超える」または「範囲内に収まっていない」などがあっても、絶対に除外せず「理由を述べたうえで列挙」してください。
4. 「推奨速度を超えてはいけない」などの独自ルールを勝手に課さないでください。
   - 速度や送り量が範囲内かどうかは参考情報であり、少し外れていても一律に不適合とは言わず、理由やリスクを述べるに留めてください。
5. 不明点がある場合は推測で埋めず、「不明です」「データがありません」などと書き、ハルシネーションを起こさないようにしてください。
6. 回答の中で必ず「前提条件に照らし合わせた説明」を含めてください。

これらを徹底的に遵守して回答してください。
"""
    full_messages = [{"role":"system", "content": system_prompt}] + messages

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
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
    if not norm:
        return None  # 未入力の場合は None
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

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

if "chat_finished" not in st.session_state:
    st.session_state.chat_finished = False

########################################
# メイン画面
########################################
st.title("ブレーカー、素材検索アプリ")

# --- 追加: 機能説明のトグル ---
with st.expander("機能説明"):
    st.write("""
**機能1**
- 切込み量 (mm)、送り量 (mm/rev)、切削速度 (m/min) の **3項目中2つ以上**の入力が必要。  
- 加工種別 (仕上げ / 軽切削 / 中切削 / 粗加工) は **任意入力**（空欄でもOK）。

**機能2 条件検索** 
- 入力した加工条件をもとに、ブレーカー（breakersテーブル）と素材（materialsテーブル）の候補を検索。  
- **未入力の項目は全許容**した上でDB検索を行います。  

**機能3 GPTによる分析**
- 検索結果 + 前提条件 + 入力値を踏まえて、GPTと対話しながら最適案を検討できます。
""")

# 前提条件の可視化
with st.expander("前提ファイルの内容"):
    pm = st.session_state["premise_data"]
    st.write(f"**タイトル**: {pm.get('title','')}")
    st.write(f"**詳細**: {pm.get('details','')}")

st.subheader("① 数値入力 & 加工種別選択（3項目中2つ以上必須）")

col1, col2, col3 = st.columns(3)
with col1:
    st.session_state.cut_depth = st.text_input("切込み(mm)", st.session_state.cut_depth)
with col2:
    st.session_state.feed_rate = st.text_input("送り量(mm/rev)", st.session_state.feed_rate)
with col3:
    st.session_state.cut_speed = st.text_input("切削速度(m/min)", st.session_state.cut_speed)

# 加工種別ボタン
b1, b2, b3, b4 = st.columns(4)
if b1.button("仕上げ"):
    st.session_state.process_type = "仕上げ"
if b2.button("軽切削"):
    st.session_state.process_type = "軽切削"
if b3.button("中切削"):
    st.session_state.process_type = "中切削"
if b4.button("粗加工"):
    st.session_state.process_type = "粗加工"

st.write(f"現在の加工種別: {st.session_state.process_type or '未選択'}")

# ★ ここで入力必須ロジックを更新：3項目のうち2つ以上必須
def check_input_requirements():
    cd = sanitize_float(st.session_state.cut_depth)
    fr = sanitize_float(st.session_state.feed_rate)
    cs = sanitize_float(st.session_state.cut_speed)

    numeric_filled = 0
    if cd is not None:
        numeric_filled += 1
    if fr is not None:
        numeric_filled += 1
    if cs is not None:
        numeric_filled += 1

    # 3項目のうち最低2つが必須
    if numeric_filled < 2:
        st.error("切込み量、送り量、切削速度のうち、少なくとも2つ以上を入力してください。")
        st.stop()
    return cd, fr, cs

col_search1, col_search2 = st.columns(2)
with col_search1:
    if st.button("検索のみ"):
        cd, fr, cs = check_input_requirements()  # ここで必須入力チェック
        pt = st.session_state.process_type.strip() if st.session_state.process_type else None

        # DB検索
        bdf = query_breakers(cd, fr, pt)
        mdf = query_materials(cs, pt)

        st.session_state.breaker_df = bdf
        st.session_state.material_df = mdf

        st.success("検索を実行しました。下に結果を表示します。")
        st.rerun()

with col_search2:
    if st.button("GPTに分析してもらう"):
        cd, fr, cs = check_input_requirements()  # ここで必須入力チェック
        pt = st.session_state.process_type.strip() if st.session_state.process_type else None

        bdf = query_breakers(cd, fr, pt)
        mdf = query_materials(cs, pt)

        st.session_state.breaker_df = bdf
        st.session_state.material_df = mdf

        st.success("候補のブレーカー、素材と、前程条件を踏まえた上での検索を行います")

        # ここでGPTに初回分析依頼
        premise = st.session_state["premise_data"]
        user_prompt_for_analysis = "検索結果に基づき、前提条件を踏まえた初回の分析をお願いします。"
        st.session_state.chat_messages.append({
            "role": "user",
            "content": user_prompt_for_analysis
        })

        gpt_reply = call_gpt_api(
            st.session_state.chat_messages,
            premise,
            bdf,
            mdf
        )
        st.session_state.chat_messages.append({"role":"assistant", "content":gpt_reply})

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
    st.session_state.chat_messages.append({"role": "user", "content": user_text})
    premise = st.session_state["premise_data"]
    bdf = st.session_state.breaker_df
    mdf = st.session_state.material_df

    gpt_reply = call_gpt_api(st.session_state.chat_messages, premise, bdf, mdf)
    st.session_state.chat_messages.append({"role": "assistant", "content": gpt_reply})
    st.rerun()

if st.button("最終決定 (チャット終了)"):
    st.session_state.chat_finished = True
    st.rerun()
