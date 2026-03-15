import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import time
import urllib3
import json
import os

# 1. 環境基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股三大法人籌碼變化", layout="centered")

# CSS 優化：隱藏選單殘影、美化按鈕、客製化進度框
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .stButton button { width: 100%; padding: 0.3rem; font-size: 14px; border-radius: 5px; }
    .status-box { 
        background-color: #1e1e1e; padding: 12px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #ff4b4b; color: #ffffff;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 聚財網加速抓取引擎 (取代單日查詢) ---
@st.cache_data(ttl=3600) # 緩存 1 小時，避免重複抓取
def fetch_wearn_data(stock_id):
    """一次性抓取聚財網歷史表格資料"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    urls = {
        'f': f"https://stock.wearn.com/a50m.asp?stockid={stock_id}", # 外資
        'it': f"https://stock.wearn.com/b50m.asp?stockid={stock_id}", # 投信
        'd': f"https://stock.wearn.com/c50.asp?stockid={stock_id}"    # 自營商
    }
    
    combined_df = None
    try:
        for key, url in urls.items():
            resp = requests.get(url, headers=headers, timeout=15)
            resp.encoding = 'big5' # 聚財網固定編碼
            
            # 使用 pandas 解析 HTML 表格
            dfs = pd.read_html(resp.text)
            target_table = None
            for d in dfs:
                if '日期' in str(d.columns):
                    target_table = d
                    break
            
            if target_table is not None:
                # 欄位解析 (外資買賣在第4欄, 投信/自營在第3欄)
                col_idx = 3 if key == 'f' else 2
                temp = target_table.iloc[:, [0, col_idx]].copy()
                temp.columns = ['date_raw', key]
                
                # 民國轉西元轉換邏輯
                def convert_date(s):
                    try:
                        pts = str(s).split('/')
                        return datetime.date(int(pts[0])+1911, int(pts[1]), int(pts[2]))
                    except: return None
                
                temp['date'] = temp['date_raw'].apply(convert_date)
                temp = temp.dropna(subset=['date']).drop(columns=['date_raw'])
                
                if combined_df is None:
                    combined_df = temp
                else:
                    combined_df = pd.merge(combined_df, temp, on='date', how='outer')
        
        if combined_df is not None:
            combined_df = combined_df.fillna(0)
            # 數值清理
            for col in ['f', 'it', 'd']:
                combined_df[col] = combined_df[col].astype(str).str.replace(',', '').astype(float).astype(int)
            combined_df['tot'] = combined_df['f'] + combined_df['it'] + combined_df['d']
            return combined_df.sort_values('date')
    except:
        return None
    return None

# --- 3. 股票清單管理 ---
LIST_FILE = "stock_lists.json"
def load_lists():
    if os.path.exists(LIST_FILE):
        try:
            with open(LIST_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {"航運股": "2603, 2609, 2615"}
    return {"航運股": "2603, 2609, 2615"}

def save_lists(lists):
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(lists, f, ensure_ascii=False, indent=4)

if 'custom_lists' not in st.session_state:
    st.session_state.custom_lists = load_lists()

# --- 4. 側邊欄 UI ---
with st.sidebar:
    st.header("📂 股票清單管理")
    list_names = list(st.session_state.custom_lists.keys())
    selected_list = st.selectbox("讀取組合", ["請選擇..."] + list_names)
    
    current_val = "2603, 2609, 2615, 2605, 2606, 2637"
    if selected_list != "請選擇...":
        current_val = st.session_state.custom_lists[selected_list]
    
    stock_input = st.text_input("1. 目前查詢股票代號", value=current_val)
    new_name = st.text_input("💾 儲存目前組合", placeholder="例如: 觀察名單")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存"):
            if new_name and stock_input:
                st.session_state.custom_lists[new_name] = stock_input
                save_lists(st.session_state.custom_lists); st.rerun()
    with c2:
        if st.button("❌ 刪除"):
            if selected_list != "請選擇...":
                del st.session_state.custom_lists[selected_list]
                save_lists(st.session_state.custom_lists); st.rerun()

    st.divider(); st.header("📅 快速區間選擇")
    presets = [[("1周", 7), ("2周", 14), ("3周", 21), ("1月", 30)], [("2月", 60), ("1季", 90), ("半年", 182), ("1年", 365)]]
    
    if 'start_date' not in st.session_state:
        st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)
        st.session_state.range_label = "自定義"

    for row in presets:
        cols = st.columns(4)
        for i, (label, days) in enumerate(row):
            if cols[i].button(label):
                st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
                st.session_state.range_label = label
                st.rerun()

    st.divider()
    start_date = st.date_input("開始日期", st.session_state.start_date)
    end_date = st.date_input("結束日期", datetime.date.today())
    run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)

# --- 5. 主視覺與分析邏輯 ---
st.title("📈 台股三大法人籌碼變化")

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    
    all_res = {}
    progress_bar = st.progress(0)
    status_area = st.empty()
    
    for i, sid in enumerate(targets):
        status_area.markdown(f'<div class="status-box">🏥 正在調閱資料：<b>{sid}</b></div>', unsafe_allow_html=True)
        df = fetch_wearn_data(sid)
        if df is not None:
            # 根據使用者選取的日期區間過濾 (聚財網一次給很多天，我們只需截取要的部分)
            mask = (df['date'] >= start_date) & (df['date'] <= end_date)
            all_res[sid] = df.loc[mask]
        progress_bar.progress((i + 1) / len(targets))

    if all_res:
        st.session_state.results = all_res
        st.session_state.info = {"start": start_date, "end": end_date, "label": st.session_state.range_label}
        status_area.success("✅ 數據載入成功")
    else:
        st.error("❌ 抓取失敗，請確認代號或區間是否有誤。")

# --- 6. 渲染圖表與 Toggle ---
if 'results' in st.session_state:
    res = st.session_state.results
    info = st.session_state.info
    
    st.divider()
    view_mode = st.radio("選擇顯示維度", ["三大法人總計", "外資", "投信", "自營商"], horizontal=True, index=0)
    mode_map = {"三大法人總計": "tot", "外資": "f", "投信": "it", "自營商": "d"}
    target_col = mode_map[view_mode]

    for stock_id, df in res.items():
        if df.empty: continue
        
        # 關鍵優化：將日期轉換為字串 MM/DD，解決 X 軸「不舒服」的時間顯示問題
        df_plot = df.copy().sort_values('date')
        df_plot['date_str'] = df_plot['date'].apply(lambda x: x.strftime('%m/%d'))
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_plot['date_str'],
            y=df_plot[target_col],
            marker_color=['#ef5350' if x >= 0 else '#66bb6a' for x in df_plot[target_col]],
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        fig.update_layout(
            title=f"【{stock_id}】{view_mode} 籌碼 (張)",
            template="plotly_dark",
            margin=dict(l=10, r=10, t=50, b=10), height=350,
            xaxis=dict(type='category', tickangle=-45) # category 解決日期重疊與空洞
        )
        st.plotly_chart(fig, use_container_width=True)

    # 深度報告區
    st.divider(); st.subheader("📋 深度會診報告")
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n" + "═"*45 + "\n\n"
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for sid, df in res.items():
            if not df.empty:
                val = df[key].sum()
                report += f"{sid}: {val:+,} 張\n"
        report += "\n"
    st.code(report, language="text")
