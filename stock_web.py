import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import time
import urllib3
import json
import os

# 1. 基礎環境設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="三大法人手機診斷版 v18.5", layout="centered")

# CSS 優化：強制移除右上角選單殘影與美化介面
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .stButton button { width: 100%; padding: 0.3rem; font-size: 14px; border-radius: 5px; }
    .report-code { font-family: 'Consolas', monospace !important; font-size: 15px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端緩存機制 (解決查詢慢的問題) ---
@st.cache_data(ttl=86400) # 快取 24 小時
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
            # 欄位解析: 0代號, 1名稱, 4外資, 7外資自營, 10投信, 11自營, 18總計
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
    
    # 自動填入邏輯
    initial_stocks = "2603, 2609, 2615"
    if selected_list != "請選擇...":
        initial_stocks = st.session_state.custom_lists[selected_list]
    
    stock_input = st.text_input("1. 目前查詢股票代號", value=initial_stocks)
    new_list_name = st.text_input("💾 儲存組合名稱", placeholder="例如: 我的最愛")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("💾 儲存"):
            if new_list_name and stock_input:
                st.session_state.custom_lists[new_list_name] = stock_input
                save_lists(st.session_state.custom_lists)
                st.rerun()
    with col_s2:
        if st.button("❌ 刪除"):
            if selected_list != "請選擇...":
                del st.session_state.custom_lists[selected_list]
                save_lists(st.session_state.custom_lists)
                st.rerun()

    st.divider()
    st.header("📅 快速區間選擇")
    
    # 建立 4x4 按鈕矩陣
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

# --- 5. 主程式邏輯 ---
st.title("📊 三大法人籌碼會診")

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    
    # 過濾週末
    all_days = pd.date_range(start_date, end_date)
    trading_days = [d for d in all_days if d.weekday() < 5]
    
    if not trading_days:
        st.warning("⚠️ 選擇區間無交易日。")
    else:
        all_data = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        
        for i, d in enumerate(trading_days):
            d_str = d.strftime('%Y%m%d')
            status_text.text(f"🏥 掃描中: {d.strftime('%Y-%m-%d')} (週末已過濾)")
            
            # 使用緩存抓取
            df = fetch_twse_cache(d_str)
            
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
            
            # 雲端微延遲以保安全
            time.sleep(0.05)
            progress_bar.progress((i + 1) / len(trading_days))

        if all_data:
            full_df = pd.concat(all_data)
            status_text.success(f"✅ 分析完成！有效交易日：{len(all_data)} 天")
            
            # --- 繪圖區 ---
            for stock in targets:
                sub_df = full_df[full_df['id'] == stock].sort_values('date')
                if sub_df.empty: continue
                
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=sub_df['date'],
                    y=sub_df['total_net'] / 1000,
                    marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in sub_df['total_net']],
                    name="張數",
                    hovertemplate="日期: %{x|%Y/%m/%d}<br>張數: %{y:+.0f} 張<extra></extra>"
                ))
                fig.update_layout(
                    title=f"【{summary[stock]['name']}】三大法人總計 (張)",
                    template="plotly_dark",
                    margin=dict(l=10, r=10, t=50, b=10),
                    height=300,
                    xaxis=dict(tickformat="%m/%d")
                )
                st.plotly_chart(fig, use_container_width=True)

            # --- 診斷報告區 (蕭醫師指定格式) ---
            st.divider()
            st.subheader("📋 深度會診報告")
            
            r_label = st.session_state.get('label', '自定義')
            report_text = f"【期間：{start_date} ~ {end_date}】\n"
            report_text += f"【區間：{r_label}】\n"
            report_text += f"【有效交易日：{len(all_data)} 天】\n"
            report_text += "═" * 45 + "\n\n"
            
            sections = [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]
            
            for title, key in sections:
                report_text += f"{title}\n"
                for s in targets:
                    val = summary[s][key] // 1000
                    name = summary[s]['name']
                    report_text += f"{name}: {val:+,} 張\n"
                report_text += "\n"
            
            st.code(report_text, language="text")
        else:
            st.error("❌ 抓取失敗，請確認該日期區間是否正確。")
