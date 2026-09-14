#!/opt/anaconda3/envs/finlab3/bin/python
# coding: utf-8
"""
portfolio_strategy_page.py — 第 9 個 V1 page：「🧬 基因策略組合」

從 Finlab組合策略_20260226.ipynb 抽出來的 Streamlit 介面化版本。

功能：
1. 預設組合 (22 個 cell 註解的 best combo) — dropdown 選 → 顯示歷史 stats → 驗證回測
2. 自訂組合 (41 個 cond 自由勾選) → 跑 sim() → 顯示 stats + equity curve + trades
3. 蒙地卡羅壓力測試 (95/97.5/99/99.7% 4 分位 Sortino/Omega 衰減)
4. 對大盤 Omega Ratio
5. Portfolio 4 策略組合 (從 cell 7-8)
"""
from __future__ import annotations

import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import portfolio_strategy as ps


# ============================================================
# 載入 features（cache 一小時，跨 user session 共用）
# ============================================================
@st.cache_data(ttl=3600, show_spinner="抓全市場特徵中（首次 ~30 秒）…")
def _cached_load_features():
    return ps.load_features()


# ============================================================
# Page render
# ============================================================
def render_portfolio_page():
    st.header("🧬 基因策略組合")
    st.caption(
        "從 Finlab組合策略_20260226.ipynb 抽出來的台股量化回測介面。"
        "22 個歷史最佳組合來自 notebook cell 註解（已驗證 CAGR/MDD/Sortino）；"
        "自訂組合可選 41 個條件自由組合。"
    )

    # ============ Tab 切換：預設組合 vs 自訂組合 ============
    tab_preset, tab_custom, tab_portfolio, tab_stress = st.tabs([
        "📚 預設組合", "🧪 自訂組合", "💼 Portfolio 組合", "🎲 蒙地卡羅壓力"
    ])

    # ----- Tab 1: 預設組合 -----
    with tab_preset:
        st.subheader("📚 22 個歷史最佳組合")
        st.caption("從 notebook cell 1-6, 17, 18 的 cell 註解抄出，回測日期 2019 至今")

        combo_names = [c['name'] for c in ps.PRESET_COMBOS]
        selected_idx = st.selectbox(
            "選擇組合",
            range(len(combo_names)),
            format_func=lambda i: combo_names[i],
            key="preset_combo_select",
        )
        combo = ps.PRESET_COMBOS[selected_idx]

        # 條件顯示
        cond_cols = st.columns([1, 1])
        with cond_cols[0]:
            st.markdown("**啟用條件**")
            for c in combo['conditions']:
                st.markdown(f"- ✅ `{c}` {ps.CONDITION_LABELS.get(c, '')}")
        with cond_cols[1]:
            st.markdown("**歷史回測成績**（活報不刷新）")
            s = combo['stats']
            mc = st.columns(3)
            mc[0].metric("CAGR", f"{s['CAGR']}%")
            mc[0].markdown(f"")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("MDD", f"{s['MDD']}%")
            m2.metric("Sortino", f"{s['Sortino']}")
            m3.metric("Omega", f"{s['Omega']}")
            m4.metric("勝率", f"{s['勝率']}%")
            m5, m6 = st.columns(2)
            m5.metric("月損益", f"{s['月損益(萬)']} 萬")
            m6.metric("月勝率", f"{s['月勝率']}%" if s['月勝率'] > 0 else "—")
            st.caption(f"來源：{combo['source']}")

        st.divider()

        # 回測按鈕
        if st.button("🚀 用 finlab 重新驗證回測", key="preset_run", type="primary"):
            _run_backtest_ui(combo['conditions'], prefix="preset")

    # ----- Tab 2: 自訂組合 -----
    with tab_custom:
        st.subheader("🧪 自訂條件組合")
        st.caption("從 41 個條件自由組合，先選條件再看回測結果")

        # 條件分組（依類別）
        categories = {
            '📈 營收 / 財報 (cond1-3, 16-20)': ['cond1', 'cond2', 'cond3', 'cond16', 'cond17', 'cond18', 'cond19', 'cond20'],
            '📊 技術指標 (cond4-10)': ['cond4', 'cond5', 'cond6', 'cond7', 'cond8', 'cond9', 'cond10'],
            '💰 流動 / 市值 (cond11, 12, 33-35)': ['cond11', 'cond12', 'cond33', 'cond34', 'cond35'],
            '📉 價量關係 (cond13-15, 26-38)': ['cond13', 'cond14', 'cond15', 'cond26', 'cond27', 'cond28', 'cond30', 'cond31', 'cond32', 'cond36', 'cond37', 'cond38'],
            '🎯 波動率 (cond23, 24)': ['cond23', 'cond24'],
            '🏔️ 新高 (cond25, 28, 30, 31)': ['cond25', 'cond28', 'cond30', 'cond31'],
            '🔥 KD (cond21, 22)': ['cond21', 'cond22'],
            '🏦 大戶籌碼 (cond29)': ['cond29'],
            '📊 市值變化 (cond39-41)': ['cond39', 'cond40', 'cond41'],
        }

        active_conditions = []
        for cat_idx, (cat, conds) in enumerate(categories.items()):
            with st.expander(cat, expanded=False):
                cols = st.columns(2)
                for i, c in enumerate(conds):
                    if c not in ps.CONDITIONS:
                        continue
                    label = f"`{c}` {ps.CONDITION_LABELS.get(c, '')}"
                    with cols[i % 2]:
                        if st.checkbox(label, key=f"custom_g{cat_idx}_{c}"):
                            active_conditions.append(c)

        st.markdown(f"**已選 {len(active_conditions)} 個條件**：`{', '.join(active_conditions) if active_conditions else '（無）'}`")

        # 進階參數
        st.divider()
        adv_cols = st.columns(3)
        with adv_cols[0]:
            nstocks = st.slider("同時持有最多 (檔)", 1, 20, 5, key="custom_nstocks")
        with adv_cols[1]:
            position_pct = st.slider("單檔最大倉位 (%)", 10, 100, 33, step=5, key="custom_pos_pct") / 100
        with adv_cols[2]:
            fee_bps = st.slider("手續費 (bps)", 1, 100, 43, key="custom_fee") / 10000

        st.divider()
        if not active_conditions:
            st.warning("⚠️ 至少勾一個條件才能回測")
        elif st.button("🚀 開始回測", key="custom_run", type="primary"):
            _run_backtest_ui(
                active_conditions,
                prefix="custom",
                nstocks_limit=nstocks,
                position_limit=position_pct,
                fee_ratio=fee_bps,
            )

    # ----- Tab 3: Portfolio 4 策略組合 -----
    with tab_portfolio:
        st.subheader("💼 Portfolio：4 策略組合（沿用 notebook cell 7-8）")
        st.caption("把幾個歷史 best 策略等權重 (1/4) 組合成 Portfolio，用 finlab.portfolio 顯示組合表現")

        port_cols = st.columns(2)
        with port_cols[0]:
            st.markdown("預設組合 1（notebook cell 7）：")
            st.code("""
port = Portfolio({
    '基因比對_營收KD值高_MDD低': (report, 1/4),
    '策略2_Finlab': (report2, 1/4),
    '均線型態_成交量成長_十日線以上': (report11, 1/4),
    '策略10_Finlab': (report10, 1/4),
})
port.display()
            """, language='python')
        with port_cols[1]:
            st.markdown("預設組合 2（notebook cell 8）：")
            st.code("""
port = Portfolio({
    '基因比對_營收KD值高_MDD低': (report, 1/4),
    '策略2_Finlab': (report2, 1/4),
    '策略4_Finlab': (report4, 1/4),
    '策略8_Finlab': (report8, 1/4),
})
port.display()
            """, language='python')

        st.info(
            "💡 Portfolio 頁面需要先跑 4 個獨立 sim() → 拿到 4 個 report 才能組合成 Portfolio。"
            "建議先在『自訂組合』tab 跑 4 次不同條件組合 → 把結果餵給 Portfolio。"
            "完整實作留待下一版。"
        )

    # ----- Tab 4: 蒙地卡羅壓力測試 -----
    with tab_stress:
        st.subheader("🎲 蒙地卡羅壓力測試（bootstrap）")
        st.caption("從回測的每日報酬 bootstrap 重抽，計算 Sortino / Omega 在 4 個風險分位的衰減")

        if 'last_report' not in st.session_state or st.session_state['last_report'] is None:
            st.warning("⚠️ 請先在『預設組合』或『自訂組合』tab 跑一次回測，這裡才能用")
        else:
            report = st.session_state['last_report']
            iters = st.slider("蒙地卡羅迭代次數", 1000, 20000, 5000, step=1000)

            if st.button("🎲 跑壓力測試", type="primary"):
                progress = st.progress(0.0, text="蒙地卡羅模擬中…")
                # 用 session state 內 streamlit progress bar 不能傳到外部 fn，所以直接跑
                result = ps.monte_carlo_stress_test(report, iterations=iters)
                progress.progress(1.0, text="完成")

                if result is None:
                    st.error("無法取得回測報酬數據")
                else:
                    # 4 個分位數衰減表
                    st.markdown("#### 4 風險等級衰減")
                    level_data = pd.DataFrame({
                        '風險等級': ['95.0%', '97.5%', '99.0%', '99.7% (3σ)'],
                        'Sortino': [
                            result['sortino_p95'], result['sortino_p975'],
                            result['sortino_p99'], result['sortino_p997'],
                        ],
                        'Omega': [
                            result['omega_p95'], result['omega_p975'],
                            result['omega_p99'], result['omega_p997'],
                        ],
                        'Sortino 累計衰減': [
                            '0% (基準)',
                            f"{(result['sortino_p95']-result['sortino_p975'])/result['sortino_p95']*100:+.1f}%",
                            f"{(result['sortino_p95']-result['sortino_p99'])/result['sortino_p95']*100:+.1f}%",
                            f"{(result['sortino_p95']-result['sortino_p997'])/result['sortino_p95']*100:+.1f}%",
                        ],
                    })
                    st.dataframe(level_data, hide_index=True, width="stretch")
                    st.caption(
                        f"基準 Sortino（中位數）: {result['sortino_baseline']:.2f}　"
                        f"基準 Omega（中位數）: {result['omega_baseline']:.2f}　"
                        f"迭代: {result['n_iterations']:,} 次"
                    )

                    # 對大盤 Omega Ratio
                    st.divider()
                    st.markdown("#### 對大盤的 Omega Ratio（cell 9 邏輯）")
                    omega_vs_market = ps.omega_score_vs_benchmark(report)
                    if omega_vs_market == float('inf'):
                        st.success("∞ （策略報酬完全優於大盤無虧損日）")
                    else:
                        st.metric("Omega (vs 加權指數)", f"{omega_vs_market:.3f}",
                                  help=">1 表示策略表現優於大盤")
                        if omega_vs_market > 1.5:
                            st.success("✅ 顯著優於大盤")
                        elif omega_vs_market > 1.0:
                            st.info("ℹ️ 略優於大盤")
                        else:
                            st.warning("⚠️ 跟大盤差不多或較差")


# ============================================================
# 內部 helper：跑回測的 UI flow
# ============================================================
def _run_backtest_ui(active_conditions, prefix="", nstocks_limit=5, position_limit=1/3, fee_ratio=None):
    if fee_ratio is None:
        fee_ratio = 1.425/1000*0.3

    progress = st.progress(0.0, text="載入特徵…")
    try:
        features = _cached_load_features()
    except Exception as e:
        st.error(f"❌ 載入 finlab 資料失敗：`{e}`")
        return

    progress.progress(0.1, text="跑 sim() 回測中…（首次可能下載資料 1-5 分鐘）")

    last_msg = [None]
    def cb(i, total, msg):
        last_msg[0] = msg
        if i is not None and total:
            pct = (i + 1) / total
            progress.progress(min(pct, 0.95), text=f"({i+1}/{total}) {msg}")

    try:
        report = ps.run_backtest(
            active_conditions,
            features,
            nstocks_limit=nstocks_limit,
            position_limit=position_limit,
            fee_ratio=fee_ratio,
            progress_callback=cb,
        )
    except Exception as e:
        progress.empty()
        st.error(f"❌ 回測失敗：`{type(e).__name__}: {e}`")
        import traceback
        with st.expander("看 traceback"):
            st.code(traceback.format_exc())
        return

    progress.progress(1.0, text="完成 ✅")
    st.session_state['last_report'] = report
    st.session_state['last_active_conditions'] = active_conditions

    # ---- 結果顯示 ----
    st.divider()
    st.subheader(f"📊 回測結果（條件 `{', '.join(active_conditions)}`）")

    stats = ps.extract_report_stats(report)
    mc = st.columns(5)
    mc[0].metric("Sortino (日)", f"{stats['daily_sortino']:.2f}" if stats['daily_sortino'] is not None else "—")
    mc[1].metric("年化報酬", f"{stats['annual_return']*100:.1f}%" if stats['annual_return'] is not None else "—")
    mc[2].metric("最大回撤", f"{stats['max_drawdown']*100:.1f}%" if stats['max_drawdown'] is not None else "—")
    mc[3].metric("Sharpe (日)", f"{stats['daily_sharpe']:.2f}" if stats['daily_sharpe'] is not None else "—")

    # ---- Equity curve ----
    st.markdown("#### 📈 累計報酬曲線")
    try:
        creturn = report.creturn
        if hasattr(creturn, 'index'):
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=creturn.index, y=creturn.values,
                name='策略累計報酬', line=dict(color='#26a69a', width=2)
            ))
            # 加 benchmark
            try:
                from finlab import data as _data
                benchmark = _data.get('benchmark_return:發行量加權股價報酬指數').squeeze()
                bench_norm = benchmark / benchmark.iloc[0] * creturn.iloc[0]
                bench_aligned = benchmark.reindex(creturn.index).dropna()
                fig.add_trace(go.Scatter(
                    x=bench_aligned.index, y=bench_aligned.values,
                    name='加權指數', line=dict(color='#888', width=1, dash='dot')
                ))
            except Exception:
                pass
            fig.update_layout(height=400, hovermode='x unified')
            st.plotly_chart(fig, width="stretch")
        else:
            st.dataframe(creturn.head(50))
    except Exception as e:
        st.warning(f"無法繪製 equity curve：`{e}`")

    # ---- Trades table ----
    st.divider()
    st.markdown("#### 📋 最近 30 筆交易")
    try:
        trades = report.trades.tail(30).copy()
        st.dataframe(trades, hide_index=True, width="stretch")
        csv = trades.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ 下載 trades CSV",
            data=csv,
            file_name=f"trades_{prefix}_{'_'.join(active_conditions)}.csv",
            mime="text/csv",
        )
    except Exception as e:
        st.warning(f"無法取得 trades：`{e}`")

    st.success("✅ 回測完成！可去『蒙地卡羅壓力』tab 看壓力測試")
