import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import time
import extra_streamlit_components as stx

# --- 1. 環境基礎設定 (網頁預覽設定) ---
st.set_page_config(page_title="三大法人籌碼變化", page_icon="📊", layout="centered")

st.markdown(f"""
    <head>
        <meta property="og:title" content="三大法人籌碼變化">
        <meta property="og:description" content="台股籌碼即時診斷工具：支援多標籤搜尋、SaaS 隔離儲存與法人買賣超分析。">
        <meta property="og:type" content="website">
    </head>
    """, unsafe_allow_html=True)

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { 
        background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; color: #ffffff; font-size: 15px;
    }
    .stMultiSelect span { color: white !important; }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; color: white !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        .stButton button { padding: 4px 0px !important; font-size: 13px !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心 API 函數 ---

@st.cache_data(ttl=86400)
def search_stock(query):
    """精準搜尋證交所 API，返回『代碼 名稱』格式"""
    query = str(query).strip()
    if not query: return []
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={query}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions") and resp["suggestions"][0] != "No Data Found":
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

# --- 3. 股票清單與 Cookie 隔離儲存 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

user_lists = load_user_lists()

# --- 4. UI 介面佈局 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
selected_list_name = st.selectbox("快速載入常用組合", ["自訂輸入..."] + list(user_lists.keys()))

# 初始預設股票
default_stocks = ["2603 長榮", "2609 陽明", "2615 萬海"]
if selected_list_name != "自訂輸入...":
    default_stocks = user_lists[selected_list_name].split(",")

# 多標籤搜尋功能 (Tag 化)
search_query = st.text_input("🔍 搜尋並新增股票 (輸入代碼或名稱)", key="stock_search")
options = []
if search_query:
    options = search_stock(search_query)

final_selection = st.multiselect(
    "目前已選清單 (可手動刪除或從上方搜尋新增)",
    options=list(set(default_stocks + options)),
    default=default_stocks
)

with st.expander("💾 儲存目前清單到瀏覽器 (他人無法看見)"):
    new_name = st.text_input("組合名稱", placeholder="例如: 我的定存股")
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
        is_active = (st.session_state.label == label)
        if cols[i].button(label, type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.start_date, st.session_state.label = datetime.date.today() - datetime.timedelta(days=days-1), label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 數據處理與繪圖 ---
if run_btn:
    if not final_selection:
        st.warning("⚠️ 請至少選擇一檔股票。")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        final_results = []
        
        for idx, item in enumerate(final_selection):
            # 分離代碼與名稱，防止顯示重複代碼
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
        else:
            st.error("❌ 抓取失敗，區間內可能無資料。")

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
        # 標題顯示：【代號 中文名稱】
        fig.update_layout(
            title=f"【{res['id']} {res['name']}】{sel_label} (張)", 
            template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10),
            xaxis=dict(tickformat="%m/%d")
        )
        st.plotly_chart(fig, use_container_width=True)

    # 會診摘要區
    report = f"【期間：{st.session_state.analysis_info['start']} ~ {st.session_state.analysis_info['end']}】\n" + "="*35 + "\n"
    for res in st.session_state.results:
        total_val = res["df"][y_col].sum() / 1000
        report += f"{res['id']} {res['name']}: {total_val:+.0f} 張\n"
    st.code(report, language="text")
