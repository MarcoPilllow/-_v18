import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import os

# 1. 基礎環境設定
st.set_page_config(page_title="台股三大法人籌碼變化", layout="centered")

# CSS 優化：隱藏選單殘影、美化按鈕、客製化狀態框
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .stButton button { width: 100%; padding: 0.2rem; font-size: 13px; border-radius: 5px; }
    .status-box { background-color: #1e1e1e; padding: 12px; border-radius: 8px; border-left: 5px solid #007bff; color: #ffffff; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 數據抓取函數 (置頂防止 NameError) ---
def fetch_wear_data(stock_id):
    """從聚財網獲取數據 (加速版)"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    urls = {
        'f': f"https://stock.wearn.com/a50m.asp?stockid={stock_id}",
        'it': f"https://stock.wearn.com/b50m.asp?stockid={stock_id}",
        'd': f"https://stock.wearn.com/c50.asp?stockid={stock_id}"
    }
    combined_df = None
    try:
        for key, url in urls.items():
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = 'big5' 
            dfs = pd.read_html(resp.text)
            target_df = None
            for d in dfs:
                if '日期' in str(d.columns):
                    target_df = d
                    break
            
            if target_df is not None:
                col_idx = 3 if key == 'f' else 2
                temp = target_df.iloc[:, [0, col_idx]].copy()
                temp.columns = ['date_raw', key]
                
                def conv_d(s):
                    try:
                        p = str(s).split('/')
                        return datetime.date(int(p[0])+1911, int(p[1]), int(p[2]))
                    except: return None
                
                temp['date'] = temp['date_raw'].apply(conv_d)
                temp = temp.dropna(subset=['date']).drop(columns=['date_raw'])
                if combined_df is None: combined_df = temp
                else: combined_df = pd.merge(combined_df, temp, on='date', how='outer')
        
        if combined_df is not None:
            combined_df = combined_df.fillna(0)
            for col in ['f', 'it', 'd']:
                combined_df[col] = combined_df[col].astype(str).str.replace(',', '').astype(float).astype(int)
            combined_df['tot'] = combined_df['f'] + combined_df['it'] + combined_df['d']
            return combined_df.sort_values('date')
    except: return None
    return None

# --- 3. 狀態初始化 ---
if 'analysis_results' not in st.session_state:
    st.session_state.analysis_results = None

if 'custom_lists' not in st.session_state:
    if os.path.exists("stock_lists.json"):
        with open("stock_lists.json", "r", encoding="utf-8") as f: st.session_state.custom_lists = json.load(f)
    else: st.session_state.custom_lists = {"航運三雄": "2603, 2609, 2615"}

# --- 4. 側邊欄 UI ---
with st.sidebar:
    st.header("📂 股票清單管理")
    list_names = list(st.session_state.custom_lists.keys())
    sel_list = st.selectbox("讀取查詢組合", ["請選擇..."] + list_names)
    stock_val = "2603, 2609, 2615, 2605, 2606, 2637"
    if sel_list != "請選擇...": stock_val = st.session_state.custom_lists[sel_list]
    stock_input = st.text_input("目前查詢代號", value=stock_val)

    st.divider(); st.header("📅 快速區間選擇")
    # 完美還原 16 格快捷鍵
    presets = [
        [("1天", 1), ("2天", 2), ("3天", 3), ("4天", 4)],
        [("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)],
        [("6周", 42), ("2月", 60), ("1季", 90), ("半年", 182)],
        [("1年", 365), ("2年", 730), ("3年", 1095), ("5年", 1825)]
    ]
    if 'start_date' not in st.session_state: st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)
    if 'range_label' not in st.session_state: st.session_state.range_label = "自定義"

    for row in presets:
        cols = st.columns(4)
        for i, (l, d) in enumerate(row):
            if cols[i].button(l):
                st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=d-1)
                st.session_state.range_label = l
                st.rerun()

    start_d = st.date_input("開始日期", st.session_state.start_date)
    end_d = st.date_input("結束日期", datetime.date.today())
    run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)

# --- 5. 核心邏輯：執行與顯示 ---
st.title("📈 台股三大法人籌碼變化")

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    results = {}
    prog = st.progress(0)
    for i, sid in enumerate(targets):
        st.write(f"🏥 正在調閱: {sid}...")
        df = fetch_wear_data(sid)
        if df is not None:
            mask = (df['date'] >= start_d) & (df['date'] <= end_d)
            results[sid] = df.loc[mask]
        prog.progress((i + 1) / len(targets))
    st.session_state.analysis_results = results
    st.session_state.query_info = {"start": start_d, "end": end_d, "label": st.session_state.range_label}

# --- 6. 渲染圖表與 Toggle ---
if st.session_state.analysis_results:
    res = st.session_state.analysis_results
    info = st.session_state.query_info
    
    st.divider()
    view_mode = st.radio("📊 選擇顯示維度", ["三大法人總和", "外資", "投信", "自營商"], horizontal=True)
    mode_map = {"三大法人總和": "tot", "外資": "f", "投信": "it", "自營商": "d"}
    target_col = mode_map[view_mode]

    for sid, df in res.items():
        if df.empty: continue
        
        # X 軸格式淨化：只留 MM/DD (解決顯示不舒服的時間代碼問題)
        df_plot = df.copy().sort_values('date')
        df_plot['date_str'] = df_plot['date'].apply(lambda x: x.strftime('%m/%d'))
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_plot['date_str'],
            y=df_plot[target_col],
            marker_color=['#ef5350' if x >= 0 else '#66bb6a' for x in df_plot[target_col]],
            name=view_mode,
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        fig.update_layout(
            title=f"【{sid}】{view_mode} (張)",
            template="plotly_dark", margin=dict(l=10, r=10, t=50, b=10), height=350,
            xaxis=dict(type='category', tickangle=-45)
        )
        st.plotly_chart(fig, use_container_width=True)

    # 深度報告
    st.divider(); st.subheader("📋 深度會診報告")
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n" + "═"*45 + "\n\n"
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for sid, df in res.items():
            if not df.empty: report += f"{sid}: {df[key].sum():+,} 張\n"
        report += "\n"
    st.code(report, language="text")
