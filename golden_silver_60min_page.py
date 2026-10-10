"""
golden_silver_60min_page.py — V1 第 11 個 page「⏰ 60分K 金包銀形態掃描」UI

跟 golden_silver_page.py (日K) 對應, 但資料源是 shioaji 60分K:
- 來自 /Users/kevin/Desktop/排程運算/shioaji_kbar/data/
- 用 KBarLoader.read_stock() 讀單檔 parquet
- MA 期間用「根數」而非「日數」(60/120/240 根 = 2.5/5/10 日)
- 量縮: 24根 (≈1日) / 240根 (≈10日) 比率
- 突破: 收盤 / MA 比率 > 1.005
- 不含三大法人 (永豐純 K 棒, 沒法人資料)

如果 data/ 還沒抓, UI 顯示提示訊息「請先跑 shioaji_kbar 抓取」。
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import sys

# 加 shioaji_kbar/scripts 到 sys.path
SHIOAJI_KBAR_SCRIPTS = Path('/Users/kevin/Desktop/排程運算/shioaji_kbar/scripts')
if str(SHIOAJI_KBAR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SHIOAJI_KBAR_SCRIPTS))


@st.cache_resource
def _get_kbar_loader():
    """KBarLoader 是檔案系統物件, 用 cache_resource 確保只初始化一次"""
    from backtest_data_loader import KBarLoader
    return KBarLoader()


@st.cache_data(ttl=1800, show_spinner="抓 60分K 資料 + 掃金包銀型態…")
def _cached_scan_60min(
    market_cap_top: int,
    market_filter: tuple,
    ma_fast: int,
    ma_mid: int,
    ma_slow: int,
    vol_fast: int,
    vol_slow: int,
    tolerance_pct: float,
    vol_shrink_ratio: float,
    break_threshold: float,
    min_score: int,
) -> pd.DataFrame:
    """掃全市場 60分K 金包銀型態"""
    from golden_silver_60min import scan_golden_silver_60min
    from finlab import data as _finlab_data

    loader = _get_kbar_loader()
    if loader._per_stock_dir is None:
        return pd.DataFrame()  # 沒抓到資料, 回空

    # 取 finlab 市值 + 證券清單
    mv = _finlab_data.get('etl:market_value')
    secs = _finlab_data.get('security_categories')
    pure = secs[(secs['market'] != 'rotc') & (secs['market'] != 'etf')].copy()
    pure['stock_id'] = pure['stock_id'].astype(str)

    mv_last = mv.iloc[-1]
    mv_last.index = mv_last.index.astype(str)
    mv_map = mv_last.to_dict()
    name_map = dict(zip(pure['stock_id'], pure['name']))
    market_map = dict(zip(pure['stock_id'], pure['market']))

    industry_map = {}
    try:
        basic = _finlab_data.get('company_basic_info')
        if 'stock_id' in basic.columns and '產業類別' in basic.columns:
            basic['stock_id'] = basic['stock_id'].astype(str)
            industry_map = dict(zip(basic['stock_id'], basic['產業類別']))
    except Exception:
        pass

    # 市值前 N 大 (且 shioaji_kbar 已有資料)
    available = set(loader.list_available())
    mv_top = {sid: v for sid, v in mv_map.items()
              if v > 0 and sid in pure['stock_id'].values and sid in available
              and pure[pure['stock_id'] == sid]['market'].iloc[0] in market_filter}
    sorted_mv = sorted(mv_top.items(), key=lambda x: x[1], reverse=True)
    stock_ids = [s for s, _ in sorted_mv[:market_cap_top]]

    df = scan_golden_silver_60min(
        stock_ids=stock_ids,
        kbar_loader=loader,
        market_cap_map=mv_map,
        name_map=name_map,
        market_map=market_map,
        industry_map=industry_map,
        ma_fast=ma_fast,
        ma_mid=ma_mid,
        ma_slow=ma_slow,
        vol_fast=vol_fast,
        vol_slow=vol_slow,
        tolerance_pct=tolerance_pct,
        vol_shrink_ratio=vol_shrink_ratio,
        break_threshold=break_threshold,
    )
    if min_score > 0 and not df.empty:
        df = df[df['訊號分數'] >= min_score].copy()
    return df


def render_golden_silver_60min_page():
    """⏰ 60分K 金包銀形態掃描 page (V1 第 11 個)"""
    st.header("⏰ 60分K 金包銀形態掃描")
    st.caption(
        "從 shioaji 60分K 抓全市場 K 棒，偵測「金包銀」壓縮型態 (60分K 版)。"
        "資料源: `/Users/kevin/Desktop/排程運算/shioaji_kbar/data/`。"
    )

    # ============ 檢查資料是否已抓到 ============
    loader = _get_kbar_loader()
    if loader._per_stock_dir is None:
        st.error(
            "❌ **找不到 60分K 資料** — 請先跑 shioaji_kbar 抓取。\n\n"
            "**步驟**:\n"
            "1. 設定 shioaji API key: `cp .env.example .env` 然後編輯填 key\n"
            "2. 跑全市場抓取 (約 1-2 小時, 背景跑):\n"
            "```bash\n"
            "cd /Users/kevin/Desktop/排程運算/shioaji_kbar\n"
            "export SHIOAJI_API_KEY='你的key'\n"
            "export SHIOAJI_SECRET_KEY='你的secret'\n"
            "/opt/anaconda3/envs/finlab3/bin/python scripts/fetch_all_60min_kbars.py --days 365\n"
            "```\n"
            "3. 抓完跑 build + features:\n"
            "```bash\n"
            "/opt/anaconda3/envs/finlab3/bin/python scripts/build_wide_format.py\n"
            "/opt/anaconda3/envs/finlab3/bin/python scripts/compute_features.py\n"
            "```\n"
            "4. 重新整理本頁"
        )
        return

    available = loader.list_available()
    st.success(
        f"✅ **60分K 資料已就緒**: {len(available)} 檔, "
        f"路徑: `{loader._per_stock_dir}`"
    )

    # ============ 控制面板 ============
    with st.expander("⚙️ 篩選條件", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            market_cap_top = st.selectbox(
                "市值前幾大 (有 60分K 資料的)",
                options=[100, 200, 300, 500, 1000],
                index=2,
                key="gs60_mv_top",
                help=f"用 etl:market_value 排序, 但只算有 60分K 資料的 (目前 {len(available)} 檔)",
            )
            market_filter = st.multiselect(
                "市場別",
                options=['sii', 'otc'],
                default=['sii', 'otc'],
                key="gs60_market",
                format_func=lambda x: {'sii': '上市 (sii)', 'otc': '上櫃 (otc)'}.get(x, x),
            )
        with col2:
            st.markdown("**3 條 MA 期間 (根數)**")
            ma_fast = st.number_input(
                f"MA_fast (≈X 日)", min_value=5, max_value=480, value=60, step=10,
                key="gs60_ma_fast",
                help="60分K 60根 ≈ 2.5 個交易日",
            )
            ma_mid = st.number_input(
                f"MA_mid (≈X 日)", min_value=10, max_value=480, value=120, step=10,
                key="gs60_ma_mid",
                help="60分K 120根 ≈ 5 個交易日",
            )
            ma_slow = st.number_input(
                f"MA_slow (≈X 日)", min_value=20, max_value=960, value=240, step=20,
                key="gs60_ma_slow",
                help="60分K 240根 ≈ 10 個交易日",
            )
        with col3:
            st.markdown("**量縮比較 (根數)**")
            vol_fast = st.number_input(
                f"vol_fast (≈1日)", min_value=4, max_value=120, value=24, step=4,
                key="gs60_vol_fast",
                help="60分K 24根 ≈ 1 個交易日",
            )
            vol_slow = st.number_input(
                f"vol_slow (≈10日)", min_value=24, max_value=960, value=240, step=20,
                key="gs60_vol_slow",
            )
        col4, col5, col6 = st.columns(3)
        with col4:
            tolerance_pct = st.slider(
                "🎯 夾擊容差 (%)",
                min_value=0.3, max_value=5.0, value=1.0, step=0.1,
                key="gs60_tolerance",
                help="60分K 較敏感, 預設 ±1% (比日K 3% 嚴格)",
            )
        with col5:
            vol_shrink_ratio = st.slider(
                "📉 量縮門檻 (vol_fast / vol_slow < )",
                min_value=0.5, max_value=1.0, value=0.8, step=0.05,
                key="gs60_vol_ratio",
            )
        with col6:
            break_threshold = st.slider(
                "🚀 突破門檻 (收盤/上蓋 MA > )",
                min_value=1.00, max_value=1.05, value=1.005, step=0.001,
                key="gs60_break",
                help="60分K 0.5% 即算突破 (比日K 1% 敏感)",
            )
        min_score = st.slider(
            "⭐ 最低訊號分數 (0-4)",
            min_value=0, max_value=4, value=1, step=1,
            key="gs60_min_score",
        )

    if not market_filter:
        st.warning("請選擇至少一個市場別")
        return

    if ma_fast >= ma_mid or ma_mid >= ma_slow:
        st.error("⚠️ MA 期間必須 fast < mid < slow")
        return

    try:
        df = _cached_scan_60min(
            market_cap_top=market_cap_top,
            market_filter=tuple(market_filter),
            ma_fast=ma_fast,
            ma_mid=ma_mid,
            ma_slow=ma_slow,
            vol_fast=vol_fast,
            vol_slow=vol_slow,
            tolerance_pct=tolerance_pct,
            vol_shrink_ratio=vol_shrink_ratio,
            break_threshold=break_threshold,
            min_score=min_score,
        )
    except Exception as e:
        st.error(f"Scan 失敗: {e}")
        import traceback
        st.code(traceback.format_exc())
        return

    if df.empty:
        st.warning(f"沒有符合條件的個股 ({len(available)} 檔 60分K 資料中)。請放寬篩選條件")
        return

    # ============ 統計指標 ============
    st.divider()
    last_data_time = df['資料時間'].max() if not df.empty else None
    last_data_str = last_data_time.strftime('%Y-%m-%d %H:%M') if pd.notna(last_data_time) else '?'
    st.caption(
        f"📅 資料時間 **{last_data_str}** (60分K) ｜ 符合條件 **{len(df)} 檔**"
    )

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("符合條件", f"{len(df)} 檔")
    m2.metric("🟢 突破表態", f"{(df['訊號'] == '🟢 突破表態').sum()} 檔")
    m3.metric("🟢 突破後回踩", f"{(df['訊號'] == '🟢 突破後回踩').sum()} 檔")
    m4.metric("🟡 量縮整理", f"{(df['訊號'] == '🟡 量縮整理').sum()} 檔")
    m5.metric("⚪ 觀察", f"{(df['訊號'] == '⚪ 觀察').sum()} 檔")

    # ============ Top chart (訊號分數排名) ============
    st.divider()
    st.markdown("#### 🏆 訊號分數排名 (Top 30)")

    df_sorted = df.sort_values('訊號分數', ascending=False).reset_index(drop=True)
    top30 = df_sorted.head(30).copy()

    color_map = {
        '🟢 突破表態': '#26a69a',
        '🟢 突破後回踩': '#42a5f5',
        '🟡 量縮整理': '#ffa726',
        '⚪ 觀察': '#9e9e9e',
    }
    bar_colors = [color_map.get(lbl, '#9e9e9e') for lbl in top30['訊號']]
    bar_labels = [f"{r['名稱']} ({r['stock_id']})" for _, r in top30.iterrows()]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        y=bar_labels,
        x=top30['訊號分數'],
        orientation='h',
        marker_color=bar_colors,
        text=[f"{s} 分" for s in top30['訊號分數']],
        textposition='outside',
        hovertemplate=(
            '<b>%{y}</b><br>'
            '訊號分數: %{x} / 4<br>'
            '訊號: %{customdata[0]}<br>'
            '收盤: %{customdata[1]:.2f}<br>'
            f'MA{ma_fast}: ' + '%{customdata[2]:.2f}<br>'
            '夾擊帶寬度: %{customdata[3]:.2f}%<br>'
            '量縮比: %{customdata[4]:.3f}<extra></extra>'
        ),
        customdata=top30[['訊號', '收盤', f'MA{ma_fast}', '夾擊帶寬度%', '量縮比']].values,
    ))
    fig_bar.update_layout(
        height=700,
        title="Top 30 訊號分數排名 (60分K)",
        xaxis=dict(title="訊號分數 (0-4)", range=[0, 4.5]),
        yaxis=dict(autorange='reversed'),
        margin=dict(l=130),
    )
    st.plotly_chart(fig_bar, width="stretch")

    # ============ 完整明細表 ============
    st.divider()
    st.markdown("#### 📋 完整明細表 (60分K)")
    display_cols = [
        'stock_id', '名稱', '市場', '產業', '市值(億)', '資料時間',
        '收盤', f'MA{ma_fast}', f'MA{ma_mid}', f'MA{ma_slow}', 'upper_ma',
        '夾擊帶寬度%', f'MA{ma_fast}距離%', '上蓋距離%',
        f'量MA{vol_fast}(根)', f'量MA{vol_slow}(根)', '量縮比',
        f'突破MA{ma_mid}', f'突破MA{ma_slow}', '近5日內突破', '實體長紅',
        '訊號', '訊號分數',
    ]
    display_df = df_sorted[display_cols].copy()
    # 格式化
    for col in [f'MA{ma_fast}', f'MA{ma_mid}', f'MA{ma_slow}', 'upper_ma']:
        display_df[col] = display_df[col].apply(lambda x: f"{x:,.2f}")
    display_df['收盤'] = display_df['收盤'].apply(lambda x: f"{x:,.2f}")
    for col in ['夾擊帶寬度%', f'MA{ma_fast}距離%', '上蓋距離%']:
        display_df[col] = display_df[col].apply(lambda x: f"{x:+.2f}%")
    display_df['量縮比'] = display_df['量縮比'].apply(lambda x: f"{x:.3f}")
    for col in [f'量MA{vol_fast}(根)', f'量MA{vol_slow}(根)']:
        display_df[col] = display_df[col].apply(lambda x: f"{x:,.0f}")
    for col in [f'突破MA{ma_mid}', f'突破MA{ma_slow}', '近5日內突破', '實體長紅']:
        display_df[col] = display_df[col].apply(lambda x: '✅' if x else '—')
    display_df['市值(億)'] = display_df['市值(億)'].apply(lambda x: f"{x:,.0f}")
    # 資料時間轉 str
    display_df['資料時間'] = display_df['資料時間'].apply(
        lambda x: x.strftime('%Y-%m-%d %H:%M') if pd.notna(x) else '?'
    )
    st.dataframe(display_df, hide_index=True, width="stretch", height=600)

    # ============ CSV 下載 ============
    csv_bytes = df_sorted.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"⬇️ 下載完整清單 ({len(df)} 檔 CSV)",
        data=csv_bytes,
        file_name=f"golden_silver_60min_{last_data_str.replace(' ', '_').replace(':', '')}.csv",
        mime="text/csv",
        key="gs60_download_csv",
    )

    # ============ 公式說明 ============
    with st.expander("📐 60分K 版公式說明 & 跟日K 版差異"):
        st.markdown(f"""
### 60分K 版「金包銀」型態

```
3 條 MA (根數):
  MA_fast  = {ma_fast} 根 ≈ {ma_fast/4:.1f} 個交易日
  MA_mid   = {ma_mid} 根 ≈ {ma_mid/4:.1f} 個交易日
  MA_slow  = {ma_slow} 根 ≈ {ma_slow/4:.1f} 個交易日

夾擊 = MA_fast < 收盤 < max(MA_mid, MA_slow)  (容差 ±{tolerance_pct}%)

量縮 = MA_vol_fast / MA_vol_slow < {vol_shrink_ratio}
  vol_fast = {vol_fast} 根 (≈ {vol_fast/4:.1f} 日)
  vol_slow = {vol_slow} 根 (≈ {vol_slow/4:.1f} 日)

突破 = 收盤 > max(MA_mid, MA_slow) × {break_threshold}
```

### 跟日K 版差異

| 項目 | 日K 版 | 60分K 版 |
|---|---|---|
| 資料頻率 | 日 (1 根/日) | 60 分 (4 根/日) |
| MA 60 意義 | 60 個交易日 ≈ 3 個月 | 60 根 ≈ 2.5 日 |
| MA 240 意義 | 240 個交易日 ≈ 12 個月 | 240 根 ≈ 10 日 |
| 靈敏度 | 中 (適合波段) | 高 (適合短中線) |
| 容差預設 | ±3% | ±1% (更嚴格) |
| 突破門檻 | × 1.01 | × 1.005 (更敏感) |
| 量縮比較 | 5日 / 60日 | 24根 / 240根 (≈1日/10日) |
| 三大法人 | ✅ (finlab) | ❌ (永豐純 K 棒) |

### 4 種訊號 (跟日K 版同)

- 🟢 **突破表態**: 夾擊 + 突破 + 實體長紅
- 🟢 **突破後回踩**: 夾擊 + 量縮 + 近 5 日內曾突破
- 🟡 **量縮整理**: 夾擊 + 量縮 (但還沒突破)
- ⚪ **觀察**: 夾擊但沒量縮沒突破
- 🔴 不符 (不加入結果)
""")


if __name__ == '__main__':
    print("golden_silver_60min_page module loaded OK")
