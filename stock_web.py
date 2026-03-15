import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import os
import time

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", layout="centered")

# CSS 修正：暴力破解 Streamlit 手機版換行限制與美化狀態框
st.markdown("""
    <style>
    footer {visibility: hidden;}
    
    /* 狀態框樣式升級：加入更清楚的層次 */
    .status-box { 
        background-color: #1e1e1e; 
        padding: 15px; 
        border-radius: 8px; 
        margin-bottom: 10px; 
        border-left: 5px solid #ff4b4b; /* 改用醒目的紅色邊條 */
        color: #ffffff;
        font-size: 15px;
        line-height: 1.6;
    }
    .status-box hr {
        margin: 8px 0;
        border: none;
        border-top: 1px solid #444;
    }
    
    /* Toggle 置中 */
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    
    /* 【終極排版鎖定】無視內部標籤變動，強制水平等分 */
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

# --- 2. 雲端緩存與 FinMind API 策略 ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
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
                if col not in pivot_df.columns:
                    pivot_df[col] = 0
                    
            pivot_df['total_net'] = pivot_df['f_net'] + pivot_df['it_net'] + pivot_df['d_net']
            pivot_df = pivot_df.reset_index()
            pivot_df['id'] = stock_id
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
        except: return {"常用航運": "2603, 2609, 2615"}
    return {"常用航運": "2603, 2609, 2615"}

def save_lists(lists):
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(lists, f, ensure_ascii=False, indent=4)

if 'custom_lists' not in st.session_state:
    st.session_state.custom_lists = load_lists()

# --- 4. 全新手機版 UI ---
st.title("📊 三大法人籌碼變化")

# [區塊 1：查詢目標]
st.subheader("1. 查詢目標")
list_names = list(st.session_state.custom_lists.keys())
selected_list = st.selectbox("載入常用清單", ["自訂輸入..."] + list_names)

initial_stocks = "2603, 2609, 2615"
if selected_list != "自訂輸入...":
    initial_stocks = st.session_state.custom_lists[selected_list]

stock_input = st.text_input("股票代號 (請用逗號分隔)", value=initial_stocks)

with st.expander("💾 儲存 / 刪除目前清單"):
    new_list_name = st.text_input("組合名稱", placeholder="例如: 航運三雄")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存清單"):
            if new_list_name and stock_input:
                st.session_state.custom_lists[new_list_name] = stock_input
                save_lists(st.session_state.custom_lists)
                st.rerun()
    with c2:
        if st.button("❌ 刪除清單"):
            if selected_list != "自訂輸入...":
                del st.session_state.custom_lists[selected_list]
                save_lists(st.session_state.custom_lists)
                st.rerun()

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

# 【重點更新】動態高亮目前選擇的按鈕
for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        # 如果該按鈕是目前選中的 label，就設為 primary (亮色)
        is_active = (st.session_state.get('label') == label)
        btn_type = "primary" if is_active else "secondary"
        
        if cols[i].button(label, type=btn_type, use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun() # 強制刷新畫面，讓按鈕顏色瞬間改變

# 保持上下排列的日期輸入框
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
            
            # 【重點更新】計算 ETA (預估剩餘時間)
            elapsed = time.time() - start_time_exec
            avg_time_per_task = elapsed / completed if completed > 0 else 0
            eta_seconds = int(avg_time_per_task * (total_tasks - completed))
            
            # 【重點更新】詳細的查詢條件與進度面板
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
