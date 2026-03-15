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

st.markdown("""
    <style>
    footer {visibility: hidden;}
    .status-box { 
        background-color: #1e1e1e; padding: 15px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #3b82f6; color: #ffffff; font-size: 14px; line-height: 1.6;
    }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] { background-color: #3b82f6 !important; color: white !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        .stButton button { padding: 4px 0px !important; font-size: 13px !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. API 函數庫 (名稱校對優化) ---

@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    """精準對接證交所 API 並加入瀏覽器偽裝，防止被擋導致『未知股票』"""
    stock_id = str(stock_id).strip()
    url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        resp = requests.get(url, headers=headers, timeout=5).json()
        if resp.get("suggestions") and resp["suggestions"][0] != "No Data Found":
            # 取得 "2603\t長榮" 取後半部
            return resp["suggestions"][0].split("\t")[1]
    except:
        pass
    # 備用方案：常見權值股手動校對，確保核心股票不變未知
    backup_dict = {"2603": "長榮", "2609": "陽明", "2615": "萬海", "2330": "台積電", "2317": "鴻海"}
    return backup_dict.get(stock_id, f"代號 {stock_id}")

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

# --- 3. 股票清單與 Cookie 管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

def save_user_lists(lists):
    cookie_manager.set("user_stock_lists", json.dumps(lists), key="save_cookie")

user_custom_lists = load_user_lists()
DEFAULT_LISTS = {"🔥 航運三雄": "2603, 2609, 2615", "🤖 AI 伺服器": "2382, 3231, 2376"}
all_lists = {**DEFAULT_LISTS, **user_custom_lists}

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")

st.subheader("1. 查詢目標")
selected_list = st.selectbox("載入組合", ["自訂輸入..."] + list(all_lists.keys()))
initial_stocks = all_lists[selected_list] if selected_list != "自訂輸入..." else "2603, 2609, 2615"
stock_input = st.text_input("股票代號 (逗號分隔)", value=initial_stocks)

with st.expander("💾 儲存 / 刪除專屬清單"):
    new_name = st.text_input("組合名稱", placeholder="我的私房股")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存"):
            if new_name:
                user_custom_lists[new_name] = stock_input
                save_user_lists(user_custom_lists)
                st.success("已儲存"); time.sleep(0.5); st.rerun()
    with c2:
        if st.button("❌ 刪除"):
            if selected_list in user_custom_lists:
                del user_custom_lists[selected_list]
                save_user_lists(user_custom_lists)
                st.success("已刪除"); time.sleep(0.5); st.rerun()

st.subheader("2. 查詢區間")
# 強勢回歸：4x4 快速區間按鈕
presets = [
    [("1天", 1), ("2天", 2), ("3天", 3), ("4天", 4)],
    [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
    [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)],
    [("1年", 365), ("2年", 730), ("3年", 1095), ("5年", 1825)]
]

if 'label' not in st.session_state:
    st.session_state.label = "2周"
    st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=13)

for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        is_active = (st.session_state.label == label)
        if cols[i].button(label, type="primary" if is_active else "secondary", use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())

run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)
st.divider()

# --- 5. 執行分析與視覺化 ---
if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    if not targets:
        st.warning("⚠️ 請輸入代號")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        summary = {}
        results = []
        start_time = time.time()
        
        for idx, sid in enumerate(targets):
            # 抓取名稱
            sname = get_stock_name(sid)
            status_area.markdown(f'<div class="status-box">🔍 正在校對：<b>{sname} ({sid})</b></div>', unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(sid, start_date, end_date)
            if df is not None and not df.empty:
                results.append(df)
                summary[sid] = {"name": sname, "f": df['f_net'].sum(), "it": df['it_net'].sum(), "d": df['d_net'].sum(), "tot": df['total_net'].sum()}
            progress_bar.progress((idx+1)/len(targets))
            # 微小延遲避免 API 被鎖
            time.sleep(0.1)

        status_area.empty(); progress_bar.empty()
        if results:
            st.session_state.full_df, st.session_state.summary, st.session_state.targets = pd.concat(results), summary, targets
            st.session_state.analysis_info = {"days": st.session_state.full_df['date'].nunique()}
            st.session_state.has_run = True

if st.session_state.get('has_run'):
    st.success(f"✅ 完成！涵蓋 {st.session_state.analysis_info['days']} 個交易日")
    sel_label = st.radio("切換檢視", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和":"total_net", "外資":"f_net", "投信":"it_net", "自營商":"d_net"}[sel_label]
    
    for sid in st.session_state.targets:
        if sid not in st.session_state.summary: continue
        sub_df = st.session_state.full_df[st.session_state.full_df['id'] == sid].sort_values('date')
        name = st.session_state.summary[sid]['name']
        
        fig = go.Figure()
        y_val = sub_df[y_col] / 1000
        fig.add_trace(go.Bar(x=sub_df['date'], y=y_val, marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val], hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"))
        # 標題校對：【名稱 (代碼)】
        fig.update_layout(title=f"【{name} ({sid})】{sel_label} (張)", template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10), xaxis=dict(tickformat="%m/%d"))
        st.plotly_chart(fig, use_container_width=True)

    # 報告區
    report = f"【會診摘要】\n" + "="*30 + "\n"
    for s in st.session_state.targets:
        if s in st.session_state.summary:
            info = st.session_state.summary[s]
            val = info[{'三大法人總和':'tot','外資':'f','投信':'it','自營商':'d'}[sel_label]]
            report += f"{info['name']} ({s}): {val//1000:+,} 張\n"
    st.code(report, language="text")
