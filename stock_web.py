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
st.set_page_config(page_title="三大法人籌碼會診 v18.0", layout="centered")

# 隱藏右上角 UI 殘影與自定義樣式
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .report-text { font-family: 'Consolas', monospace; line-height: 1.2; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 股票清單管理 (模擬桌面版 SQLite 邏輯) ---
LIST_FILE = "stock_lists.json"

def load_lists():
    if os.path.exists(LIST_FILE):
        try:
            with open(LIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"航運股": "2603, 2609, 2615"}
    return {"航運股": "2603, 2609, 2615"}

def save_lists(lists):
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(lists, f, ensure_ascii=False, indent=4)

# 初始化 session state 中的清單
if 'custom_lists' not in st.session_state:
    st.session_state.custom_lists = load_lists()

# --- 3. 側邊欄 UI：清單管理與查詢設定 ---
with st.sidebar:
    st.header("📂 股票清單管理")
    
    # 選擇現有組合
    list_names = list(st.session_state.custom_lists.keys())
    selected_list = st.selectbox("讀取查詢組合", ["請選擇..."] + list_names)
    
    # 自動填入邏輯
    current_val = "2603, 2609, 2615"
    if selected_list != "請選擇...":
        current_val = st.session_state.custom_lists[selected_list]
    
    # 輸入與儲存功能
    stock_input = st.text_input("1. 目前查詢股票代號", value=current_val)
    new_list_name = st.text_input("💾 儲存目前組合名稱", placeholder="例如: 航運三雄")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存組合", use_container_width=True):
            if new_list_name and stock_input:
                st.session_state.custom_lists[new_list_name] = stock_input
                save_lists(st.session_state.custom_lists)
                st.success(f"已存: {new_list_name}")
                st.rerun()
    with c2:
        if st.button("❌ 刪除清單", use_container_width=True):
            if selected_list != "請選擇...":
                del st.session_state.custom_lists[selected_list]
                save_lists(st.session_state.custom_lists)
                st.warning("已刪除")
                st.rerun()

    st.divider()
    st.header("🔍 查詢設定")
    range_option = st.selectbox("快速區間", ["1周", "2周", "1月", "1季", "自定義"])
    
    today = datetime.date.today()
    if range_option == "1周": start_date = today - datetime.timedelta(days=7)
    elif range_option == "2周": start_date = today - datetime.timedelta(days=14)
    elif range_option == "1月": start_date = today - datetime.timedelta(days=30)
    elif range_option == "1季": start_date = today - datetime.timedelta(days=90)
    else: start_date = st.date_input("開始日期", today - datetime.timedelta(days=14))
    
    end_date = st.date_input("結束日期", today)
    run_btn = st.button("🚀 執行籌碼分析", type="primary", use_container_width=True)

# --- 4. 資料抓取邏輯 (偽裝瀏覽器以免被阻擋) ---
def fetch_twse_data(date_obj):
    d_str = date_obj.strftime('%Y%m%d')
    url = f"https://www.twse.com.tw/fund/T86?response=json&date={d_str}&selectType=ALL"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://www.twse.com.tw/zh/page/trading/fund/T86.html'
    }
    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=15).json()
        if resp.get('stat') == 'OK' and 'data' in resp:
            df = pd.DataFrame(resp['data'])
            # 解析欄位
            df = df[[0, 1, 4, 7, 10, 11, 18]]
            df.columns = ['id', 'name', 'f_buy', 'f_trust', 'it_net', 'd_net', 'total_net']
            for col in df.columns[2:]:
                df[col] = df[col].astype(str).str.replace(',', '').astype(int)
            df['f_net'] = df['f_buy'] + df['f_trust']
            return df
    except:
        return None
    return None

# --- 5. 主視覺顯示 ---
st.title("📊 三大法人籌碼診斷")

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    date_list = pd.date_range(start_date, end_date)
    trading_days = [d for d in date_list if d.weekday() < 5]
    
    if not trading_days:
        st.warning("所選區間內無交易日")
    else:
        all_data = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 匯總數據初始化
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        
        for i, d in enumerate(trading_days):
            status_text.text(f"🏥 正在掃描日期: {d.strftime('%Y-%m-%d')}")
            df = fetch_twse_data(d)
            if df is not None:
                res = df[df['id'].isin(targets)].copy()
                for _, row in res.iterrows():
                    sid = row['id']
                    summary[sid]['name'] = row['name']
                    summary[sid]['f'] += row['f_net']
                    summary[sid]['it'] += row['it_net']
                    summary[sid]['d'] += row['d_net']
                    summary[sid]['tot'] += row['total_net']
                all_data.append(res.assign(date=d))
            
            time.sleep(0.4) # 雲端抓取防護間隔
            progress_bar.progress((i + 1) / len(trading_days))

        if all_data:
            full_df = pd.concat(all_data)
            status_text.success(f"✅ 完成！已掃描 {len(all_data)} 天數據")
            
            # --- 顯示互動圖表 ---
            for stock in targets:
                sub_df = full_df[full_df['id'] == stock].sort_values('date')
                if sub_df.empty: continue
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=sub_df['date'],
                    y=sub_df['total_net'] / 1000,
                    marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in sub_df['total_net']],
                    name="張數",
                    hovertemplate="日期: %{x|%m/%d}<br>張數: %{y:+.0f} 張<extra></extra>"
                ))
                fig.update_layout(
                    title=f"【{summary[stock]['name']}】三大法人總計 (張)",
                    template="plotly_dark",
                    margin=dict(l=10, r=10, t=50, b=10),
                    height=300,
                    xaxis=dict(tickformat="%m/%d")
                )
                st.plotly_chart(fig, use_container_width=True)

            # --- 顯示文字報告 (蕭醫師指定的範例格式) ---
            st.divider()
            st.subheader("📋 深度會診報告")
            
            report = f"【期間：{start_date} ~ {end_date}】\n"
            report += f"【區間：{range_option}】\n"
            report += f"【有效交易日：{len(all_data)} 天】\n"
            report += "═" * 45 + "\n\n"
            
            sections = [
                ("[三大法人總和]", 'tot'),
                ("[外資]", 'f'),
                ("[投信]", 'it'),
                ("[自營商]", 'd')
            ]
            
            for title, key in sections:
                report += f"{title}\n"
                for stock in targets:
                    val = summary[stock][key] // 1000
                    name = summary[stock]['name']
                    report += f"{name}: {val:+,} 張\n"
                report += "\n"
            
            st.code(report, language="text")
            
        else:
            st.error("❌ 抓取失敗，請確認證交所狀態或縮短查詢天數。")
