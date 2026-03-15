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
    .status-box hr { margin: 8px 0; border: none; border-top: 1px solid #444; }
    button:focus { outline: none !important; box-shadow: none !important; }
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    button[kind="primary"] {
        background-color: #3b82f6 !important; border: none !important; color: white !important;
    }
    button[kind="primary"]:hover { background-color: #2563eb !important; }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: row !important; display: flex !important; gap: 4px !important; }
        .stButton button { padding: 4px 0px !important; font-size: 12px !important; }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 名稱對照大數據優化 (一次性下載，徹底解決名字不顯示問題) ---
@st.cache_data(ttl=86400)
def load_all_stock_names():
    """從 FinMind 抓取全市場名稱清單，保證所有代號都能顯示中文"""
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        parameter = {"dataset": "TaiwanStockInfo"}
        resp = requests.get(url, params=parameter, timeout=15).json()
        if resp.get('status') == 200:
            df = pd.DataFrame(resp['data'])
            # 建立 { '2330': '台積電' } 字典
            return dict(zip(df['stock_id'], df['stock_name']))
    except:
        pass
    return {}

# 啟動時先載入全市場字典
stock_dict = load_all_stock_names()

def get_actual_name(sid):
    sid = str(sid).strip()
    return stock_dict.get(sid, f"代號 {sid}")

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

# --- 3. Cookie 清單管理 ---
if 'cookie_manager' not in st.session_state:
    st.session_state['cookie_manager'] = stx.CookieManager()
cookie_manager = st.session_state['cookie_manager']

def load_user_lists():
    val = cookie_manager.get(cookie="user_stock_lists")
    return json.loads(val) if val and isinstance(val, str) else (val if isinstance(val, dict) else {})

user_custom_lists = load_user_lists()
all_lists = {**{"🔥 航運三雄": "2603, 2609, 2615", "🤖 AI 伺服器": "2382, 3231, 2376"}, **user_custom_lists}

# --- 4. UI 介面 ---
st.title("📊 三大法人籌碼變化")
selected_list = st.selectbox("載入組合", ["自訂輸入..."] + list(all_lists.keys()))
initial_stocks = all_lists[selected_list] if selected_list != "自訂輸入..." else "2603, 2609, 2615"
stock_input = st.text_input("股票代號 (逗號分隔)", value=initial_stocks)

st.subheader("2. 查詢區間")
presets = [
    [("1天", 1), ("2天", 2), ("3天", 3), ("4天", 4)],
    [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
    [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)],
    [("1年", 365), ("2年", 730), ("3年", 1095), ("5年", 1825)]
]

if 'label' not in st.session_state:
    st.session_state.label, st.session_state.start_date = "2周", datetime.date.today() - datetime.timedelta(days=13)

for row in presets:
    cols = st.columns(4)
    for i, (label, days) in enumerate(row):
        if cols[i].button(label, type="primary" if st.session_state.label == label else "secondary", use_container_width=True):
            st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
            st.session_state.label = label
            st.rerun()

start_date = st.date_input("開始日期", st.session_state.start_date)
end_date = st.date_input("結束日期", datetime.date.today())
run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)

# --- 5. 執行分析 ---
if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    if targets:
        progress_bar = st.progress(0)
        status_area = st.empty()
        summary, results = {}, []
        start_time_exec = time.time()
        
        for idx, sid in enumerate(targets):
            completed = idx + 1
            avg = (time.time() - start_time_exec) / completed
            eta = int(avg * (len(targets) - completed))
            
            # 使用我們穩定的名稱對照表
            sname = get_actual_name(sid)
            
            status_area.markdown(f"""
                <div class="status-box">
                    <b>🔍 查詢條件：</b> {st.session_state.label} ({start_date} ~ {end_date})<br>
                    <hr>
                    <b>⚡ 處理進度：</b> [{completed} / {len(targets)}] 正在解析 <b>{sname} ({sid})</b><br>
                    <b>⏱️ 預估剩餘：</b> {eta} 秒
                </div>
            """, unsafe_allow_html=True)
            
            df = fetch_finmind_institutional(sid, start_date, end_date)
            if df is not None and not df.empty:
                results.append(df)
                summary[sid] = {"name": sname, "tot": df['total_net'].sum(), "f": df['f_net'].sum(), "it": df['it_net'].sum(), "d": df['d_net'].sum()}
            progress_bar.progress(completed/len(targets))

        status_area.empty(); progress_bar.empty()
        if results:
            st.session_state.full_df, st.session_state.summary, st.session_state.targets = pd.concat(results), summary, targets
            st.session_state.info = {"start": start_date, "end": end_date, "label": st.session_state.label, "days": pd.concat(results)['date'].nunique()}
            st.session_state.has_run = True

# --- 6. 渲染圖表與報告 ---
if st.session_state.get('has_run'):
    info = st.session_state.info
    st.success(f"✅ 完成！涵蓋 {info['days']} 個交易日")
    sel_label = st.radio("切換數據", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True, label_visibility="collapsed")
    y_col = {"三大法人總和":"total_net", "外資":"f_net", "投信":"it_net", "自營商":"d_net"}[sel_label]
    
    for sid in st.session_state.targets:
        if sid not in st.session_state.summary: continue
        sub_df = st.session_state.full_df[st.session_state.full_df['id'] == sid].sort_values('date')
        name = st.session_state.summary[sid]['name']
        fig = go.Figure()
        y_val = sub_df[y_col] / 1000
        fig.add_trace(go.Bar(x=sub_df['date'], y=y_val, marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_val], hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"))
        fig.update_layout(title=f"【{name} ({sid})】{sel_label} (張)", template="plotly_dark", height=300, margin=dict(l=10, r=10, t=50, b=10), xaxis=dict(tickformat="%m/%d"))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("📋 三大法人買賣超總結")
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n【有效交易日：{info['days']} 天】\n"
    report += "═════════════════════════════════════════════\n\n"
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for sid in st.session_state.targets:
            if sid in st.session_state.summary:
                s = st.session_state.summary[sid]
                report += f"{s['name']}: {s[key]//1000:+,} 張\n"
        report += "\n"
    st.code(report, language="text")
