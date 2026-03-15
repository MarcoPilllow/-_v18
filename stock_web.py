import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import time
import extra_streamlit_components as stx
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 環境基礎設定與護眼 UI ---
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { 
        background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; color: #ffffff; font-size: 14px; 
    }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; border-color: #3b82f6 !important; color: white !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        [data-testid="stHorizontalBlock"] > div { flex: 1 1 0 !important; min-width: 0 !important; padding: 0 !important; }
        .stButton button { padding: 4px 0px !important; font-size: 12px !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. API 函數庫 ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions"): return resp["suggestions"][0].split("\t")[1]
    except: pass
    return str(stock_id)

@st.cache_data(ttl=3600)
def fetch_all_finmind_data(stock_id, start_date, end_date):
    sd, ed = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    try:
        # 1. 股價 (K線 + 均線用)
        res_p = requests.get(url, params={"dataset":"TaiwanStockPrice","data_id":stock_id,"start_date":sd,"end_date":ed}).json()
        df_p = pd.DataFrame(res_p.get('data', []))
        # 2. 法人買賣超
        res_i = requests.get(url, params={"dataset":"TaiwanStockInstitutionalInvestorsBuySell","data_id":stock_id,"start_date":sd,"end_date":ed}).json()
        df_i = pd.DataFrame(res_i.get('data', []))
        # 3. 信用交易
        res_m = requests.get(url, params={"dataset":"TaiwanStockMarginPurchaseShortSale","data_id":stock_id,"start_date":sd,"end_date":ed}).json()
        df_m = pd.DataFrame(res_m.get('data', []))

        if df_p.empty: return None

        # 處理法人
        def classify(n):
            n = str(n).lower()
            if 'foreign' in n or '外資' in n: return 'f_net'
            elif 'trust' in n or '投信' in n: return 'it_net'
            elif 'dealer' in n or '自營' in n: return 'd_net'
            return 'other'
        df_i['net'] = df_i['buy'] - df_i['sell']
        df_i['type'] = df_i['name'].apply(classify)
        pivot_i = df_i.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
        for col in ['f_net', 'it_net', 'd_net']:
            if col not in pivot_i.columns: pivot_i[col] = 0
        pivot_i['total_net'] = pivot_i['f_net'] + pivot_i['it_net'] + pivot_i['d_net']

        # 合併所有資料
        df_all = df_p.copy()
        df_all = pd.merge(df_all, pivot_i, on='date', how='left')
        if not df_m.empty:
            df_m['Margin_Bal'] = df_m['MarginPurchaseTodayBalance'] / 1000
            df_m['Short_Bal'] = df_m['ShortSaleTodayBalance'] / 1000
            df_all = pd.merge(df_all, df_m[['date', 'Margin_Bal', 'Short_Bal']], on='date', how='left')
        
        df_all = df_all.fillna(0)
        df_all['date'] = pd.to_datetime(df_all['date']).dt.strftime('%Y-%m-%d')
        return df_all
    except: return None

@st.cache_data(ttl=3600)
def fetch_latest_top20():
    dynamic = {}
    today = datetime.date.today()
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5: continue
        url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX20?response=json&date={d.strftime('%Y%m%d')}"
        try:
            resp = requests.get(url, timeout=5).json()
            if resp.get("stat") == "OK" and "data" in resp:
                ids = [str(row[1]) for row in resp["data"]]
                dynamic[f"🚀 最新爆量 Top 20"] = ", ".join(ids)
                break
        except: continue
    return dynamic

# --- 3. 股票清單與 Cookie 管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return val if isinstance(val, dict) else {}

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

dynamic_top20 = fetch_latest_top20()
static_concepts = {
    "🌐 網摘：AI 伺服器": "2382, 3231, 2376, 6669",
    "🌐 網摘：矽光子": "3450, 3163, 3363, 6442",
    "🌐 網摘：航運三雄": "2603, 2609, 2615"
}
user_lists = load_user_lists()
all_lists = {**dynamic_top20, **static_concepts, **user_lists}

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
selected_list = st.selectbox("載入組合", ["自訂輸入..."] + list(all_lists.keys()))
initial_stocks = all_lists[selected_list] if selected_list != "自訂輸入..." else "2603, 2609, 2615"
stock_input = st.text_input("股票代號 (逗號分隔)", value=initial_stocks)

st.subheader("2. 查詢區間")
presets = [
    [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
    [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)]
]
if 'label' not in st.session_state: st.session_state.label = "2周"
if 'start_date' not in st.session_state: st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)

for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        is_active = (st.session_state.label == label)
        if cols[i].button(label, type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 數據處理與專業 K 線繪圖 ---
if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    if not targets:
        st.warning("請輸入代號")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        final_results = {}
        start_time = time.time()

        for idx, stock in enumerate(targets):
            status_area.markdown(f'<div class="status-box">🔍 正在彙整：{stock} ({idx+1}/{len(targets)})</div>', unsafe_allow_html=True)
            df = fetch_all_finmind_data(stock, start_date, end_date)
            if df is not None:
                final_results[stock] = {"df": df, "name": get_stock_name(stock)}
            progress_bar.progress((idx+1)/len(targets))
        
        status_area.empty()
        progress_bar.empty()

        for stock_id, data in final_results.items():
            df = data['df']
            # 計算均線
            df['MA5'] = df['close'].rolling(5).mean()
            df['MA20'] = df['close'].rolling(20).mean()

            # 建立多副圖 (1主圖 + 3副圖)
            fig = make_subplots(
                rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                row_heights=[0.5, 0.2, 0.15, 0.15],
                subplot_titles=(f"【{stock_id} {data['name']}】K線/均線", "法人買賣超", "融資餘額", "成交量")
            )

            # --- Row 1: K線圖 ---
            fig.add_trace(go.Candlestick(
                x=df['date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
                name="K線", increasing_line_color='#ef5350', decreasing_line_color='#66bb6a'
            ), row=1, col=1)
            fig.add_trace(go.Scatter(x=df['date'], y=df['MA5'], line=dict(color='#ffeb3b', width=1), name="MA5"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df['date'], y=df['MA20'], line=dict(color='#00e676', width=1), name="MA20"), row=1, col=1)

            # --- Row 2: 法人買賣超 ---
            y_inst = df['total_net'] / 1000
            fig.add_trace(go.Bar(
                x=df['date'], y=y_inst, name="法人張數",
                marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_inst]
            ), row=2, col=1)

            # --- Row 3: 融資餘額 ---
            fig.add_trace(go.Scatter(
                x=df['date'], y=df['Margin_Bal'], mode='lines', 
                line=dict(color='#f1c40f', width=2), name="融資"
            ), row=3, col=1)

            # --- Row 4: 成交量 ---
            fig.add_trace(go.Bar(
                x=df['date'], y=df['Trading_Volume']/1000, name="成交量",
                marker_color='#ecf0f1', opacity=0.7
            ), row=4, col=1)

            fig.update_layout(
                template="plotly_dark", height=800, showlegend=False,
                xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10),
                hovermode="x unified"
            )
            fig.update_yaxes(showgrid=True, gridcolor='#333333')
            st.plotly_chart(fig, use_container_width=True)

        # 報告區
        st.subheader("📋 會診摘要")
        report = ""
        for s in targets:
            if s in final_results:
                d = final_results[s]['df'].iloc[-1]
                report += f"**{s} {final_results[s]['name']}**：法人累積 {d['total_net']//1000:+.0f} 張 | 融資 {d['Margin_Bal']:.0f} 張\n\n"
        st.info(report)
