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

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { 
        background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; color: #ffffff; font-size: 15px; line-height: 1.6;
    }
    .status-box hr { margin: 8px 0; border: none; border-top: 1px solid #444; }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; border-color: #3b82f6 !important; color: white !important; }
    button[kind="primary"]:hover { background-color: #2563eb !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        [data-testid="stHorizontalBlock"] > div { flex: 1 1 0 !important; min-width: 0 !important; padding: 0 !important; }
        .stButton button { padding: 4px 0px !important; font-size: 13px !important; width: 100% !important; }
    }
    </style>
    """, unsafe_allow_html=True)

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
            df['net'] = df['buy'] - df['sell']
            def classify(name):
                n = str(name).lower()
                if 'foreign' in n or '外資' in n: return 'f_net'
                elif 'trust' in n or '投信' in n: return 'it_net'
                elif 'dealer' in n or '自營' in n: return 'd_net'
                return 'other'
            df['type'] = df['name'].apply(classify)
            pivot = df.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
            for col in ['f_net', 'it_net', 'd_net']:
                if col not in pivot.columns: pivot[col] = 0
            pivot['total_net'] = pivot['f_net'] + pivot['it_net'] + pivot['d_net']
            pivot = pivot.reset_index()
            pivot['id'] = stock_id
            pivot['date'] = pd.to_datetime(pivot['date']).dt.strftime('%Y-%m-%d')
            return pivot
    except: return None

# 【更新 1】真·輕量火箭清單 (只抓最後一個交易日，防擋 IP)
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
                dynamic[f"🚀 最新 ({d.strftime('%m/%d')})：爆量冠軍 Top 20"] = ", ".join(ids)
                break
        except: continue
    return dynamic

# 【更新 2】真·動態概念股爬蟲 (抓取 Yahoo 當下熱門題材)
@st.cache_data(ttl=43200)
def scrape_concept_stocks():
    scraped = {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        # 1. 抓取熱門類股頁面
        url = "https://tw.stock.yahoo.com/class"
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 2. 抓取前 5 個熱門概念產業名稱與連結
        items = soup.select('li[class*="List"] a[href*="category"]')[:5]
        for item in items:
            title = item.get_text(strip=True)
            link = item['href']
            if not link.startswith('http'): link = "https://tw.stock.yahoo.com" + link
            
            # 3. 進入產業頁面抓取前 5 檔代號
            sub_res = requests.get(link, headers=headers, timeout=10)
            sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
            stock_els = sub_soup.select('div[class*="D(f)"] span[class*="C($c-secondary-text)"]')
            ids = []
            for el in stock_els:
                found = re.search(r'\d{4,6}', el.get_text())
                if found: ids.append(found.group())
                if len(ids) >= 5: break
            if ids:
                scraped[f"🌐 即時題材：{title}"] = ", ".join(ids)
    except: pass
    
    if not scraped: # 兜底方案
        scraped = {"🌐 網摘：AI 伺服器": "2382, 3231, 2376, 6669", "🌐 網摘：重電綠能": "1503, 1513, 1514, 1519"}
    return scraped

# --- 3. 股票清單與 Cookie 管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

# 獲取三種清單並合併
dynamic_top20 = fetch_latest_top20()
realtime_concepts = scrape_concept_stocks()
user_lists = load_user_lists()
all_lists = {**dynamic_top20, **realtime_concepts, **user_lists}

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
list_names = list(all_lists.keys())
selected_list = st.selectbox("載入組合 (自動追蹤即時爆量與題材)", ["自訂輸入..."] + list_names)
initial_stocks = all_lists[selected_list] if selected_list != "自訂輸入..." else "2603, 2609, 2615"
stock_input = st.text_input("股票代號 (逗號分隔)", value=initial_stocks)

with st.expander("💾 儲存 / 刪除您的私房清單"):
    new_name = st.text_input("組合名稱", placeholder="例如: 我的定存股")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存清單"):
            if new_name and stock_input:
                user_lists[new_name] = stock_input
                save_user_lists(user_lists)
                st.success("✅ 已儲存！")
                time.sleep(0.5); st.rerun()
    with c2:
        if st.button("❌ 刪除清單"):
            if selected_list in user_lists:
                del user_lists[selected_list]
                save_user_lists(user_lists)
                st.success("🗑️ 已刪除！")
                time.sleep(0.5); st.rerun()

st.subheader("2. 查詢區間")
presets = [
    [("1天", 1), ("2天", 2), ("3天", 3), ("4天", 4)],
    [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
    [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)],
    [("1年", 365), ("2年", 730), ("3年", 1095), ("5年", 1825)]
]
if 'start_date' not in st.session_state:
    st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)
    st.session_state.label = "2周"

for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        is_active = (st.session_state.get('label') == label)
        if cols[i].button(label, type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 數據分析與視覺化 ---
if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    if not targets:
        st.warning("⚠️ 請輸入代號")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        results_list = []
        start_time = time.time()
        
        for idx, stock in enumerate(targets):
            completed = idx + 1
            elapsed = time.time() - start_time
            avg = elapsed / completed if completed > 0 else 0
            eta = int(avg * (len(targets) - completed))
            
            status_area.markdown(f'<div class="status-box">🔍 <b>查詢條件：</b> {st.session_state.get("label", "自定義")} ({start_date} ~ {end_date})<br><hr>⚡ <b>處理進度：</b> [{completed}/{len(targets)}] 正在解析 {stock}<br>⏱️ <b>預估剩餘：</b> {eta} 秒</div>', unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(stock, start_date, end_date)
            if df is not None and not df.empty:
                results_list.append(df)
                summary[stock]['name'] = get_stock_name(stock)
                summary[stock]['f'] = df['f_net'].sum()
                summary[stock]['it'] = df['it_net'].sum()
                summary[stock]['d'] = df['d_net'].sum()
                summary[stock]['tot'] = df['total_net'].sum()
            progress_bar.progress(completed / len(targets))

        status_area.empty(); progress_bar.empty()

        if results_list:
            st.session_state.full_df = pd.concat(results_list)
            st.session_state.summary = summary
            st.session_state.targets = targets
            st.session_state.analysis_info = {"start": start_date, "end": end_date, "label": st.session_state.label, "days": st.session_state.full_df['date'].nunique()}
            st.session_state.has_run = True
        else:
            st.error("❌ 無資料")

if st.session_state.get('has_run', False):
    info = st.session_state.analysis_info
    st.success(f"✅ 高效分析完成！共涵蓋 {info['days']} 個有效交易日")
    sel_label = st.radio("🔄 切換法人檢視", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和":"total_net", "外資":"f_net", "投信":"it_net", "自營商":"d_net"}[sel_label]
    
    for stock in st.session_state.targets:
        sub_df = st.session_state.full_df[st.session_state.full_df['id'] == stock].sort_values('date')
        if sub_df.empty: continue
        fig = go.Figure()
        y_val = sub_df[y_col] / 1000
        fig.add_trace(go.Bar(x=sub_df['date'], y=y_val, marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val], hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"))
        fig.update_layout(title=f"【{st.session_state.summary[stock]['name']}】{sel_label} (張)", template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

    report_text = f"【期間：{info['start']} ~ {info['end']}】\n有效交易日：{info['days']} 天\n" + "="*30 + "\n"
    for s in st.session_state.targets:
        report_text += f"{st.session_state.summary[s]['name']}: {st.session_state.summary[s][{'三大法人總和':'tot','外資':'f','投信':'it','自營商':'d'}[sel_label]]//1000:+,} 張\n"
    st.code(report_text, language="text")
