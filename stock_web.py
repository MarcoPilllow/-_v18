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

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #3b82f6; color: #ffffff; font-size: 15px; }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; border-color: #3b82f6 !important; color: white !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        [data-testid="stHorizontalBlock"] > div { flex: 1 1 0 !important; min-width: 0 !important; padding: 0 !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. API 函數 (FinMind & TWSE) ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions"): return resp["suggestions"][0].split("\t")[1]
    except: pass
    return str(stock_id)

@st.cache_data(ttl=3600)
def fetch_finmind_all_data(stock_id, start_date, end_date):
    """一站式抓取法人、股價(成交量、股數)、信用交易"""
    sd, ed = start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    
    try:
        # 1. 法人買賣超
        res_i = requests.get(url, params={"dataset":"TaiwanStockInstitutionalInvestorsBuySell","data_id":stock_id,"start_date":sd,"end_date":ed}).json()
        df_i = pd.DataFrame(res_i.get('data', []))
        
        # 2. 股價與成交資訊 (包含計算周轉率用的發行股數)
        res_p = requests.get(url, params={"dataset":"TaiwanStockPrice","data_id":stock_id,"start_date":sd,"end_date":ed}).json()
        df_p = pd.DataFrame(res_p.get('data', []))
        
        # 3. 信用交易
        res_m = requests.get(url, params={"dataset":"TaiwanStockMarginPurchaseShortSale","data_id":stock_id,"start_date":sd,"end_date":ed}).json()
        df_m = pd.DataFrame(res_m.get('data', []))

        if df_i.empty: return None

        # 處理法人資料
        df_i['net'] = df_i['buy'] - df_i['sell']
        def classify(n):
            n = str(n).lower()
            if 'foreign' in n or '外資' in n: return 'f_net'
            elif 'trust' in n or '投信' in n: return 'it_net'
            elif 'dealer' in n or '自營' in n: return 'd_net'
            return 'other'
        df_i['type'] = df_i['name'].apply(classify)
        pivot_i = df_i.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
        for col in ['f_net', 'it_net', 'd_net']:
            if col not in pivot_i.columns: pivot_i[col] = 0
        pivot_i['total_net'] = pivot_i['f_net'] + pivot_i['it_net'] + pivot_i['d_net']

        # 合併股價資訊 (成交量、周轉率)
        if not df_p.empty:
            df_p['Volume'] = df_p['Trading_Volume'] / 1000 # 張
            # 周轉率估算: 成交張數 / (成交張數 / 成交筆數... 這裡簡化取成交股數與成交金額)
            # 專業周轉率建議公式: 成交量 / 發行總股數。這裡暫用成交量表示走勢。
            pivot_i = pd.merge(pivot_i, df_p[['date', 'Volume']], on='date', how='left')

        # 合併信用交易
        if not df_m.empty:
            df_m['Margin_Bal'] = df_m['MarginPurchaseTodayBalance'] / 1000
            df_m['Short_Bal'] = df_m['ShortSaleTodayBalance'] / 1000
            pivot_i = pd.merge(pivot_i, df_m[['date', 'Margin_Bal', 'Short_Bal']], on='date', how='left')

        pivot_i = pivot_i.fillna(0).reset_index()
        pivot_i['date'] = pd.to_datetime(pivot_i['date']).dt.strftime('%Y-%m-%d')
        return pivot_i
    except: return None

# --- 3. 股票清單管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return val if isinstance(val, dict) else {}

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

# 這裡省略部分前述爬蟲邏輯以維持代碼精簡，重點在於下方繪圖
all_lists = {"🔥 航運三雄": "2603, 2609, 2615", "🤖 AI 伺服器": "2382, 3231, 2376"}

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")
stock_input = st.text_input("股票代號", value="2603, 2609, 2615")
start_date = st.date_input("開始日期", datetime.date.today() - datetime.timedelta(days=20))
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    results = {}
    for s in targets:
        df = fetch_finmind_all_data(s, start_date, end_date)
        if df is not None: results[s] = {"df": df, "name": get_stock_name(s)}
    st.session_state.results = results
    st.session_state.has_run = True

# --- 5. 多副圖堆疊設定與繪圖 ---
if st.session_state.get('has_run'):
    st.subheader("⚙️ 副圖指標堆疊 (可複選)")
    # 提供多選按鈕
    sub_metrics = st.multiselect(
        "選擇要顯示的副圖指標：",
        ["📊 成交總量 (張)", "💰 融資餘額 (張)", "📉 融券餘額 (張)"],
        default=["📊 成交總量 (張)"]
    )
    
    metric_map = {
        "📊 成交總量 (張)": ("Volume", "#ecf0f1", "成交量"),
        "💰 融資餘額 (張)": ("Margin_Bal", "#f1c40f", "融資"),
        "📉 融券餘額 (張)": ("Short_Bal", "#3498db", "融券")
    }

    results = st.session_state.results
    for stock_id, data in results.items():
        df = data['df']
        
        # 動態計算行數：1 (主圖) + 勾選的副圖數量
        num_subplots = 1 + len(sub_metrics)
        row_heights = [0.5] + [0.5/len(sub_metrics)] * len(sub_metrics) if sub_metrics else [1.0]
        
        fig = make_subplots(
            rows=num_subplots, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.05,
            row_heights=row_heights
        )

        # 1. 主圖：法人籌碼 (Bar)
        y_inst = df['total_net'] / 1000
        fig.add_trace(go.Bar(
            x=df['date'], y=y_inst,
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_inst],
            name="法人總計", hovertemplate="日期: %{x}<br>法人: %{y:+.0f} 張<extra></extra>"
        ), row=1, col=1)

        # 2. 動態添加副圖
        for i, m_label in enumerate(sub_metrics):
            col_name, col_color, label_name = metric_map[m_label]
            if col_name in df.columns:
                fig.add_trace(go.Scatter(
                    x=df['date'], y=df[col_name],
                    mode='lines+markers', name=label_name,
                    line=dict(color=col_color, width=2),
                    hovertemplate=f"日期: %{{x}}<br>{label_name}: %{{y:,.0f}} 張<extra></extra>"
                ), row=i+2, col=1)
                fig.update_yaxes(title_text=label_name, row=i+2, col=1, showgrid=False)

        fig.update_layout(
            title=f"【{data['name']}】多維度籌碼診斷",
            template="plotly_dark", height=300 + (150 * len(sub_metrics)),
            margin=dict(l=10, r=10, t=50, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified" # 關鍵：滑鼠一指，全部指標日期對齊顯示
        )
        fig.update_yaxes(title_text="法人張數", row=1, col=1)
        
        st.plotly_chart(fig, use_container_width=True)
