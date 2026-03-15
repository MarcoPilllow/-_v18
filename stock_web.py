import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import time
import urllib3
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

# 1. 環境基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="三大法人手機診斷版 v18.8", layout="centered")

# CSS 優化：自定義進度框與隱藏殘影
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .stButton button { width: 100%; padding: 0.3rem; font-size: 14px; border-radius: 5px; }
    .status-box { 
        background-color: #1e1e1e; 
        padding: 12px; 
        border-radius: 8px; 
        margin-bottom: 10px; 
        border-left: 5px solid #007bff;
        color: #ffffff;
    }
    /* 美化 Radio 按鈕間距 */
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端緩存機制 ---
@st.cache_data(ttl=86400)
def fetch_twse_cache(date_str):
    url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.twse.com.tw/zh/page/trading/fund/T86.html'
    }
    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=15).json()
        if resp.get('stat') == 'OK' and 'data' in resp:
            df = pd.DataFrame(resp['data'])
            df = df[[0, 1, 4, 7, 10, 11, 18]]
            df.columns = ['id', 'name', 'f_buy', 'f_trust', 'it_net', 'd_net', 'total_net']
            for col in df.columns[2:]:
                df[col] = df[col].astype(str).str.replace(',', '').astype(int)
            df['f_net'] = df['f_buy'] + df['f_trust']
            return df
    except:
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

# --- 4. 側邊欄 UI ---
with st.sidebar:
    st.header("📂 股票清單管理")
    list_names = list(st.session_state.custom_lists.keys())
    selected_list = st.selectbox("讀取組合", ["請選擇..."] + list_names)
    
    initial_stocks = "2603, 2609, 2615"
    if selected_list != "請選擇...":
        initial_stocks = st.session_state.custom_lists[selected_list]
    
    stock_input = st.text_input("1. 目前查詢股票代號", value=initial_stocks)
    new_list_name = st.text_input("💾 儲存組合名稱", placeholder="例如: 航運三雄")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存"):
            if new_list_name and stock_input:
                st.session_state.custom_lists[new_list_name] = stock_input
                save_lists(st.session_state.custom_lists); st.rerun()
    with c2:
        if st.button("❌ 刪除"):
            if selected_list != "請選擇...":
                del st.session_state.custom_lists[selected_list]
                save_lists(st.session_state.custom_lists); st.rerun()

    st.divider()
    st.header("📅 快速區間選擇")
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
            if cols[i].button(label):
                st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
                st.session_state.label = label

    st.divider()
    start_date = st.date_input("開始日期", st.session_state.start_date)
    end_date = st.date_input("結束日期", datetime.date.today())
    run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)

# --- 5. 主視覺顯示與並行加速邏輯 ---
st.title("📊 三大法人籌碼會診")

# === 核心修改區塊 1：執行分析並將結果存入 Session State ===
if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    all_days = pd.date_range(start_date, end_date)
    trading_days = [d for d in all_days if d.weekday() < 5] # 過濾週末
    total_tasks = len(trading_days)
    
    if total_tasks == 0:
        st.warning("⚠️ 所選區間內無交易日。")
    else:
        results_map = {}
        progress_bar = st.progress(0)
        status_area = st.empty()
        eta_area = st.empty()
        
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        start_time_exec = time.time()
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_date = {executor.submit(fetch_twse_cache, d.strftime('%Y%m%d')): d for d in trading_days}
            completed = 0
            for future in as_completed(future_to_date):
                date_obj = future_to_date[future]
                completed += 1
                
                elapsed = time.time() - start_time_exec
                avg = elapsed / completed
                eta = int(avg * (total_tasks - completed))
                
                status_area.markdown(f"""
                    <div class="status-box">
                        <b>🏥 並行掃描中：[{completed} / {total_tasks}]</b><br>
                        最新完成：{date_obj.strftime('%Y-%m-%d')}
                    </div>
                """, unsafe_allow_html=True)
                
                if eta > 0:
                    eta_area.info(f"⏳ 預計還需要 **{eta}** 秒完成")
                else:
                    eta_area.empty()
                
                df = future.result()
                if df is not None:
                    res = df[df['id'].isin(targets)].copy()
                    for _, row in res.iterrows():
                        sid = row['id']
                        summary[sid]['name'] = row['name']
                        summary[sid]['f'] += row['f_net']
                        summary[sid]['it'] += row['it_net']
                        summary[sid]['d'] += row['d_net']
                        summary[sid]['tot'] += row['total_net']
                    results_map[date_obj] = res.assign(date=date_obj)
                
                progress_bar.progress(completed / total_tasks)

        eta_area.empty()
        status_area.empty()
        progress_bar.empty()

        if results_map:
            # 將算好的資料存入 Session State，避免切換選項時重新讀取
            sorted_dates = sorted(results_map.keys())
            st.session_state.full_df = pd.concat([results_map[d] for d in sorted_dates])
            st.session_state.summary = summary
            st.session_state.targets = targets
            st.session_state.analysis_info = {
                "start": start_date, "end": end_date, 
                "label": st.session_state.get('label', '自定義'), 
                "days": len(results_map)
            }
            st.session_state.has_run = True
        else:
            st.error("❌ 抓取失敗，區間內可能無資料。")
            st.session_state.has_run = False

# === 核心修改區塊 2：獨立渲染圖表，加入 Toggle 邏輯 ===
if st.session_state.get('has_run', False):
    info = st.session_state.analysis_info
    st.success(f"✅ 分析完成！共載入 {info['days']} 個交易日")
    
    # --- 新增 Toggle 選項 ---
    metric_options = {
        "三大法人總和": "total_net",
        "外資": "f_net",
        "投信": "it_net",
        "自營商": "d_net"
    }
    
    # 使用水平排列的 radio 做出 Toggle 效果
    selected_label = st.radio(
        "🔄 切換檢視數據", 
        list(metric_options.keys()), 
        horizontal=True,
        label_visibility="collapsed" # 隱藏標題讓視覺更像獨立的 Toggle bar
    )
    y_column = metric_options[selected_label]
    
    # 讀取暫存的資料
    full_df = st.session_state.full_df
    summary = st.session_state.summary
    targets = st.session_state.targets

    # 顯示圖表
    for stock in targets:
        sub_df = full_df[full_df['id'] == stock].sort_values('date')
        if sub_df.empty: continue
        fig = go.Figure()
        
        # 動態調整 Y 軸為使用者選定的法人數據
        y_data = sub_df[y_column] / 1000
        
        fig.add_trace(go.Bar(
            x=sub_df['date'],
            y=y_data,
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_data],
            name="張數",
            hovertemplate="日期: %{x|%Y/%m/%d}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        
        fig.update_layout(
            title=f"【{summary[stock]['name']}】{selected_label} (張)",
            template="plotly_dark",
            margin=dict(l=10, r=10, t=50, b=10), height=300, xaxis=dict(tickformat="%m/%d")
        )
        st.plotly_chart(fig, use_container_width=True)

    # 顯示診斷報告
    st.divider()
    st.subheader("📋 深度會診報告")
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n【有效交易日：{info['days']} 天】\n" + "═"*45 + "\n\n"
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for s in targets: 
            report += f"{summary[s]['name']}: {summary[s][key]//1000:+,} 張\n"
        report += "\n"
    st.code(report, language="text")
