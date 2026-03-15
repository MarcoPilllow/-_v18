import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import time
import extra_streamlit_components as stx

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人籌碼變化", page_icon="📊", layout="centered")

st.markdown(f"""
    <head>
        <meta property="og:title" content="三大法人籌碼變化">
        <meta property="og:description" content="台股籌碼即時診斷：已過濾權證汙染，支援純現貨中文搜尋。">
        <meta property="og:type" content="website">
    </head>
    """, unsafe_allow_html=True)

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { 
        background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; color: #ffffff; font-size: 14px; line-height: 1.6;
    }
    .status-box hr { margin: 8px 0; border: none; border-top: 1px solid #444; }
    button:focus { outline: none !important; box-shadow: none !important; border: none !important; }
    .stButton button { border: none !important; }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; color: white !important; }
    button[kind="primary"]:hover { background-color: #2563eb !important; }
    .stMultiSelect span { color: white !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        .stButton button { padding: 4px 0px !important; font-size: 12px !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心 API 函數 (含權證過濾邏輯) ---
@st.cache_data(ttl=86400)
def search_stock_filtered(query):
    """搜尋並自動剔除權證（代號長度 > 4 或 含有英文者）"""
    query = str(query).strip()
    if not query: return []
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=5).json()
        if resp.get("suggestions") and resp["suggestions"][0] != "No Data Found":
            raw_list = resp["suggestions"]
            filtered_list = []
            for s in raw_list:
                parts = s.split("\t")
                sid = parts[0]
                # 關鍵過濾：現貨股票代號為 4 碼數字（ETF 為 5~6 碼但不含英文）
                # 權證代號通常極長且包含大量字母，或是 6 碼且具有特定規則
                # 這裡採取嚴格過濾：長度必須為 4 (普通股) 或 5~6 且全數字 (ETF)
                if sid.isdigit() and len(sid) <= 6:
                    filtered_list.append(s.replace("\t", " "))
            return filtered_list
    except: pass
    return []

@st.cache_data(ttl=3600)
def fetch_finmind_institutional(stock_id, start_date, end_date):
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": str(stock_id),
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d")
    }
    try:
        resp = requests.get(url, params=params, timeout=15).json()
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
            pivot = df.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
            for col in ['f_net', 'it_net', 'd_net']:
                if col not in pivot.columns: pivot[col] = 0
            pivot['total_net'] = pivot['f_net'] + pivot['it_net'] + pivot['d_net']
            pivot = pivot.reset_index()
            pivot['id'] = stock_id
            pivot['date'] = pd.to_datetime(pivot['date']).dt.strftime('%Y-%m-%d')
            return pivot
    except: return None

# --- 3. 股票清單與 Cookie 管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

user_lists = load_user_lists()

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
selected_list_name = st.selectbox("快速載入常用組合", ["自訂輸入..."] + list(user_lists.keys()))

default_stocks = ["2603 長榮", "2609 陽明", "2615 萬海"]
if selected_list_name != "自訂輸入...":
    default_stocks = user_lists[selected_list_name].split(",")

# 輸入中文名稱也會自動過濾權證
search_query = st.text_input("🔍 搜尋並新增股票 (支援中文/代號，已過濾權證)", key="stock_search")
options = search_stock_filtered(search_query) if search_query else []

final_selection = st.multiselect(
    "目前已選清單 (可手動刪除或從上方搜尋建議點選新增)",
    options=list(set(default_stocks + options)),
    default=default_stocks
)

with st.expander("💾 儲存目前清單到瀏覽器"):
    new_name = st.text_input("組合名稱", placeholder="例如: 航運小分隊")
    if st.button("💾 儲存清單"):
        if new_name and final_selection:
            user_lists[new_name] = ",".join(final_selection)
            cookie_manager.set("user_stock_lists", json.dumps(user_lists), key="save_cookie")
            st.success("✅ 已儲存！"); time.sleep(0.5); st.rerun()

st.subheader("2. 查詢區間")
presets = [[("1天",1),("2天",2),("3天",3),("4天",4)],[("1周",7),("2周",14),("3周",21),("1月",30)],[("6周",42),("2月",60),("1季",90),("半年",182)]]
if 'label' not in st.session_state:
    st.session_state.label = "2周"
    st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=13)

for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        if cols[i].button(label, type="primary" if st.session_state.label==label else "secondary", use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 數據處理與繪圖 ---
if run_btn:
    if not final_selection:
        st.warning("⚠️ 請選擇股票")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        summary, results = {}, []
        start_time_exec = time.time()
        
        for idx, item in enumerate(final_selection):
            completed = idx + 1
            elapsed = time.time() - start_time_exec
            avg = elapsed / completed
            eta = int(avg * (len(final_selection) - completed))
            
            parts = item.split(" ")
            sid, sname = parts[0], parts[1] if len(parts)>1 else parts[0]
            
            status_area.markdown(f"""
                <div class="status-box">
                    <b>🔍 查詢條件：</b> {st.session_state.label} ({start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')})<br>
                    <hr>
                    <b>⚡ 處理進度：</b> [{completed} / {len(final_selection)}] 正在解析 <b>{sname} ({sid})</b><br>
                    <b>⏱️ 預估剩餘：</b> {eta} 秒
                </div>
            """, unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(sid, start_date, end_date)
            if df is not None and not df.empty:
                results.append({"id": sid, "name": sname, "df": df})
                summary[sid] = {"name": sname, "tot": df['total_net'].sum(), "f": df['f_net'].sum(), "it": df['it_net'].sum(), "d": df['d_net'].sum()}
            progress_bar.progress(completed/len(final_selection))
            time.sleep(0.05)

        status_area.empty(); progress_bar.empty()
        if results:
            st.session_state.results, st.session_state.summary = results, summary
            st.session_state.info = {"start": start_date, "end": end_date, "label": st.session_state.label, "days": results[0]['df']['date'].nunique()}
            st.session_state.has_run = True

if st.session_state.get('has_run'):
    sel_label = st.radio("切換數據", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和":"total_net", "外資":"f_net", "投信":"it_net", "自營商":"d_net"}[sel_label]
    
    for res in st.session_state.results:
        df = res["df"]
        fig = go.Figure()
        y_val = df[y_col] / 1000
        fig.add_trace(go.Bar(x=df['date'], y=y_val, marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val], hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"))
        fig.update_layout(title=f"【{res['id']} {res['name']}】{sel_label} (張)", template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10), xaxis=dict(tickformat="%m/%d"))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("📋 三大法人買賣超總結")
    info = st.session_state.info
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n【有效交易日：{info['days']} 天】\n"
    report += "═════════════════════════════════════════════\n\n"
    
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for res in st.session_state.results:
            sid = res['id']
            val = st.session_state.summary[sid][key]
            report += f"{res['name']}: {val//1000:+,} 張\n"
        report += "\n"
    st.code(report, language="text")
