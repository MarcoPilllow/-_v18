import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import time
import urllib3

# 1. 禁用 SSL 警告 (雲端執行必備，防止報錯)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 2. 頁面配置 (手機優化)
st.set_page_config(page_title="三大法人手機版", layout="centered")

# 3. 修正右上角 keyboard 文字殘影與隱藏選單
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    </style>
    """, unsafe_allow_html=True)

st.title("📊 三大法人籌碼診斷 (手機版)")

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("🔍 查詢設定")
    stock_input = st.text_input("股票代號 (逗號分隔)", value="2603, 2609, 2615")
    
    range_option = st.selectbox("快速區間", ["1周", "2周", "1月", "1季", "自定義"])
    today = datetime.date.today()
    
    if range_option == "1周": start_date = today - datetime.timedelta(days=7)
    elif range_option == "2周": start_date = today - datetime.timedelta(days=14)
    elif range_option == "1月": start_date = today - datetime.timedelta(days=30)
    elif range_option == "1季": start_date = today - datetime.timedelta(days=90)
    else:
        start_date = st.date_input("開始日期", today - datetime.timedelta(days=14))
    
    end_date = st.date_input("結束日期", today)
    run_btn = st.button("🚀 開始分析", use_container_width=True)

# --- 核心抓取邏輯 (雲端強化版) ---
def fetch_twse_data(date_obj):
    d_str = date_obj.strftime('%Y%m%d')
    url = f"https://www.twse.com.tw/fund/T86?response=json&date={d_str}&selectType=ALL"
    
    # 加入專業 Headers 偽裝成瀏覽器，避免被證交所擋掉
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.twse.com.tw/zh/page/trading/fund/T86.html'
    }
    
    try:
        # 使用 verify=False 跳過 SSL 驗證
        resp = requests.get(url, headers=headers, verify=False, timeout=15).json()
        if resp.get('stat') == 'OK' and 'data' in resp:
            df = pd.DataFrame(resp['data'])
            # 欄位解析
            df = df[[0, 1, 4, 7, 10, 11, 18]]
            df.columns = ['id', 'name', 'f_buy', 'f_trust', 'it_net', 'd_net', 'total_net']
            for col in df.columns[2:]:
                df[col] = df[col].astype(str).str.replace(',', '').astype(int)
            # 外資 = 外資買賣 + 外資避險
            df['f_net'] = df['f_buy'] + df['f_trust']
            return df
    except:
        return None
    return None

# --- 執行查詢 ---
if run_btn:
    # 支援全形與半形逗號
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    date_list = pd.date_range(start_date, end_date)
    trading_days = [d for d in date_list if d.weekday() < 5]
    
    if not trading_days:
        st.warning("選擇的區間內沒有交易日 (週末或假日)")
    else:
        all_data = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, d in enumerate(trading_days):
            status_text.text(f"正在掃描日期: {d.strftime('%Y-%m-%d')}")
            df = fetch_twse_data(d)
            if df is not None:
                res = df[df['id'].isin(targets)].copy()
                res['date'] = d
                all_data.append(res)
            
            # 雲端必須放慢速度，避免被鎖 IP
            time.sleep(0.5) 
            progress_bar.progress((i + 1) / len(trading_days))

        if all_data:
            full_df = pd.concat(all_data)
            status_text.success(f"✅ 分析完成！共取得 {len(all_data)} 天有效數據")
            
            # --- 繪圖 (使用 Plotly 手機互動感應) ---
            for stock in targets:
                sub_df = full_df[full_df['id'] == stock].sort_values('date')
                if sub_df.empty: continue
                
                stock_name = sub_df['name'].iloc[0]
                fig = go.Figure()
                
                # 柱狀圖
                fig.add_trace(go.Bar(
                    x=sub_df['date'],
                    y=sub_df['total_net'] / 1000,
                    marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in sub_df['total_net']],
                    name="三大法人總計",
                    hovertemplate="日期: %{x|%Y/%m/%d}<br>張數: %{y:+.0f} 張<extra></extra>"
                ))
                
                # 佈局優化 (手機版)
                fig.update_layout(
                    title=f"【{stock_name}】三大法人總計",
                    template="plotly_white",
                    margin=dict(l=10, r=10, t=50, b=10),
                    height=400,
                    xaxis=dict(tickformat="%m/%d", nticks=10),
                    yaxis=dict(title="張數 (1000張)")
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # 顯示簡單統計數據
                total_sum = sub_df['total_net'].sum() / 1000
                st.metric(f"{stock_name} 期間累計", f"{total_sum:+.0f} 張")
                st.divider()
        else:
            st.error("❌ 雲端無法連線至證交所或該日期無數據。請稍後再試或縮短查詢天數。")
