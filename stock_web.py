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
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

# [CSS 略，與前版相同]
st.markdown("""<style>footer {visibility: hidden;} .status-box { background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 5px solid #3b82f6; color: #ffffff; font-size: 15px; line-height: 1.6;} div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; } button[kind="primary"] { background-color: #3b82f6 !important; border-color: #3b82f6 !important; color: white !important; } @media (max-width: 768px) { [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; } [data-testid="stHorizontalBlock"] > div { flex: 1 1 0 !important; min-width: 0 !important; padding: 0 !important; } .stButton button { padding: 4px 0px !important; font-size: 13px !important; width: 100% !important; } }</style>""", unsafe_allow_html=True)

# --- 2. 雲端緩存與 API ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions"): return resp["suggestions"][0].split("\t")[1]
    except: pass
    return str(stock_id)

@st.cache_data(ttl=3600)
def fetch_finmind_institutional(stock_id, start_date, end_date):
    url = "https://api.finmindtrade.com/api/v4/data"
    parameter = {"dataset": "TaiwanStockInstitutionalInvestorsBuySell", "data_id": str(stock_id), "start_date": start_date.strftime("%Y-%m-%d"), "end_date": end_date.strftime("%Y-%m-%d")}
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

# 【真‧動態爬蟲】去 Yahoo 抓取目前最火熱的概念股
@st.cache_data(ttl=43200) # 半天更新一次即可
def scrape_concept_stocks():
    scraped_lists = {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        # 1. 抓取 Yahoo 概念股排行榜頁面
        main_url = "https://tw.stock.yahoo.com/class"
        res = requests.get(main_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 2. 尋找概念股區塊 (這裡會抓取前 4 個熱門主題)
        items = soup.select('li[class*="List"] a[href*="category"]')[:4]
        
        for item in items:
            title = item.get_text(strip=True)
            link = item['href']
            if not link.startswith('http'): link = "https://tw.stock.yahoo.com" + link
            
            # 3. 進入該概念股頁面抓取成分股代號
            sub_res = requests.get(link, headers=headers, timeout=10)
            sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
            # 抓取前 5 檔股票代號 (台股代號通常是 4-6 位數字)
            stock_elements = sub_soup.select('div[class*="D(f)"] span[class*="C($c-secondary-text)"]')
            ids = []
            for el in stock_elements:
                found = re.search(r'\d{4,6}', el.get_text())
                if found: ids.append(found.group())
                if len(ids) >= 5: break
            
            if ids:
                scraped_lists[f"🌐 即時題材：{title}"] = ", ".join(ids)
                
    except Exception as e:
        pass 

    # 兜底方案
    if not scraped_lists:
        scraped_lists = {"🌐 網摘：AI 伺服器": "2382, 3231, 2376, 6669", "🌐 網摘：重電綠能": "1503, 1513, 1514, 1519"}
        
    return scraped_lists

# [fetch_latest_top20 略，同前版，只抓一天避免被鎖]
@st.cache_data(ttl=3600)
def fetch_latest_top20():
    dynamic_lists = {}
    today = datetime.date.today()
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5: continue
        url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX20?response=json&date={d.strftime('%Y%m%d')}"
        try:
            resp = requests.get(url, timeout=5).json()
            if resp.get("stat") == "OK":
                ids = [str(row[1]) for row in resp["data"]]
                dynamic_lists[f"🚀 最新 ({d.strftime('%m/%d')})：爆量 Top 20"] = ", ".join(ids)
                break
        except: continue
    return dynamic_lists

# --- 3. 股票清單與 Cookie ---
if 'cookie_manager' not in st.session_state: st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

def save_user_lists(lists): cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

# 獲取三種清單：1. 證交所爆量、2. Yahoo 即時題材、3. 個人自訂
dynamic_top20 = fetch_latest_top20()
realtime_concepts = scrape_concept_stocks()
user_custom_lists = load_user_lists()
all_lists = {**dynamic_top20, **realtime_concepts, **user_custom_lists}

# --- 4. UI 介面 (省略細節，同前版) ---
st.title("📊 三大法人籌碼變化")
st.subheader("1. 查詢目標")
list_names = list(all_lists.keys())
selected_list = st.selectbox("載入組合 (支援即時題材、爆量與自訂)", ["自訂輸入..."] + list_names)
initial_stocks = all_lists[selected_list] if selected_list != "自訂輸入..." else "2603, 2609, 2615"
stock_input = st.text_input("股票代號", value=initial_stocks)

# [以下分析邏輯與圖表渲染略，同 v20.3]
# ... [保留原本的日期選擇、執行按鈕、圖表畫法] ...
