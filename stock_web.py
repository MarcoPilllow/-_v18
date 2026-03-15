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

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

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

# 【全新加入】抓取成交量與融資券餘額 (FinMind)
@st.cache_data(ttl=3600)
def fetch_finmind_secondary(stock_id, start_date, end_date):
    sd_str = start_date.strftime("%Y-%m-%d")
    ed_str = end_date.strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    
    try:
        # 1. 抓取成交量
        res_p = requests.get(url, params={"dataset": "TaiwanStockPrice", "data_id": str(stock_id), "start_date": sd_str, "end_date": ed_str}, timeout=10).json()
        df_p = pd.DataFrame(res_p.get('data', []))
        
        # 2. 抓取融資融券
        res_m = requests.get(url, params={"dataset": "TaiwanStockMarginPurchaseShortSale", "data_id": str(stock_id), "start_date": sd_str, "end_date": ed_str}, timeout=10).json()
        df_m = pd.DataFrame(res_m.get('data', []))

        df_merged = pd.DataFrame()
        
        if not df_p.empty:
            df_p['Volume'] = df_p['Trading_Volume'] / 1000 # 換算成張
            df_merged = df_p[['date', 'Volume']]
            
        if not df_m.empty:
            df_m['Margin_Bal'] = df_m['MarginPurchaseTodayBalance'] / 1000 # 融資餘額(張)
            df_m['Short_Bal'] = df_m['ShortSaleTodayBalance'] / 1000 # 融券餘額(張)
            df_m_sub = df_m[['date', 'Margin_Bal', 'Short_Bal']]
            
            if df_merged.empty:
                df_merged = df_m_sub
            else:
                df_merged = pd.merge(df_merged, df_m_sub, on='date', how='outer')
                
        if not df_merged.empty:
            df_merged['date'] = pd.to_datetime(df_merged['date']).dt.strftime('%Y-%m-%d')
            df_merged['id'] = stock_id
            return df_merged
            
    except: return None
    return None

@st.cache_data(ttl=3600)
def fetch_latest_top20():
    dynamic_lists = {}
    today = datetime.date.today()
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5: continue
        date_str = d.strftime("%Y%m%d")
        url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX20?response=json&date={date_str}"
        try:
            resp = requests.get(url, timeout=5).json()
            if resp.get("stat") == "OK" and "data" in resp:
                top20_ids = [str(row[1]) for row in resp["data"]]
                dynamic_lists[f"🚀 最新 ({d.strftime('%m/%d')})：全市場爆量 Top 20"] = ", ".join(top20_ids)
                tech = [s for s in top20_ids if s.startswith(('23', '24', '3', '5', '6', '8'))]
                fin = [s for s in top20_ids if s.startswith('28')]
                ship = [s for s in top20_ids if s.startswith('26')]
                if tech: dynamic_lists[f"🚀 最新：爆量電子科技"] = ", ".join(tech)
                if fin: dynamic_lists[f"🚀 最新：爆量金融保險"] = ", ".join(fin)
                if ship: dynamic_lists[f"🚀 最新：爆量航運業"] = ", ".join(ship)
                break
        except: continue
    return dynamic_lists

@st.cache_data(ttl=43200)
def scrape_concept_stocks():
    scraped_lists = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = "https://tw.stock.yahoo.com/class/"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            pass 
    except: pass

    if not scraped_lists:
        scraped_lists = {
            "🌐 網摘：AI 伺服器概念": "2382, 3231, 2376, 6669, 2356",
            "🌐 網摘：矽光子/CPO 概念": "3450, 3163, 3363, 6442, 4979",
            "🌐 網摘：重電綠能大軍": "1503, 1513, 1514, 1519, 6806",
            "🌐 網摘：高股息 ETF 成分股": "2603, 3034, 2303, 2891, 2454"
        }
    return scraped_lists

# --- 3. 股票清單管理 ---
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

dynamic_top20 = fetch_latest_top20()
scraped_concepts = scrape_concept_stocks()
user_custom_lists = load_user_lists()
all_lists = {**dynamic_top20, **scraped_concepts, **user_custom_lists}

# --- 4. 全新手機版 UI ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
list_names = list(all_lists.keys())
selected_list = st.selectbox("載入組合 (支援最新爆量、網路概念股與自訂)", ["自訂輸入..."] + list_names)

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
            elif selected_list in scraped_concepts or selected_list in dynamic_top20:
                st.error("⚠️ 系統抓取的清單無法刪除喔！")
            else:
                st.warning("請先選擇要刪除的自訂清單。")

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
            avg = elapsed / completed if completed > 0 else 0
            eta_seconds = int(avg * (total_tasks - completed))
            
            status_area.markdown(f"""
                <div class="status-box">
                    <b>🔍 查詢條件：</b> {st.session_state.get('label', '自定義')} ({start_date.strftime('%m/%d')} ~ {end_date.strftime('%m/%d')})<br>
                    <hr>
                    <b>⚡ 處理進度：</b> [{completed} / {total_tasks}] 正在並行解析 {stock}<br>
                    <b>⏱️ 預估剩餘：</b> {eta_seconds} 秒
                </div>
            """, unsafe_allow_html=True)
            
            stock_name = get_stock_name(stock)
            summary[stock]['name'] = stock_name
            
            # 分別抓取兩組資料
            df_inst = fetch_finmind_institutional(stock, start_date, end_date)
            df_sec = fetch_finmind_secondary(stock, start_date, end_date)
            
            if df_inst is not None and not df_inst.empty:
                # 兩組合併
                if df_sec is not None and not df_sec.empty:
                    df = pd.merge(df_inst, df_sec, on=['date', 'id'], how='left')
                else:
                    df = df_inst.copy()
                    for col in ['Volume', 'Margin_Bal', 'Short_Bal']: df[col] = 0
                
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
    
    # 建立主副圖的 Radio 切換器
    st.subheader("⚙️ 圖表顯示設定")
    c1, c2 = st.columns(2)
    with c1:
        metric_options = {"三大法人總和": "total_net", "外資": "f_net", "投信": "it_net", "自營商": "d_net"}
        selected_label = st.radio("🔴 主圖：法人籌碼", list(metric_options.keys()))
        y_column = metric_options[selected_label]
        
    with c2:
        sec_metric_options = {"無 (僅顯示法人)": None, "📊 成交總量 (張)": "Volume", "💰 融資餘額 (張)": "Margin_Bal", "📉 融券餘額 (張)": "Short_Bal"}
        selected_sec_label = st.radio("🟡 副圖：附加折線", list(sec_metric_options.keys()))
        y_col_sec = sec_metric_options[selected_sec_label]
    
    st.divider()
    
    full_df = st.session_state.full_df
    summary = st.session_state.summary
    targets = st.session_state.targets

    for stock in targets:
        sub_df = full_df[full_df['id'] == stock].sort_values('date')
        if sub_df.empty: continue
        
        # 啟用雙 Y 軸 (Secondary Y)
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        y_data = sub_df[y_column] / 1000
        
        # 繪製主圖：籌碼柱狀圖
        fig.add_trace(go.Bar(
            x=sub_df['date'],
            y=y_data,
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_data],
            name=selected_label,
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ), secondary_y=False)
        
        # 繪製副圖：附加指標折線圖 (如果使用者有選)
        if y_col_sec and y_col_sec in sub_df.columns:
            # 根據指標種類給予不同的折線顏色
            sec_color = "#f1c40f" if "融資" in selected_sec_label else "#3498db" if "融券" in selected_sec_label else "#ecf0f1"
            clean_sec_name = selected_sec_label.split(" ")[1] # 移除 Emoji 以維持圖例乾淨
            
            fig.add_trace(go.Scatter(
                x=sub_df['date'],
                y=sub_df[y_col_sec],
                mode='lines+markers',
                line=dict(color=sec_color, width=2.5),
                marker=dict(size=6),
                name=clean_sec_name,
                hovertemplate="日期: %{x}<br>數值: %{y:,.0f} 張<extra></extra>"
            ), secondary_y=True)
        
        # 綜合 Layout 設定
        fig.update_layout(
            title=f"【{summary[stock]['name']}】籌碼與指標診斷",
            template="plotly_dark",
            margin=dict(l=10, r=10, t=50, b=10), height=350, xaxis=dict(tickformat="%m/%d"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # 設定雙 Y 軸的樣式 (隱藏副圖網格線，保持畫面乾淨)
        fig.update_yaxes(title_text="法人張數", secondary_y=False, showgrid=True, gridcolor='#333333')
        if y_col_sec:
            fig.update_yaxes(title_text=clean_sec_name, secondary_y=True, showgrid=False)
            
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
