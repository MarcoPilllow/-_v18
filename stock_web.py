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

st.markdown(f"""
    <head>
        <meta property="og:title" content="三大法人籌碼變化">
        <meta property="og:description" content="台股籌碼即時診斷工具：已修正中文名稱顯示，支援動態爆量雷達。">
        <meta property="og:type" content="website">
    </head>
    """, unsafe_allow_html=True)

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
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        [data-testid="stHorizontalBlock"] > div { flex: 1 1 0 !important; min-width: 0 !important; padding: 0 !important; }
        .stButton button { padding: 4px 0px !important; font-size: 13px !important; width: 100% !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端緩存與 API 函數庫 ---

@st.cache_data(ttl=86400)
def get_stock_info(query):
    """精準抓取代碼與名稱，防止重複顯示代碼"""
    query = str(query).strip().split(' ')[0] # 只取空格前的代碼部分，防止傳入已格式化的字串
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={query}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions") and resp["suggestions"][0] != "No Data Found":
            item = resp["suggestions"][0].split("\t")
            return item[0], item[1] # (代碼, 名稱)
    except: pass
    return query, query

def process_input_targets(input_str):
    """解析使用者輸入，確保產出唯一的 (代碼, 名稱) 對象清單"""
    # 處理全角逗號並分割
    raw_items = [s.strip() for s in input_str.replace('，', ',').split(',') if s.strip()]
    seen_ids = set()
    processed = []
    for item in raw_items:
        sid, sname = get_stock_info(item)
        if sid not in seen_ids:
            seen_ids.add(sid)
            processed.append({"id": sid, "name": sname})
    return processed

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
                # 這裡抓取代碼與名稱格式為 '代碼 名稱'
                items = [f"{row[1]} {row[2]}" for row in resp["data"]]
                dynamic[f"🚀 最新 ({d.strftime('%m/%d')})：爆量排行榜"] = ", ".join(items)
                break
        except: continue
    return dynamic

@st.cache_data(ttl=43200)
def scrape_concept_stocks():
    scraped = {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        url = "https://tw.stock.yahoo.com/class"
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('li[class*="List"] a[href*="category"]')[:4]
        for item in items:
            title, link = item.get_text(strip=True), item['href']
            if not link.startswith('http'): link = "https://tw.stock.yahoo.com" + link
            sub_res = requests.get(link, headers=headers, timeout=10)
            sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
            stock_rows = sub_soup.select('div[class*="D(f)"] div[class*="Lh(20px)"]')
            stocks = []
            for row in stock_rows:
                name = row.select_one('span').get_text()
                sid = row.find_next_sibling('div').get_text()
                stocks.append(f"{sid} {name}")
                if len(stocks) >= 5: break
            if stocks: scraped[f"🌐 即時題材：{title}"] = ", ".join(stocks)
    except: pass
    if not scraped:
        scraped = {"🌐 網摘：AI 伺服器": "2382 廣達, 3231 緯創, 2376 技嘉", "🌐 網摘：航運三雄": "2603 長榮, 2609 陽明, 2615 萬海"}
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

dynamic_top20 = fetch_latest_top20()
realtime_concepts = scrape_concept_stocks()
user_lists = load_user_lists()
all_lists = {**dynamic_top20, **realtime_concepts, **user_lists}

# --- 4. 介面渲染 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
selected_list = st.selectbox("載入組合 (支援中文名稱與代碼)", ["自訂輸入..."] + list(all_lists.keys()))
initial_stocks = all_lists[selected_list] if selected_list != "自訂輸入..." else "2603 長榮, 2609 陽明, 2615 萬海"
stock_input = st.text_input("輸入股票代碼或名稱 (例如：台積電, 2603)", value=initial_stocks)

with st.expander("💾 儲存 / 刪除您的私房清單"):
    new_name = st.text_input("組合名稱", placeholder="例如: 航運小分隊")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存清單"):
            if new_name and stock_input:
                user_lists[new_name] = stock_input
                save_user_lists(user_lists)
                st.success("✅ 已儲存！"); time.sleep(0.5); st.rerun()
    with c2:
        if st.button("❌ 刪除清單"):
            if selected_list in user_lists:
                del user_lists[selected_list]
                save_user_lists(user_lists)
                st.success("🗑️ 已刪除！"); time.sleep(0.5); st.rerun()

st.subheader("2. 查詢區間")
presets = [[("1天",1),("2天",2),("3天",3),("4天",4)],[("1周",7),("2周",14),("3周",21),("1月",30)],[("6周",42),("2月",60),("1季",90),("半年",182)]]
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

# --- 5. 數據分析與視覺化 ---
if run_btn:
    targets = process_input_targets(stock_input)
    if not targets:
        st.warning("⚠️ 請輸入有效的代碼或名稱")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        final_summary = {}
        results_list = []
        start_time = time.time()
        
        for idx, t_obj in enumerate(targets):
            completed = idx + 1
            elapsed = time.time() - start_time
            avg = elapsed / completed
            eta = int(avg * (len(targets) - completed))
            
            status_area.markdown(f'<div class="status-box">🔍 <b>解析中：</b> {t_obj["name"]} ({t_obj["id"]})<br><hr>⏱️ <b>預估剩餘：</b> {eta} 秒</div>', unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(t_obj["id"], start_date, end_date)
            if df is not None and not df.empty:
                results_list.append(df)
                final_summary[t_obj["id"]] = {
                    "name": t_obj["name"],
                    "f": df['f_net'].sum(), "it": df['it_net'].sum(), "d": df['d_net'].sum(), "tot": df['total_net'].sum()
                }
            progress_bar.progress(completed / len(targets))

        status_area.empty(); progress_bar.empty()
        if results_list:
            full_df = pd.concat(results_list)
            st.session_state.full_df, st.session_state.summary, st.session_state.targets = full_df, final_summary, targets
            st.session_state.analysis_info = {"start": start_date, "end": end_date, "days": full_df['date'].nunique()}
            st.session_state.has_run = True

if st.session_state.get('has_run'):
    info = st.session_state.analysis_info
    st.success(f"✅ 高效分析完成！共涵蓋 {info['days']} 個有效交易日")
    sel_label = st.radio("切換檢視", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和":"total_net", "外資":"f_net", "投信":"it_net", "自營商":"d_net"}[sel_label]
    
    for t_obj in st.session_state.targets:
        sid = t_obj["id"]
        sub_df = st.session_state.full_df[st.session_state.full_df['id'] == sid].sort_values('date')
        if sub_df.empty: continue
        fig = go.Figure()
        y_val = sub_df[y_col] / 1000
        fig.add_trace(go.Bar(x=sub_df['date'], y=y_val, marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val], hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"))
        
        # 【關鍵修正】標題顯示：【代號 名稱】
        fig.update_layout(title=f"【{sid} {st.session_state.summary[sid]['name']}】{sel_label} (張)", template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # 【關鍵修正】報告摘要顯示中文名稱
    report = f"【期間：{info['start']} ~ {info['end']}】\n有效交易日：{info['days']} 天\n" + "="*30 + "\n"
    for t_obj in st.session_state.targets:
        sid = t_obj["id"]
        if sid in st.session_state.summary:
            val = st.session_state.summary[sid][{'三大法人總和':'tot','外資':'f','投信':'it','自營商':'d'}[sel_label]]
            report += f"{sid} {st.session_state.summary[sid]['name']}: {val//1000:+,} 張\n"
    st.code(report, language="text")
