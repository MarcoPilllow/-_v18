import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import time
import extra_streamlit_components as stx
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

# CSS 修正：優化排版與「按鈕護眼配色」
st.markdown("""
    <style>
    footer {visibility: hidden;}
    
    .status-box { 
        background-color: #1e1e1e; 
        padding: 15px; 
        border-radius: 8px; 
        margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; 
        color: #ffffff;
        font-size: 15px;
        line-height: 1.6;
    }
    .status-box hr { margin: 8px 0; border: none; border-top: 1px solid #444; }
    
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    
    button[kind="primary"] {
        background-color: #3b82f6 !important; 
        border-color: #3b82f6 !important;
        color: white !important;
    }
    button[kind="primary"]:hover {
        background-color: #2563eb !important; 
        border-color: #2563eb !important;
    }
    button[kind="primary"]:focus {
        box-shadow: 0 0 0 0.2rem rgba(59, 130, 246, 0.5) !important; 
    }
    
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            display: flex !important;
            gap: 4px !important;
        }
        [data-testid="stHorizontalBlock"] > div {
            flex: 1 1 0 !important;
            min-width: 0 !important;
            padding: 0 !important; 
        }
        .stButton button {
            padding: 4px 0px !important;
            font-size: 13px !important;
            width: 100% !important;
        }
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
            def classify_investor(name):
                n = str(name).lower()
                if 'foreign' in n or '外資' in n: return 'f_net'
                elif 'trust' in n or '投信' in n: return 'it_net'
                elif 'dealer' in n or '自營' in n: return 'd_net'
                return 'other'
            df['type'] = df['name'].apply(classify_investor)
            pivot_df = df.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
            for col in ['f_net', 'it_net', 'd_net']:
                if col not in pivot_df.columns: pivot_df[col] = 0
            pivot_df['total_net'] = pivot_df['f_net'] + pivot_df['it_net'] + pivot_df['d_net']
            pivot_df = pivot_df.reset_index()
            pivot_df['id'] = stock_id
            pivot_df['date'] = pd.to_datetime(pivot_df['date']).dt.strftime('%Y-%m-%d')
            return pivot_df
    except: return None
    return None

# 【新增功能】多日動態爆量雷達 (快取 12 小時)
@st.cache_data(ttl=43200)
def fetch_dynamic_hot_stocks():
    dynamic_lists = {}
    today = datetime.date.today()
    
    # 準備過去 40 天的日期，扣除週末，取前 20 個「可能有交易」的日子
    past_days = [today - datetime.timedelta(days=i) for i in range(40)]
    possible_trading_days = [d for d in past_days if d.weekday() < 5][:20]

    def fetch_single_day(d):
        date_str = d.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX20?response=json&date={date_str}"
        try:
            resp = requests.get(url, timeout=5).json()
            if resp.get("stat") == "OK" and "data" in resp:
                res = []
                for row in resp["data"]:
                    sid = str(row[1])
                    vol = int(row[3].replace(',', '')) # 取得成交量
                    res.append((sid, vol))
                return d, res
        except: pass
        return d, []

    results = {}
    # 溫和地使用並行抓取，避免被證交所鎖 IP
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_single_day, d): d for d in possible_trading_days}
        for future in as_completed(futures):
            d, data = future.result()
            if data: results[d] = data
            time.sleep(0.1)

    if not results: return {}

    # 確保日期排序 (由新到舊)
    sorted_dates = sorted(results.keys(), reverse=True)
    latest_date = sorted_dates[0]
    
    # --- 輔助分類函數 ---
    def categorize(prefix, ids, emoji):
        tech = [s for s in ids if s.startswith(('23', '24', '3', '5', '6', '8'))]
        fin = [s for s in ids if s.startswith('28')]
        ship = [s for s in ids if s.startswith('26')]
        if tech: dynamic_lists[f"{emoji} {prefix}：電子科技"] = ", ".join(tech)
        if fin: dynamic_lists[f"{emoji} {prefix}：金融保險"] = ", ".join(fin)
        if ship: dynamic_lists[f"{emoji} {prefix}：航運業"] = ", ".join(ship)

    # 1. 🚀 近一日
    latest_top20 = [sid for sid, vol in results[latest_date]]
    dynamic_lists["🚀 近一日：全市場爆量 Top 20"] = ", ".join(latest_top20)
    categorize("近一日爆量", latest_top20, "🚀")

    # 2. 🚀🚀 近一週 (前 5 個有效交易日累計)
    week_dates = sorted_dates[:5]
    week_vols = {}
    for d in week_dates:
        for sid, vol in results[d]:
            week_vols[sid] = week_vols.get(sid, 0) + vol
    week_top20 = [sid for sid, vol in sorted(week_vols.items(), key=lambda x: x[1], reverse=True)[:20]]
    if week_top20:
        dynamic_lists["🚀🚀 近一週：累計爆量 Top 20"] = ", ".join(week_top20)
        categorize("近一週爆量", week_top20, "🚀🚀")

    # 3. 🚀🚀🚀 近一月 (最多前 20 個有效交易日累計)
    month_vols = {}
    for d in sorted_dates:
        for sid, vol in results[d]:
            month_vols[sid] = month_vols.get(sid, 0) + vol
    month_top20 = [sid for sid, vol in sorted(month_vols.items(), key=lambda x: x[1], reverse=True)[:20]]
    if month_top20:
        dynamic_lists["🚀🚀🚀 近一月：累計爆量 Top 20"] = ", ".join(month_top20)
        categorize("近一月爆量", month_top20, "🚀🚀🚀")

    return dynamic_lists

# --- 3. 股票清單管理 (SaaS 升級版) ---
DEFAULT_CONCEPT_STOCKS = {
    "🔥 熱門：航運三雄": "2603, 2609, 2615",
    "🤖 趨勢：AI 伺服器": "2382, 3231, 2376, 6669",
    "🏭 穩健：經典傳產 (塑化/紡織)": "1326, 1402, 2002",
    "⚡ 政策：重電綠能": "1503, 1513, 1514, 1519",
    "💰 存股：金融金控": "2881, 2882, 2886, 2891"
}

if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    if val and isinstance(val, str):
        try: return json.loads(val)
        except: return {}
    elif val and isinstance(val, dict): return val
    return {}

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

# 獲取動態 Top20、使用者自訂、內建清單並合併
dynamic_stocks = fetch_dynamic_hot_stocks()
user_custom_lists = load_user_lists()
# 順序：動態雷達 -> 靜態罐頭 -> 個人私房股
all_lists = {**dynamic_stocks, **DEFAULT_CONCEPT_STOCKS, **user_custom_lists}

# --- 4. 全新手機版 UI ---
st.title("📊 三大法人籌碼變化")

# [區塊 1：查詢目標]
st.subheader("1. 查詢目標")
list_names = list(all_lists.keys())
selected_list = st.selectbox("載入組合 (支援動態雷達、概念股與自訂)", ["自訂輸入..."] + list_names)

initial_stocks = "2603, 2609, 2615"
if selected_list != "自訂輸入...":
    initial_stocks = all_lists[selected_list]

stock_input = st.text_input("股票代號 (請用逗號分隔)", value=initial_stocks)

with st.expander("💾 儲存 / 刪除專屬清單 (將存於您的瀏覽器)"):
    new_list_name = st.text_input("組合名稱", placeholder="例如: 我的私房股")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存清單"):
            if new_list_name and stock_input:
                user_custom_lists[new_list_name] = stock_input
                save_user_lists(user_custom_lists)
                st.success("✅ 已成功存入您的瀏覽器！")
                time.sleep(0.5)
                st.rerun()
    with c2:
        if st.button("❌ 刪除清單"):
            if selected_list in user_custom_lists:
                del user_custom_lists[selected_list]
                save_user_lists(user_custom_lists)
                st.success("🗑️ 已從您的瀏覽器刪除！")
                time.sleep(0.5)
                st.rerun()
            elif selected_list in DEFAULT_CONCEPT_STOCKS or selected_list in dynamic_stocks:
                st.error("⚠️ 系統內建與動態抓取的清單無法刪除喔！")
            else:
                st.warning("請先選擇要刪除的自訂清單。")

# [區塊 2：查詢區間]
st.subheader("2. 查詢區間")

presets = [
    [("1天", 1), ("2天", 2), ("3天", 3), ("4天", 4)],
    [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
    [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)],
    [("1年", 365), ("2年", 730), ("3年", 1095), ("5年", 1825)]
]

if 'start_date' not in st.session_state:
    st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)
    st.session_state.label = "自定義"

for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        is_active = (st.session_state.get('label') == label)
        btn_type = "primary" if is_active else "secondary"
        
        if cols[i].button(label, type=btn_type, use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

# [區塊 3：執行按鈕]
run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 數據分析與視覺化 ---
if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    
    if not targets:
        st.warning("⚠️ 請輸入至少一檔股票代號。")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        results_list = []
        
        total_tasks = len(targets)
        start_time_exec = time.time()
        
        for idx, stock in enumerate(targets):
            completed = idx + 1
            
            elapsed = time.time() - start_time_exec
            avg_time_per_task = elapsed / completed if completed > 0 else 0
            eta_seconds = int(avg_time_per_task * (total_tasks - completed))
            
            status_area.markdown(f"""
                <div class="status-box">
                    <b>🔍 查詢條件：</b> {st.session_state.get('label', '自定義')} ({start_date.strftime('%m/%d')} ~ {end_date.strftime('%m/%d')})<br>
                    <hr>
                    <b>⚡ 處理進度：</b> [{completed} / {total_tasks}] 正在解析 {stock}<br>
                    <b>⏱️ 預估剩餘：</b> {eta_seconds} 秒
                </div>
            """, unsafe_allow_html=True)
            
            stock_name = get_stock_name(stock)
            summary[stock]['name'] = stock_name
            df = fetch_finmind_institutional(stock, start_date, end_date)
            
            if df is not None and not df.empty:
                results_list.append(df)
                summary[stock]['f'] = df['f_net'].sum()
                summary[stock]['it'] = df['it_net'].sum()
                summary[stock]['d'] = df['d_net'].sum()
                summary[stock]['tot'] = df['total_net'].sum()
                
            progress_bar.progress(completed / total_tasks)

        status_area.empty()
        progress_bar.empty()

        if results_list:
            full_df = pd.concat(results_list)
            actual_trading_days = full_df['date'].nunique()
            
            st.session_state.full_df = full_df
            st.session_state.summary = summary
            st.session_state.targets = targets
            st.session_state.analysis_info = {
                "start": start_date, "end": end_date, 
                "label": st.session_state.get('label', '自定義'), 
                "days": actual_trading_days
            }
            st.session_state.has_run = True
        else:
            st.error("❌ 抓取失敗，區間內可能無資料。")
            st.session_state.has_run = False

# [區塊 6：圖表與報告渲染]
if st.session_state.get('has_run', False):
    info = st.session_state.analysis_info
    st.success(f"✅ 高效分析完成！共涵蓋 {info['days']} 個有效交易日")
    
    metric_options = {
        "三大法人總和": "total_net",
        "外資": "f_net",
        "投信": "it_net",
        "自營商": "d_net"
    }
    
    selected_label = st.radio(
        "🔄 切換檢視數據", 
        list(metric_options.keys()), 
        horizontal=True,
        label_visibility="collapsed"
    )
    y_column = metric_options[selected_label]
    
    full_df = st.session_state.full_df
    summary = st.session_state.summary
    targets = st.session_state.targets

    for stock in targets:
        sub_df = full_df[full_df['id'] == stock].sort_values('date')
        if sub_df.empty: continue
        fig = go.Figure()
        
        y_data = sub_df[y_column] / 1000
        
        fig.add_trace(go.Bar(
            x=sub_df['date'],
            y=y_data,
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_data],
            name="張數",
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        
        fig.update_layout(
            title=f"【{summary[stock]['name']}】{selected_label} (張)",
            template="plotly_dark",
            margin=dict(l=10, r=10, t=50, b=10), height=300, xaxis=dict(tickformat="%m/%d")
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("📋 深度會診報告")
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n【有效交易日：{info['days']} 天】\n" + "═"*45 + "\n\n"
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for s in targets: 
            report += f"{summary[s]['name']}: {summary[s][key]//1000:+.0f} 張\n"
        report += "\n"
    st.code(report, language="text")
