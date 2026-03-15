import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import time
import extra_streamlit_components as stx
from bs4 import BeautifulSoup
import re

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", page_icon="📊", layout="centered")

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { 
        background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; color: #ffffff; font-size: 15px;
    }
    /* 讓 multiselect 的標籤更顯眼 */
    .stMultiSelect span { color: white !important; }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; color: white !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        .stButton button { padding: 4px 0px !important; font-size: 13px !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. API 函數庫 ---

@st.cache_data(ttl=86400)
def search_stock(query):
    """搜尋證交所 API，返回『代碼 名稱』格式字串"""
    query = str(query).strip()
    if not query: return []
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={query}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions") and resp["suggestions"][0] != "No Data Found":
            # 格式化為 "2615 萬海"
            return [s.replace("\t", " ") for s in resp["suggestions"]]
    except: pass
    return []

@st.cache_data(ttl=3600)
def fetch_finmind_institutional(stock_id, start_date, end_date):
    url = "https://api.finmindtrade.com/api/v4/data"
    parameter = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": str(stock_id),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d")
    }
    try:
        resp = requests.get(url, params=parameter, timeout=15).json()
        if resp.get('status') == 200 and resp.get('data'):
            df = pd.DataFrame(resp['data'])
            df['net'] = df['buy'] - df['sell']
            def classify(n):
                n = str(n).lower()
                if 'foreign' in n or '外資' in n: return 'f_net'
                elif 'trust' in n or '投信' in n: return 'it_net'
                elif 'dealer' in n or '自營' in n: return 'd_net'
                return 'other'
            df['type'] = df['name'].apply(classify)
            pivot_df = df.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
            for col in ['f_net', 'it_net', 'd_net']:
                if col not in pivot_df.columns: pivot_df[col] = 0
            pivot_df['total_net'] = pivot_df['f_net'] + pivot_df['it_net'] + pivot_df['d_net']
            pivot_df = pivot_df.reset_index()
            pivot_df['id'] = stock_id
            pivot_df['date'] = pd.to_datetime(pivot_df['date']).dt.strftime('%Y-%m-%d')
            return pivot_df
    except: return None

# --- 3. 股票清單與 Cookie 管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

user_lists = load_user_lists()

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
selected_list_name = st.selectbox("快速載入常用組合", ["自訂輸入..."] + list(user_lists.keys()))

# 預設顯示的股票標籤
default_stocks = ["2603 長榮", "2609 陽明", "2615 萬海"]
if selected_list_name != "自訂輸入...":
    default_stocks = user_lists[selected_list_name].split(",")

# 【核心功能：Tag 化搜尋】
# 使用 multiselect 並結合動態搜尋建議
search_query = st.text_input("🔍 搜尋並新增股票 (輸入代碼或名稱，如：台積電)", key="stock_search")
options = []
if search_query:
    options = search_stock(search_query)

# 最終選擇的股票會以 Tag 形式呈現
final_selection = st.multiselect(
    "目前已選清單 (可手動刪除或從上方搜尋新增)",
    options=list(set(default_stocks + options)),
    default=default_stocks
)

with st.expander("💾 儲存目前清單到瀏覽器"):
    new_name = st.text_input("組合名稱", placeholder="例如: 航運小分隊")
    if st.button("💾 儲存清單"):
        if new_name and final_selection:
            user_lists[new_name] = ",".join(final_selection)
            save_user_lists(user_lists)
            st.success("✅ 已儲存！"); time.sleep(0.5); st.rerun()

st.subheader("2. 查詢區間")
presets = [[("1天",1),("2天",2),("3天",3),("4天",4)],[("1周",7),("2周",14),("3周",21),("1月",30)]]
if 'start_date' not in st.session_state: st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14); st.session_state.label = "2周"
for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        if cols[i].button(label, type="primary" if st.session_state.label==label else "secondary", use_container_width=True):
            st.session_state.start_date, st.session_state.label = datetime.date.today() - datetime.timedelta(days=days-1), label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 數據分析與視覺化 ---
if run_btn:
    if not final_selection:
        st.warning("⚠️ 請至少選擇一檔股票。")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        final_results = []
        
        for idx, item in enumerate(final_selection):
            # item 格式為 "2615 萬海"
            parts = item.split(" ")
            sid = parts[0]
            sname = parts[1] if len(parts) > 1 else sid
            
            status_area.markdown(f'<div class="status-box">🔍 正在解析：{sname} ({sid})</div>', unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(sid, start_date, end_date)
            if df is not None and not df.empty:
                final_results.append({"id": sid, "name": sname, "df": df})
            progress_bar.progress((idx + 1) / len(final_selection))

        status_area.empty(); progress_bar.empty()
        
        if final_results:
            st.session_state.results = final_results
            st.session_state.analysis_info = {"start": start_date, "end": end_date}
            st.session_state.has_run = True

if st.session_state.get('has_run'):
    sel_label = st.radio("🔄 切換檢視", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和":"total_net", "外資":"f_net", "投信":"it_net", "自營商":"d_net"}[sel_label]
    
    for res in st.session_state.results:
        df = res["df"]
        fig = go.Figure()
        y_val = df[y_col] / 1000
        fig.add_trace(go.Bar(
            x=df['date'], y=y_val, 
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val],
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        # 【修正顯示】標題現在只會顯示一個代碼 + 中文名稱
        fig.update_layout(
            title=f"【{res['id']} {res['name']}】{sel_label} (張)", 
            template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10)
        )
        st.plotly_chart(fig, use_container_width=True)

    # 報告區
    report = f"【分析期間：{st.session_state.analysis_info['start']} ~ {st.session_state.analysis_info['end']}】\n" + "="*35 + "\n"
    for res in st.session_state.results:
        val = res["df"][y_col].sum() / 1000
        report += f"{res['id']} {res['name']}: {val:+, .0f} 張\n"
    st.code(report, language="text")
