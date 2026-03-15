import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import os

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .stButton button { width: 100%; padding: 0.3rem; font-size: 14px; border-radius: 5px; }
    .status-box { 
        background-color: #1e1e1e; 
        padding: 12px; 
        border-radius: 8px; 
        margin-bottom: 10px; 
        border-left: 5px solid #007bff;
        color: #ffffff;
    }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端緩存與 FinMind API 策略 ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    """透過證交所輕量 API 取得股票名稱"""
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions"):
            return resp["suggestions"][0].split("\t")[1]
    except:
        pass
    return str(stock_id)

@st.cache_data(ttl=3600)
def fetch_finmind_institutional(stock_id, start_date, end_date):
    """使用 FinMind API，單次拉取區間內該股票的所有法人買賣超"""
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
            if df.empty: return None
            
            # 計算淨買賣超 (FinMind 的數據單位為「股」)
            df['net'] = df['buy'] - df['sell']
            
            # FinMind 回傳的是英文名稱 (Foreign_Investor, Investment_Trust, Dealer)
            def classify_investor(name):
                n = str(name).lower()
                if 'foreign' in n or '外資' in n: return 'f_net'
                elif 'trust' in n or '投信' in n: return 'it_net'
                elif 'dealer' in n or '自營' in n: return 'd_net'
                return 'other'
                
            df['type'] = df['name'].apply(classify_investor)
            
            # 以日期分組，將不同法人的 net 加總
            pivot_df = df.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
            
            # 確保欄位都存在，避免報錯
            for col in ['f_net', 'it_net', 'd_net']:
                if col not in pivot_df.columns:
                    pivot_df[col] = 0
                    
            pivot_df['total_net'] = pivot_df['f_net'] + pivot_df['it_net'] + pivot_df['d_net']
            pivot_df = pivot_df.reset_index()
            pivot_df['id'] = stock_id
            
            # 轉換日期格式以便與 Plotly 相容
            pivot_df['date'] = pd.to_datetime(pivot_df['date']).dt.strftime('%Y-%m-%d')
            return pivot_df
    except Exception as e:
        return None
    return None

# --- 3. 股票清單管理 ---
LIST_FILE = "stock_lists.json"
def load_lists():
    if os.path.exists(LIST_FILE):
        try:
            with open(LIST_FILE, "r", encoding="utf-8") as f: return json.load(f)
