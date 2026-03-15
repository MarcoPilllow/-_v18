import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import json
import os

# --- 1. 環境基礎設定 ---
st.set_page_config(page_title="三大法人手機診斷版 v19.0", layout="centered")

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
    div[role="radiogroup"] { justify-content: center; margin-bottom: 1rem; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端緩存與 FinMind API 策略 ---
@st.cache_data(ttl=86400)
def get_stock_name(stock_id):
    """透過證交所輕量 API 取得股票名稱"""
    try:
        url = f"https://www.twse.com.tw/zh/api/codeQuery?query={stock_id}"
        resp = requests.get(url, timeout=5).json()
        if resp.get("suggestions"):
            return resp["suggestions"][0].split("\t")[1]
    except:
        pass
    return str(stock_id)

@st.cache_data(ttl=3600)
def fetch_finmind_institutional(stock_id, start_date, end_date):
    """【核心升級】使用 FinMind API，單次拉取區間內該股票的所有法人買賣超"""
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
            
            # 計算淨買賣超 (FinMind 的數據單位為「股」)
            df['net'] = df['buy'] - df['sell']
            
            # 將 FinMind 的細部法人名稱歸類為三大法人
            def classify_investor(name):
                if '外資' in name: return 'f_net'
                elif '投信' in name: return 'it_net'
                elif '自營商' in name: return 'd_net'
                return 'other'
                
            df['type'] = df['name'].apply(classify_investor)
            
            # 以日期分組，將不同法人的 net 加總 (例如自營商有自行買賣和避險)
            pivot_df = df.pivot_table(index='date', columns='type', values='net', aggfunc='sum').fillna(0)
            
            # 確保欄位都存在，避免報錯
            for col in ['f_net', 'it_net', 'd_net']:
                if col not in pivot_df.columns:
                    pivot_df[col] = 0
                    
            pivot_df['total_net'] = pivot_df['f_net'] + pivot_df['it_net'] + pivot_df['d_net']
            pivot_df = pivot_df.reset_index()
            pivot_df['id'] = stock_id
            
            # 轉換日期格式以便與 Plotly 相容
            pivot_df['date'] = pd.to_datetime(pivot_df['date']).dt.strftime('%Y-%m-%d')
            return pivot_df
    except Exception as e:
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

# --- 5. 主視覺顯示與高效數據處理 ---
st.title("📊 三大法人籌碼會診")

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    
    if not targets:
        st.warning("⚠️ 請輸入至少一檔股票代號。")
    else:
        progress_bar = st.progress(0)
        status_area = st.empty()
        
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        results_list = []
        
        # 改為針對「股票」發送請求，大幅降低 Request 次數
        for idx, stock in enumerate(targets):
            status_area.markdown(f"""
                <div class="status-box">
                    <b>⚡ 正在彙總區間資料：[{idx+1} / {len(targets)}]</b><br>
                    代號：{stock}
                </div>
            """, unsafe_allow_html=True)
            
            # 取得名稱並抓取資料
            stock_name = get_stock_name(stock)
            summary[stock]['name'] = stock_name
            df = fetch_finmind_institutional(stock, start_date, end_date)
            
            if df is not None and not df.empty:
                results_list.append(df)
                summary[stock]['f'] = df['f_net'].sum()
                summary[stock]['it'] = df['it_net'].sum()
                summary[stock]['d'] = df['d_net'].sum()
                summary[stock]['tot'] = df['total_net'].sum()
                
            progress_bar.progress((idx + 1) / len(targets))

        status_area.empty()
        progress_bar.empty()

        if results_list:
            full_df = pd.concat(results_list)
            # 透過實際抓到的資料計算真實的「有效交易日」
            actual_trading_days = full_df['date'].nunique()
            
            st.session_state.full_df = full_df
            st.session_state.summary = summary
            st.session_state.targets = targets
            st.session_state.analysis_info = {
                "start": start_date, "end": end_date, 
                "label": st.session_state.get('label', '自定義'), 
                "days": actual_trading_days
            }
            st.session_state.has_run = True
        else:
            st.error("❌ 抓取失敗，區間內可能無資料。")
            st.session_state.has_run = False

# === 6. 圖表 Toggle 與 報告渲染 ===
if st.session_state.get('has_run', False):
    info = st.session_state.analysis_info
    st.success(f"✅ 高效分析完成！共涵蓋 {info['days']} 個有效交易日")
    
    metric_options = {
        "三大法人總和": "total_net",
        "外資": "f_net",
        "投信": "it_net",
        "自營商": "d_net"
    }
    
    selected_label = st.radio(
        "🔄 切換檢視數據", 
        list(metric_options.keys()), 
        horizontal=True,
        label_visibility="collapsed"
    )
    y_column = metric_options[selected_label]
    
    full_df = st.session_state.full_df
    summary = st.session_state.summary
    targets = st.session_state.targets

    for stock in targets:
        sub_df = full_df[full_df['id'] == stock].sort_values('date')
        if sub_df.empty: continue
        fig = go.Figure()
        
        # 轉換回「張」數
        y_data = sub_df[y_column] / 1000
        
        fig.add_trace(go.Bar(
            x=sub_df['date'],
            y=y_data,
            marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_data],
            name="張數",
            hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
        ))
        
        fig.update_layout(
            title=f"【{summary[stock]['name']}】{selected_label} (張)",
            template="plotly_dark",
            margin=dict(l=10, r=10, t=50, b=10), height=300, xaxis=dict(tickformat="%m/%d")
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("📋 深度會診報告")
    report = f"【期間：{info['start']} ~ {info['end']}】\n【區間：{info['label']}】\n【有效交易日：{info['days']} 天】\n" + "═"*45 + "\n\n"
    for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
        report += f"{title}\n"
        for s in targets: 
            report += f"{summary[s]['name']}: {summary[s][key]//1000:+.0f} 張\n"
        report += "\n"
    st.code(report, language="text")
