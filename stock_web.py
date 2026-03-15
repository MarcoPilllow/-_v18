import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import time
import extra_streamlit_components as stx

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

# --- 2. 雲端緩存與 FinMind API ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    """從證交所抓取股票名稱"""
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions") and resp["suggestions"][0] != "No Data Found":
            # 格式通常是 "2330\t台積電"，我們切分取第 2 個
            return resp["suggestions"][0].split("\t")[1]
    except:
        pass
    return str(stock_id) # 失敗則回傳代碼

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

# --- 3. 股票清單管理 (SaaS 升級版：Cookie 隔離 + 內建概念股) ---
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
    """從使用者的瀏覽器 Cookie 讀取專屬清單"""
    val = cookie_manager.get(cookie="user_stock_lists")
    if val and isinstance(val, str):
        try: return json.loads(val)
        except: return {}
    elif val and isinstance(val, dict):
        return val
    return {}

def save_user_lists(lists):
    """將自訂清單寫入使用者的瀏覽器 Cookie"""
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

user_custom_lists = load_user_lists()
all_lists = {**DEFAULT_CONCEPT_STOCKS, **user_custom_lists}

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
list_names = list(all_lists.keys())
selected_list = st.selectbox("載入組合 (支援內建概念股與您的自訂)", ["自訂輸入..."] + list_names)

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

st.subheader("2. 查詢區間")
presets = [
    [("1天", 1), ("2天", 2), ("3天", 3), ("4天", 4)],
    [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
    [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)]
]

if 'start_date' not in st.session_state:
    st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)
    st.session_state.label = "自定義"

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
        st.warning("⚠️ 請輸入至少一檔股票代號。")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        summary = {t: {'name': '', 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        results_list = []
        start_time_exec = time.time()
        
        for idx, stock in enumerate(targets):
            completed = idx + 1
            elapsed = time.time() - start_time_exec
            avg = elapsed / completed if completed > 0 else 0
            eta = int(avg * (len(targets) - completed))
            
            # 抓取中文名稱
            stock_name = get_stock_name(stock)
            summary[stock]['name'] = stock_name
            
            status_area.markdown(f"""
                <div class="status-box">
                    <b>🔍 查詢條件：</b> {st.session_state.get('label', '自定義')} ({start_date.strftime('%m/%d')} ~ {end_date.strftime('%m/%d')})<br>
                    <hr>
                    <b>⚡ 處理進度：</b> [{completed} / {len(targets)}] 正在解析 <b>{stock_name} ({stock})</b><br>
                    <b>⏱️ 預估剩餘：</b> {eta} 秒
                </div>
            """, unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(stock, start_date, end_date)
            if df is not None and not df.empty:
                results_list.append(df)
                summary[stock]['f'] = df['f_net'].sum()
                summary[stock]['it'] = df['it_net'].sum()
                summary[stock]['d'] = df['d_net'].sum()
                summary[stock]['tot'] = df['total_net'].sum()
            progress_bar.progress(completed / len(targets))

        status_area.empty()
        progress_bar.empty()

        if results_list:
            st.session_state.full_df = pd.concat(results_list)
            st.session_state.summary = summary
            st.session_state.targets = targets
            st.session_state.analysis_info = {
                "start": start_date, "end": end_date, 
                "label": st.session_state.get('label', '自定義'), 
                "days": st.session_state.full_df['date'].nunique()
            }
            st.session_state.has_run = True
        else:
            st.error("❌ 抓取失敗，區間內可能無資料。")

# [區塊 6：圖表渲染]
if st.session_state.get('has_run', False):
    info = st.session_state.analysis_info
    st.success(f"✅ 高效分析完成！共涵蓋 {info['days']} 個有效交易日")
    
    selected_label = st.radio("🔄 切換檢視數據", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和": "total_net", "外資": "f_net", "投信": "it_net", "自營商": "d_net"}[selected_label]
    
    for stock in st.session_state.targets:
        sub_df = st.session_state.full_df[st.session_state.full_df['id'] == stock].sort_values('date')
        if sub_df.empty: continue
        
        name = st.session_state.summary[stock]['name']
        fig = go.Figure()
        y_val = sub_df[y_col] / 1000
        
        fig.add_trace(go.Bar(
            x=sub_df['date'], y=y_val, 
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val],
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        
        fig.update_layout(
            title=f"【{name} ({stock})】{selected_label} (張)", 
            template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10),
            xaxis=dict(tickformat="%m/%d")
        )
        st.plotly_chart(fig, use_container_width=True)

    # 底部報告也加入名稱
    st.divider()
    report = f"【期間：{info['start']} ~ {info['end']}】\n"
    for s in st.session_state.targets:
        sum_data = st.session_state.summary[s]
        report += f"{sum_data['name']} ({s}): {sum_data['tot']//1000:+,} 張\n"
    st.code(report, language="text")
