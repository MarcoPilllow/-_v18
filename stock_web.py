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
            if len(df) < 2: continue
