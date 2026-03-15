import streamlit as st
import requests
import pandas as pd
import datetime
import plotly.graph_objects as go
import time
import urllib3
import json
import os
import re

# 1. 環境基礎設定
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="台股三大法人籌碼變化", layout="centered")

# CSS 優化：移除右上角殘影、美化按鈕、客製化進度框
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stApp [data-testid="stToolbar"] {display:none;}
    .stButton button { width: 100%; padding: 0.3rem; font-size: 14px; border-radius: 5px; }
    .status-box { 
        background-color: #1e1e1e; padding: 12px; border-radius: 8px; margin-bottom: 10px; 
        border-left: 5px solid #00c853; color: #ffffff;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 全新高速爬蟲模組 (Wearn 聚財網多日策略) ---
def fetch_wearn_table(url_base, stock_id):
    """抓取單一法人特定股票的多日歷史資料"""
    url = f"{url_base}?kind={stock_id}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'big5' # 聚財網使用 big5 編碼
        dfs = pd.read_html(res.text)
        
        # 從網頁標題嘗試提取股票名稱 (例如: <title>... 2603長榮 ...</title>)
        name_match = re.search(rf'{stock_id}([\u4e00-\u9fa5]+)', res.text)
        stock_name = name_match.group(1) if name_match else str(stock_id)

        for df in dfs:
            if len(df) < 2:
                continue
            
            # 尋找包含「日期」與「買賣」關鍵字的正確表格列
            header_idx = -1
            for i in range(min(4, len(df))):
                row_vals = [str(x) for x in df.iloc[i].values]
                if any('日期' in x for x in row_vals) and any('買賣' in x for x in row_vals):
                    header_idx = i
                    break
                    
            if header_idx != -1:
                df.columns = df.iloc[header_idx]
                df = df.iloc[header_idx+1:].copy()
                
                # 取得目標欄位
                date_col = [c for c in df.columns if '日期' in str(c)][0]
                net_cols = [c for c in df.columns if '買賣' in str(c)]
                if not net_cols:
                    continue
                net_col = net_cols[0]
                
                df = df[[date_col, net_col]].dropna()
                
                # 民國日期轉換 (例: 113/05/20 -> 2024-05-20)
                def parse_date(d_str):
                    try:
                        parts = str(d_str).strip().split('/')
                        if len(parts) >= 3:
                            return datetime.date(int(parts[0])+1911, int(parts[1]), int(parts[2]))
                    except Exception:
                        return None
                    return None
                    
                df['date'] = df[date_col].apply(parse_date)
                df = df.dropna(subset=['date'])
                
                # 數字清理 (去除加號、逗號)
                df['net'] = df[net_col].astype(str).str.replace(',', '').str.replace('+', '').str.replace(' ', '')
                df['net'] = pd.to_numeric(df['net'], errors='coerce').fillna(0).astype(int)
                
                return df[['date', 'net']], stock_name
                
    except Exception as e:
        pass
        
    return pd.DataFrame(), str(stock_id)

@st.cache_data(ttl=3600)
def fetch_stock_all_institutions(stock_id):
    """一次性抓取三大法人多日資料並合併"""
    df_f, name1 = fetch_wearn_table("https://stock.wearn.com/a50m.asp", stock_id)
    df_it, name2 = fetch_wearn_table("https://stock.wearn.com/b50m.asp", stock_id)
    df_d, name3 = fetch_wearn_table("https://stock.wearn.com/c50.asp", stock_id)
    
    dfs = []
    if not df_f.empty:
        dfs.append(df_f.rename(columns={'net': 'f_net'}))
    if not df_it.empty:
        dfs.append(df_it.rename(columns={'net': 'it_net'}))
    if not df_d.empty:
        dfs.append(df_d.rename(columns={'net': 'd_net'}))
        
    if not dfs:
        return None, str(stock_id)
        
    from functools import reduce
    merged = reduce(lambda left, right: pd.merge(left, right, on='date', how='outer'), dfs).fillna(0)
    
    for col in ['f_net', 'it_net', 'd_net']:
        if col not in merged.columns:
            merged[col] = 0
            
    merged['total_net'] = merged['f_net'] + merged['it_net'] + merged['d_net']
    merged['id'] = stock_id
    
    # 決定最終名稱
    final_name = name1 if name1 != str(stock_id) else (name2 if name2 != str(stock_id) else name3)
    merged['name'] = final_name
    return merged, final_name

# --- 3. 股票清單管理 ---
LIST_FILE = "stock_lists.json"

def load_lists():
    if os.path.exists(LIST_FILE):
        try:
            with open(LIST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"航運股": "2603, 2609, 2615"}
    return {"航運股": "2603, 2609, 2615"}

def save_lists(lists):
    with open(LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(lists, f, ensure_ascii=False, indent=4)

if 'custom_lists' not in st.session_state:
    st.session_state.custom_lists = load_lists()

# --- 4. 側邊欄 UI：清單管理與區間選擇 ---
with st.sidebar:
    st.header("📂 股票清單管理")
    list_names = list(st.session_state.custom_lists.keys())
    selected_list = st.selectbox("讀取組合", ["請選擇..."] + list_names)
    
    current_val = "2603, 2609, 2615, 2605, 2606, 2637"
    if selected_list != "請選擇...":
        current_val = st.session_state.custom_lists[selected_list]
    
    stock_input = st.text_input("1. 目前查詢股票代號", value=current_val)
    new_name = st.text_input("💾 儲存目前組合", placeholder="例如: 航運三雄")
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 儲存"):
            if new_name and stock_input:
                st.session_state.custom_lists[new_name] = stock_input
                save_lists(st.session_state.custom_lists)
                st.rerun()
    with c2:
        if st.button("❌ 刪除"):
            if selected_list != "請選擇...":
                del st.session_state.custom_lists[selected_list]
                save_lists(st.session_state.custom_lists)
                st.rerun()

    st.divider()
    st.header("📅 快速區間選擇")
    presets = [[("1周", 7), ("2周", 14), ("3周", 21)], [("1月", 30), ("6周", 42), ("2月", 60)]]
    
    if 'start_date' not in st.session_state:
        st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=14)
        st.session_state.range_label = "自定義"

    for row in presets:
        cols = st.columns(3)
        for i, (label, days) in enumerate(row):
            if cols[i].button(label):
                st.session_state.start_date = datetime.date.today() - datetime.timedelta(days=days-1)
                st.session_state.range_label = label

    st.divider()
    start_date = st.date_input("開始日期", st.session_state.start_date)
    end_date = st.date_input("結束日期", datetime.date.today())
    run_btn = st.button("🚀 執行高速籌碼分析", type="primary", use_container_width=True)

# --- 5. 主視覺顯示與平行掃描邏輯 ---
st.title("📈 台股三大法人籌碼變化")

if run_btn:
    targets = [s.strip() for s in stock_input.replace('，', ',').split(',') if s.strip()]
    total_tasks = len(targets)
    
    if total_tasks == 0:
        st.warning("⚠️ 請輸入至少一檔股票。")
    else:
        all_data_list = []
        progress_bar = st.progress(0)
        status_area = st.empty()
        
        summary = {t: {'name': t, 'f': 0, 'it': 0, 'd': 0, 'tot': 0} for t in targets}
        start_time_exec = time.time()
        
        # --- 高速逐檔掃描 (By Stock) ---
        for i, stock in enumerate(targets):
            status_area.markdown(f'<div class="status-box"><b>⚡ 高速掃描中：[{i+1}/{total_tasks}]</b><br>正在獲取：代號 {stock} 多日資料</div>', unsafe_allow_html=True)
            
            # 抓取該股票的三大法人合併資料
            df, s_name = fetch_stock_all_institutions(stock)
            summary[stock]['name'] = s_name
            
            if df is not None and not df.empty:
                # 根據使用者選擇的日期區間進行過濾
                mask = (df['date'] >= start_date) & (df['date'] <= end_date)
                filtered_df = df.loc[mask].copy()
                
                if not filtered_df.empty:
                    # 計算總和供深度報告使用
                    summary[stock]['f'] = filtered_df['f_net'].sum()
                    summary[stock]['it'] = filtered_df['it_net'].sum()
                    summary[stock]['d'] = filtered_df['d_net'].sum()
                    summary[stock]['tot'] = filtered_df['total_net'].sum()
                    all_data_list.append(filtered_df)
            
            progress_bar.progress((i + 1) / total_tasks)

        if all_data_list:
            full_df = pd.concat(all_data_list).sort_values('date')
            elapsed_time = round(time.time() - start_time_exec, 1)
            status_area.success(f"✅ 掃描完成！耗時 {elapsed_time} 秒。")
            
            # --- Toggle 功能區 ---
            st.divider()
            view_mode = st.radio("選擇顯示維度", ["三大法人總計", "外資", "投信", "自營商"], horizontal=True, index=0)
            mode_map = {"三大法人總計": "total_net", "外資": "f_net", "投信": "it_net", "自營商": "d_net"}
            target_col = mode_map[view_mode]

            for stock in targets:
                sub_df = full_df[full_df['id'] == stock].copy()
                if sub_df.empty:
                    continue
                
                # 將日期強制轉為純字串，徹底解決 Plotly X軸時間與重影問題
                sub_df['date_str'] = sub_df['date'].apply(lambda d: d.strftime('%m/%d'))
                
                fig = go.Figure()
                y_vals = sub_df[target_col] // 1000  # 轉為張數
                
                fig.add_trace(go.Bar(
                    x=sub_df['date_str'], y=y_vals,
                    marker_color=['#ef5350' if x>=0 else '#66bb6a' for x in y_vals],
                    hovertemplate="日期: %{x}<br>張數: %{y:+.0f} 張<extra></extra>"
                ))
                
                fig.update_layout(
                    title=f"【{summary[stock]['name']}】{view_mode} (張)",
                    template="plotly_dark", margin=dict(l=10, r=10, t=50, b=10), height=350,
                    xaxis=dict(type='category', tickangle=-45) # category 強制純文字分類
                )
                st.plotly_chart(fig, use_container_width=True)

            # --- 深度報告區 ---
            st.divider()
            st.subheader("📋 深度會診報告")
            r_label = st.session_state.get('range_label', '自定義')
            report = f"【期間：{start_date} ~ {end_date}】\n【區間：{r_label}】\n" + "═"*45 + "\n\n"
            for title, key in [("[三大法人總和]", 'tot'), ("[外資]", 'f'), ("[投信]", 'it'), ("[自營商]", 'd')]:
                report += f"{title}\n"
                for s in targets: 
                    if summary[s]['tot'] != 0 or summary[s]['f'] != 0: # 有資料才顯示
                        report += f"{summary[s]['name']}: {summary[s][key]//1000:+.0f} 張\n"
                report += "\n"
            st.code(report, language="text")
        else:
            status_area.error("❌ 查無資料。可能是所選日期無交易，或股票代碼錯誤。")
