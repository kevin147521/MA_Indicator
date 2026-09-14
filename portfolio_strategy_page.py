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

    # ----- Tab 3: Portfolio 4 策略組合（跟預設組合同樣兩欄佈局） -----
    with tab_portfolio:
        st.subheader("💼 Portfolio：4 策略組合（沿用 notebook cell 7-8）")
        st.caption("從 notebook cell 7-8 抽出的 4 策略 1/4 等權組合，可組合成 Portfolio 並推到 finlab cloud。")

        # 1) 選 combo
        preset_names = [p['name'] for p in ps.PORTFOLIO_PRESETS]
        preset_idx = st.selectbox(
            "選擇 Portfolio 組合",
            range(len(preset_names)),
            format_func=lambda i: preset_names[i],
            key="portfolio_preset_select",
        )
        preset = ps.PORTFOLIO_PRESETS[preset_idx]

        # 2) 兩欄：左 = 啟用策略, 右 = 組合說明（跟預設 tab 一致）
        cond_cols = st.columns([1, 1])
        with cond_cols[0]:
            st.markdown("**啟用策略**")
            for s in preset['strategies']:
                st.markdown(
                    f"- ✅ **{s['name']}** (cell {s.get('cell', '?')}, "
                    f"{len(s['conditions'])} 條件, weight {s['weight']*100:.0f}%)"
                )
        with cond_cols[1]:
            st.markdown("**組合說明**")
            st.caption(preset['description'])
            st.caption(f"來源：notebook cell {'7' if preset_idx == 0 else '8'}")
            st.caption(f"權重：4 策略各 1/4 等權（共 100%）")
            n_total_cond = sum(len(s['conditions']) for s in preset['strategies'])
            st.caption(f"條件總數：{n_total_cond}（跨 {len(preset['strategies'])} 策略）")
            st.caption(f"跑 sim 預估耗時：~20 秒（cache hit 後每個 4-5 秒）")

        # 3) 進階參數（折疊，跟預設 tab 的 expander 一致）
        with st.expander("⚙️ 進階參數（選填）", expanded=False):
            adv = st.columns(3)
            with adv[0]:
                total_balance = st.number_input(
                    "總資金 (TWD)", min_value=100_000, max_value=100_000_000,
                    value=12_000_000, step=1_000_000,
                    help="推到 finlab cloud 時的總倉位大小",
                    key="port_total_balance",
                )
            with adv[1]:
                rebalance_safety_weight = st.slider(
                    "Rebalance 安全權重 (0=積極)", 0.0, 0.5, 0.0, step=0.05,
                    key="port_rebalance",
                )
            with adv[2]:
                save_version_name = st.text_input(
                    "資料版本名稱", value=f"v{preset_idx+1}_comb{preset_idx+1}",
                    key="port_version_name",
                    help="存 SQLite / JSON 時用的 version id",
                )

        # 4) 主按鈕（跟預設 tab 一樣 type="primary"）
        if st.button("🚀 組 Portfolio（跑 4 個 sim() + 組合）", type="primary", key="port_compose"):
            _compose_portfolio_ui(preset_idx, total_balance, rebalance_safety_weight)

        # 5) 結果顯示區（組完才出現，跟預設 tab 的「回測結果」section 一致）
        if st.session_state.get('portfolio_result'):
            st.divider()
            _render_portfolio_result(st.session_state['portfolio_result'])

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


# ============================================================
# Portfolio tab 用的 helper
# ============================================================
def _compose_portfolio_ui(preset_idx: int, total_balance: float, rebalance_safety_weight: float):
    """跑 4 個 sim() + 組 Portfolio + 存 session_state"""
    preset = ps.PORTFOLIO_PRESETS[preset_idx]
    progress = st.progress(0.0, text="載入特徵…")

    try:
        features = _cached_load_features()
    except Exception as e:
        progress.empty()
        st.error(f"❌ 載入 finlab 資料失敗：`{e}`")
        return

    progress.progress(0.1, text=f"跑 {len(preset['strategies'])} 個 sim()...")

    def cb(i, total, msg):
        if i is not None and total:
            pct = 0.1 + 0.85 * (i + 1) / total
            progress.progress(min(pct, 0.95), text=f"({i+1}/{total}) {msg}")

    try:
        result = ps.compose_portfolio(preset, features, progress_callback=cb)
    except Exception as e:
        progress.empty()
        st.error(f"❌ 組 Portfolio 失敗：`{type(e).__name__}: {e}`")
        import traceback
        with st.expander("traceback"):
            st.code(traceback.format_exc())
        return

    progress.progress(1.0, text="✅ Portfolio 組成")

    # 存 session_state
    st.session_state['portfolio_result'] = {
        'preset_name': preset['name'],
        'preset_idx': preset_idx,
        'preset': preset,
        'port': result['port'],
        'strategy_stats': result['strategy_stats'],
        'port_stats': result['port_stats'],
        'total_balance': total_balance,
        'rebalance_safety_weight': rebalance_safety_weight,
    }
    st.success(f"✅ Portfolio 組成完成（{len(preset['strategies'])} 策略）")


def _render_portfolio_result(result: dict):
    """顯示 Portfolio 結果（含 equity curve、最新持倉、trades、壓力測試、存/推按鈕）"""
    port = result['port']
    port_stats = result['port_stats']
    strategy_stats = result['strategy_stats']
    preset = result['preset']

    st.divider()
    st.subheader(f"📊 Portfolio 結果：{preset['name']}")

    # ============ 1. 5+4 個 metric（跟預設 tab 同款） ============
    mc = st.columns(5)
    mc[0].metric("CAGR", f"{port_stats.get('cagr', 0)*100:+.1f}%")
    mc[1].metric("MDD", f"{port_stats.get('max_drawdown', 0)*100:.1f}%")
    mc[2].metric("Sortino (日)", f"{port_stats.get('daily_sortino', 0):.2f}")
    mc[3].metric("Sharpe (日)", f"{port_stats.get('daily_sharpe', 0):.2f}")
    mc[4].metric("Calmar", f"{port_stats.get('calmar', 0):.2f}")

    mc2 = st.columns(4)
    mc2[0].metric("Total Return", f"{port_stats.get('total_return', 0):+.1f}%")  # finlab Portfolio 已是 % 形式
    mc2[1].metric("Win ratio", f"{port_stats.get('win_ratio', 0)*100:.1f}%")
    mc2[2].metric("年勝率", f"{port_stats.get('win_year_perc', 0)*100:.1f}%")
    omega = ps.omega_score_vs_benchmark(port)
    mc2[3].metric("Omega vs 加權指數", f"{omega:.3f}")

    # ============ 2. Equity curve（從 preset tab 抄的邏輯，但修 scale） ============
    # ⚠️ finlab Portfolio.creturn 是「倍數」scale（從 1.0 開始，總報酬 196% → 199.7）
    #    而 benchmark 是「金額」scale（從 10000 點開始），
    #    直接 plot 在同一個 y 軸會把 Portfolio 線壓扁到接近 0。
    #    解法：兩個都按「起始 1000 萬 TWD」標準化到金額 scale 對照。
    st.divider()
    st.markdown("#### 📈 累計報酬曲線（起始 1000 萬 TWD）")
    try:
        creturn = port.creturn  # 倍數 scale，1.0 → 199.7
        if hasattr(creturn, 'index'):
            INITIAL_CAPITAL = 10_000_000  # 1000 萬 TWD 起始
            port_amt = (creturn / creturn.iloc[0]) * INITIAL_CAPITAL

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=port_amt.index, y=port_amt.values,
                name=f'Portfolio（{INITIAL_CAPITAL/1e6:.0f}M 起始）',
                line=dict(color='#26a69a', width=2),
                hovertemplate='日期：%{x|%Y-%m-%d}<br>市值：%{y:,.0f}<br>倍數：%{customdata:.2f}x<extra></extra>',
                customdata=port_amt.values / INITIAL_CAPITAL,
            ))
            # 加權指數也標準化到同樣起始金額
            try:
                from finlab import data as _data
                benchmark = _data.get('benchmark_return:發行量加權股價報酬指數').squeeze()
                bench_aligned = benchmark.reindex(port_amt.index).dropna()
                bench_amt = (bench_aligned / bench_aligned.iloc[0]) * INITIAL_CAPITAL
                fig.add_trace(go.Scatter(
                    x=bench_amt.index, y=bench_amt.values,
                    name=f'加權指數（同樣 {INITIAL_CAPITAL/1e6:.0f}M 起始）',
                    line=dict(color='#888', width=1, dash='dot'),
                    hovertemplate='日期：%{x|%Y-%m-%d}<br>市值：%{y:,.0f}<extra></extra>',
                ))
                # 標註期末值
                port_final = port_amt.iloc[-1]
                bench_final = bench_amt.iloc[-1]
                port_pct = (port_final / INITIAL_CAPITAL - 1) * 100
                bench_pct = (bench_final / INITIAL_CAPITAL - 1) * 100
                fig.add_annotation(
                    x=port_amt.index[-1], y=port_final,
                    text=f"Portfolio +{port_pct:.0f}%",
                    showarrow=True, arrowhead=2, ax=-50, ay=-20,
                    font=dict(color='#26a69a', size=12),
                )
                fig.add_annotation(
                    x=bench_amt.index[-1], y=bench_final,
                    text=f"加權 +{bench_pct:.0f}%",
                    showarrow=True, arrowhead=2, ax=-50, ay=20,
                    font=dict(color='#888', size=12),
                )
            except Exception:
                pass
            fig.update_layout(
                height=450,
                hovermode='x unified',
                yaxis_title='市值 (TWD)',
                yaxis_tickformat=',',
                xaxis_title='日期',
                legend=dict(yanchor='top', y=0.99, xanchor='left', x=0.01),
            )
            st.plotly_chart(fig, width="stretch")

            # 額外摘要
            port_final = (port_amt.iloc[-1] / INITIAL_CAPITAL - 1) * 100
            try:
                bench_final_pct = (bench_amt.iloc[-1] / INITIAL_CAPITAL - 1) * 100
                st.caption(
                    f"📊 期末：Portfolio **+{port_final:.1f}%** vs 加權指數 **+{bench_final_pct:.1f}%** "
                    f"（{port_final - bench_final_pct:+.1f}% 超額報酬）｜"
                    f"起始 1000 萬 → Portfolio 期末 {port_amt.iloc[-1]:,.0f} TWD"
                )
            except Exception:
                pass
        else:
            st.dataframe(creturn.head(50))
    except Exception as e:
        st.warning(f"無法繪製 equity curve：`{e}`")

    # ============ 2.5. 📅 年度績效（FY2020 整年 ~ FY2026 YTD） ============
    st.divider()
    st.markdown("#### 📅 年度績效（FY 整年 + FY2026 YTD）")
    _render_yearly_performance(port, port_stats)

    # ============ 3. 🎯 最新持倉（含中文名稱） ============
    st.divider()
    st.markdown("#### 🎯 最新持倉（含中文名稱）")
    _render_portfolio_holdings(port, result['total_balance'], result['rebalance_safety_weight'])

    # ============ 4. 4 個獨立策略對比表 ============
    st.divider()
    st.markdown("#### 📊 4 個獨立策略表現")
    rows = []
    for s in preset['strategies']:
        ist = strategy_stats[s['name']]
        rows.append({
            '策略': s['name'],
            'cell': s.get('cell', '?'),
            '條件數': len(s['conditions']),
            'weight': f"{s.get('weight', 0.25)*100:.0f}%",
            'CAGR': f"{ist['cagr']*100:+.1f}%",
            'MDD': f"{ist['max_drawdown']*100:.1f}%",
            'Sortino': f"{ist['daily_sortino']:.2f}",
            'Sharpe': f"{ist['daily_sharpe']:.2f}",
        })
    st.dataframe(rows, hide_index=True, width="stretch")

    # ============ 5. Trades table + CSV 下載 ============
    st.divider()
    st.markdown("#### 📋 Portfolio 最近 30 筆交易")
    try:
        trades = port.trades.tail(30).copy()
        st.dataframe(trades, hide_index=True, width="stretch")
        csv = trades.to_csv(index=False).encode("utf-8")
        from datetime import datetime
        st.download_button(
            "⬇️ 下載 Portfolio trades CSV",
            data=csv,
            file_name=f"portfolio_trades_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="port_trades_csv",
        )
    except Exception as e:
        st.warning(f"無法取得 trades：`{e}`")

    # ============ 6. Portfolio 蒙地卡羅壓力測試 ============
    st.divider()
    st.markdown("#### 🎲 Portfolio 蒙地卡羅壓力測試（bootstrap）")
    iters = st.slider(
        "蒙地卡羅迭代次數", 1000, 20000, 5000, step=1000,
        key="port_mc_iters",
    )
    if st.button("🎲 跑 Portfolio 壓力測試", key="port_stress_btn", type="primary"):
        progress = st.progress(0.0, text="Portfolio bootstrap 蒙地卡羅模擬中…")
        result_mc = ps.monte_carlo_stress_test(port, iterations=iters)
        progress.progress(1.0, text="完成")
        if result_mc is None:
            st.error("無法取得回測報酬數據")
        else:
            level_data = pd.DataFrame({
                '風險等級': ['95.0%', '97.5%', '99.0%', '99.7% (3σ)'],
                'Sortino': [result_mc['sortino_p95'], result_mc['sortino_p975'],
                            result_mc['sortino_p99'], result_mc['sortino_p997']],
                'Omega': [result_mc['omega_p95'], result_mc['omega_p975'],
                           result_mc['omega_p99'], result_mc['omega_p997']],
                'Sortino 累計衰減': [
                    '0% (基準)',
                    f"{(result_mc['sortino_p95']-result_mc['sortino_p975'])/result_mc['sortino_p95']*100:+.1f}%",
                    f"{(result_mc['sortino_p95']-result_mc['sortino_p99'])/result_mc['sortino_p95']*100:+.1f}%",
                    f"{(result_mc['sortino_p95']-result_mc['sortino_p997'])/result_mc['sortino_p95']*100:+.1f}%",
                ],
            })
            st.dataframe(level_data, hide_index=True, width="stretch")
            st.caption(
                f"基準 Sortino（中位數）: {result_mc['sortino_baseline']:.2f}　"
                f"基準 Omega（中位數）: {result_mc['omega_baseline']:.2f}　"
                f"迭代: {result_mc['n_iterations']:,} 次"
            )

    # ============ 7. 存資料版本 + 推到 finlab cloud ============
    st.divider()
    st.markdown("#### 💾 存成資料版本 / 推到 finlab cloud")
    save_col1, save_col2, save_col3 = st.columns([3, 1, 1])
    with save_col1:
        version_name = st.text_input(
            "Version name",
            value="",
            placeholder="留空自動產生 (e.g. v2_comb1_2026-09-15)",
            key="port_save_version",
        )
    with save_col2:
        st.write("")  # 對齊
        st.write("")
        if st.button("💾 存版本", key="port_save_btn", type="secondary"):
            from datetime import datetime
            ver = version_name.strip() or f"v{preset['name'].split()[1]}_{datetime.now().strftime('%Y%m%d_%H%M')}"
            data_version = {
                'version': ver,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'finlab_version': '2.0.16',
                'composition': preset['description'],
                'strategies': [{'name': s['name'], 'weight': s.get('weight', 0.25),
                                'cell': s.get('cell', '?'),
                                'conditions': s['conditions']} for s in preset['strategies']],
                'individual_stats': strategy_stats,
                'portfolio_stats': {k: port_stats.get(k) for k in [
                    'cagr', 'total_return', 'max_drawdown', 'daily_sortino',
                    'daily_sharpe', 'calmar', 'win_ratio', 'win_year_perc'
                ]},
                'omega_vs_market': omega,
                'sim_params': {
                    'period': '2019-2026-09-14', 'position_limit': '1/3',
                    'fee_ratio': 1.425/1000*0.3, 'nstocks_limit': 5,
                    'trade_at_price': 'open',
                },
            }
            try:
                json_path = ps.save_portfolio_data_version(ver, data_version)
                st.success(f"✅ 已存資料版本 **{ver}**")
                st.caption(f"📊 `~/.openclaw/ma_indicator_data/portfolio_versions.db`")
                st.caption(f"📄 `{json_path}`")
            except Exception as e:
                st.error(f"❌ 存失敗：`{e}`")
    with save_col3:
        st.write("")  # 對齊
        st.write("")
        if st.button("☁️ 推 cloud", key="port_push_btn", type="secondary",
                     help="推到 finlab cloud portfolio"):
            _push_to_cloud_ui(port, result['total_balance'], result['rebalance_safety_weight'])


def _render_yearly_performance(port, port_stats: dict):
    """顯示 FY 整年績效 + FY2026 YTD（含加權指數對照 + bar chart）"""
    try:
        return_table = port_stats.get('return_table', {})
        if not return_table:
            st.info("此 Portfolio 沒有 return_table（可能期間太短）")
            return

        # 用 port.creturn index 找出所有有資料的年度
        creturn = port.creturn
        if not hasattr(creturn, 'index'):
            return
        years_in_data = sorted({d.year for d in creturn.index})
        # 跳過進場年（資料不完整），從 2020 開始
        # 但如果從 2019 開始就留（用戶可自己看）
        current_year = max(years_in_data)  # 2026

        # 抓 Portfolio 年度報酬（從 return_table 的 YTD）
        rows = []
        for y in years_in_data:
            year_data = return_table.get(str(y), {}) or return_table.get(y, {})
            ytd = year_data.get('YTD')
            if ytd is None:
                # 自己從 creturn 算
                year_cret = creturn[creturn.index.year == y]
                if len(year_cret) > 1:
                    ytd = (year_cret.iloc[-1] / year_cret.iloc[0]) - 1
                else:
                    continue
            rows.append({'year': y, 'port_return': ytd})

        # 抓加權指數年度報酬
        try:
            from finlab import data as _data
            benchmark = _data.get('benchmark_return:發行量加權股價報酬指數').squeeze()
            bench_index = pd.to_datetime(benchmark.index)
            bench_aligned = benchmark.reindex(creturn.index).dropna()
            # 算每年度 1/1 第一筆 到 12/31 最後一筆的累積報酬
            for r in rows:
                y = r['year']
                year_mask = (bench_aligned.index >= f'{y}-01-01') & (bench_aligned.index <= f'{y}-12-31')
                year_bench = bench_aligned[year_mask]
                if len(year_bench) > 1:
                    r['bench_return'] = (year_bench.iloc[-1] / year_bench.iloc[0]) - 1
                else:
                    r['bench_return'] = None
        except Exception as e:
            for r in rows:
                r['bench_return'] = None

        # 組裝 DataFrame
        df_rows = []
        for r in rows:
            y = r['year']
            label = f"FY{y}" if y < current_year else f"FY{y} (YTD)"
            df_rows.append({
                '年度': label,
                'Portfolio': f"{r['port_return']*100:+.1f}%",
                '加權指數': f"{r['bench_return']*100:+.1f}%" if r.get('bench_return') is not None else "—",
                '超額報酬': f"{(r['port_return'] - (r['bench_return'] or 0))*100:+.1f}%" if r.get('bench_return') is not None else "—",
            })

        df = pd.DataFrame(df_rows)

        # Bar chart：Portfolio vs 加權指數（grouped bar）
        fig = go.Figure()
        x_labels = df['年度'].tolist()
        port_vals = [r['port_return']*100 for r in rows]
        bench_vals = [(r.get('bench_return') or 0)*100 for r in rows]

        fig.add_trace(go.Bar(
            name='Portfolio',
            x=x_labels, y=port_vals,
            marker_color='#26a69a',
            text=[f"+{v:.0f}%" if v >= 0 else f"{v:.0f}%" for v in port_vals],
            textposition='outside',
        ))
        if any(r.get('bench_return') is not None for r in rows):
            fig.add_trace(go.Bar(
                name='加權指數',
                x=x_labels, y=bench_vals,
                marker_color='#90a4ae',
                text=[f"+{v:.0f}%" if v >= 0 else f"{v:.0f}%" for v in bench_vals],
                textposition='outside',
            ))
        fig.update_layout(
            barmode='group',
            yaxis_title='年度報酬 (%)',
            height=380,
            yaxis_tickformat='.0f',
            xaxis_title='',
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        # 🔑 Plotly click event → streamlit rerun → 從 event 取點擊的年份
        event = st.plotly_chart(
            fig,
            on_select="rerun",
            key="yearly_bar_chart",
            selection_mode="points",
        )

        # 表格
        st.dataframe(df, hide_index=True, width="stretch")

        # 摘要
        port_avg = sum(port_vals) / len(port_vals) if port_vals else 0
        bench_avg = sum(b for b in bench_vals if b is not None) / len([b for b in bench_vals if b is not None]) if bench_vals else 0
        full_years = [r for r in rows if r['year'] < current_year]
        if full_years:
            n_full = len(full_years)
            port_full_avg = sum(r['port_return']*100 for r in full_years) / n_full
            bench_full_avg = sum((r.get('bench_return') or 0)*100 for r in full_years) / n_full
            st.caption(
                f"📊 **{n_full} 個完整年度平均**：Portfolio **+{port_full_avg:.1f}%** vs "
                f"加權指數 **+{bench_full_avg:.1f}%**（年化超額 +{port_full_avg - bench_full_avg:.1f}%）｜"
                f"FY{current_year} (YTD)：Portfolio **+{port_vals[-1]:.1f}%** vs "
                f"加權指數 **+{bench_vals[-1]:.1f}%**"
            )

        # ============ 月度績效 drill-down（點擊年份或下拉選單） ============
        st.markdown("##### 📆 月度績效（點上方 bar 或選年份）")

        # 從 click event 拿年份（streamlit 1.58 的 PlotlyPoint 是 dict，不是 object）
        clicked_label = None
        try:
            if event and hasattr(event, 'selection') and event.selection and event.selection.points:
                pt = event.selection.points[0]
                if isinstance(pt, dict):
                    clicked_label = pt.get('x')
                else:
                    clicked_label = getattr(pt, 'x', None)
        except (AttributeError, IndexError, KeyError, TypeError):
            clicked_label = None

        # Dropdown 當備援（給 click 失效或用戶想直接選的情境）
        default_idx = 0
        if clicked_label and clicked_label in x_labels:
            default_idx = x_labels.index(clicked_label)
        selected_label = st.selectbox(
            "查看年度",
            options=x_labels,
            index=default_idx,
            key="monthly_year_select",
            help="💡 也可以點上方 bar chart 切換",
        )

        # 解析年份（"FY2026 (YTD)" → 2026）
        import re as _re
        m = _re.match(r"FY(\d{4})", selected_label)
        if m:
            selected_year = int(m.group(1))
            _render_monthly_breakdown(port_stats, selected_year, selected_label)
    except Exception as e:
        st.warning(f"無法顯示年度績效：`{e}`")
        import traceback
        with st.expander("traceback"):
            st.code(traceback.format_exc())


def _render_monthly_breakdown(port_stats: dict, year: int, label: str):
    """渲染選定年份的月度績效（12 個月 bar chart + 月勝率 + 最佳/最差月）"""
    try:
        return_table = port_stats.get('return_table', {})
        # finlab return_table key 是 str(year) 或 int(year)，兩種都試
        year_data = return_table.get(str(year), {}) or return_table.get(year, {})

        if not year_data:
            st.info(f"{label} 沒有月度資料")
            return

        # 月份順序
        MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        # 過濾掉 YTD 這個非月份的 key
        monthly = {m: year_data.get(m) for m in MONTHS if m in year_data}

        if not monthly:
            st.info(f"{label} 沒有月度資料")
            return

        months = list(monthly.keys())
        returns = [monthly[m] * 100 for m in months]  # 轉 %

        # ============ Metrics ============
        positive = [r for r in returns if r > 0]
        negative = [r for r in returns if r < 0]
        n_total = len(returns)
        n_win = len(positive)
        n_loss = len(negative)
        win_rate = (n_win / n_total * 100) if n_total else 0
        avg_month = sum(returns) / n_total if n_total else 0

        if returns:
            best_idx = returns.index(max(returns))
            worst_idx = returns.index(min(returns))
            best_label = f"{months[best_idx]} +{returns[best_idx]:.1f}%"
            worst_label = f"{months[worst_idx]} {returns[worst_idx]:+.1f}%"
        else:
            best_label = "—"
            worst_label = "—"

        # YTD 對照
        ytd = year_data.get('YTD')
        ytd_str = f"+{ytd*100:.1f}%" if ytd is not None else "—"

        # 標題列
        st.markdown(f"**📆 {label} 月度績效**")
        mc = st.columns(5)
        mc[0].metric("月勝率", f"{win_rate:.0f}%", delta=f"{n_win}/{n_total} 月")
        mc[1].metric("平均月報酬", f"{avg_month:+.1f}%")
        mc[2].metric("最佳月", best_label)
        mc[3].metric("最差月", worst_label)
        mc[4].metric("年度累計", ytd_str)

        # ============ 12 月 bar chart（正綠 / 負紅） ============
        fig = go.Figure()
        colors = ['#26a69a' if r >= 0 else '#ef5350' for r in returns]
        fig.add_trace(go.Bar(
            x=months,
            y=returns,
            marker_color=colors,
            text=[f"+{r:.1f}%" if r >= 0 else f"{r:.1f}%" for r in returns],
            textposition='outside',
            hovertemplate='%{x}<br>報酬：%{y:+.2f}%<extra></extra>',
        ))
        fig.update_layout(
            height=380,
            yaxis_title='月度報酬 (%)',
            yaxis_tickformat='.0f',
            xaxis_title='',
            showlegend=False,
            margin=dict(t=30, b=30),
        )
        # 0 線
        fig.add_hline(y=0, line_dash='dot', line_color='gray', line_width=1)
        st.plotly_chart(fig, width="stretch")

        # 表格（也可選用）
        table_df = pd.DataFrame({
            '月份': months,
            '月度報酬': [f"{r:+.1f}%" for r in returns],
            '正/負': ['🟢 +' if r > 0 else ('🔴 ' if r < 0 else '➖') for r in returns],
        })
        st.dataframe(table_df, hide_index=True, width="stretch")

        # 摘要
        st.caption(
            f"💡 **{label} 月度摘要**：{n_win} 個月正報酬 / {n_loss} 個月負報酬｜"
            f"最高月 {best_label}｜最低月 {worst_label}｜"
            f"平均月 {avg_month:+.1f}% (若月勝率 > 50% 表示策略在該年度穩定賺錢)"
        )
    except Exception as e:
        st.warning(f"無法顯示 {label} 月度績效：`{e}`")
        import traceback
        with st.expander("traceback"):
            st.code(traceback.format_exc())


def _render_portfolio_holdings(port, total_balance: float, rebalance_safety_weight: float):
    """從 PortfolioSyncManager 取最新持倉 + 中文名稱"""
    from finlab.portfolio import PortfolioSyncManager

    with st.spinner("從 finlab PortfolioSyncManager 取最新持倉…"):
        try:
            pm = PortfolioSyncManager()
            pm.update(port, total_balance=total_balance, rebalance_safety_weight=rebalance_safety_weight)
        except Exception as e:
            st.warning(f"無法更新 pm：`{e}`")
            pm = None

    if pm is None:
        return

    # 從 str(pm) parse 持倉表（finlab PortfolioSyncManager 沒有公開 holdings API）
    holdings = []
    for line in str(pm).split('\n'):
        line = line.strip()
        parts = line.split()
        if not parts or not parts[0].isdigit() or len(parts[0]) != 4:
            continue
        try:
            stock_id = parts[0]
            quantity = float(parts[1])
            price = float(parts[2])
            weight = float(parts[3])
            close_price = float(parts[4])
            volume = float(parts[5])
            strategy = ' '.join(parts[6:-1]) if len(parts) > 7 else (parts[6] if len(parts) > 6 else '?')
            type_ = parts[-1] if parts else '?'
            holdings.append({
                'stock_id': stock_id,
                'name': '',
                'quantity': int(quantity),
                'price': price,
                'value': quantity * price,
                'weight_pct': weight * 100,
                'strategy': strategy,
                'type': type_,
            })
        except (ValueError, IndexError):
            pass

    if not holdings:
        st.info("目前無持倉（pm 還沒推送或 sync 失敗）")
        return

    # 加中文名稱
    name_map = _cached_security_names()
    for h in holdings:
        h['name'] = name_map.get(h['stock_id'], '?')

    # 聚合（同檔被多策略持有）
    seen = {}
    for h in holdings:
        sid = h['stock_id']
        if sid not in seen:
            seen[sid] = {
                'stock_id': sid,
                '名稱': h['name'],
                '數量': h['quantity'],
                '現價': h['price'],
                '市值(TWD)': h['value'],
                '權重(%)': h['weight_pct'],
                '來源策略': h['strategy'],
            }
        else:
            seen[sid]['來源策略'] += f", {h['strategy']}"

    df = pd.DataFrame(list(seen.values())).sort_values('權重(%)', ascending=False)
    st.dataframe(df, hide_index=True, width="stretch")

    total_value = sum(h['value'] for h in holdings)
    total_weight = sum(h['weight_pct'] for h in holdings)
    n_unique = len(seen)
    st.caption(
        f"📊 共 **{n_unique}** 檔個股｜總市值 TWD {total_value:,.0f}（依報價 × 數量估算）｜"
        f"總權重 {total_weight:.1f}%（4 策略可重疊持倉）"
    )


@st.cache_data(ttl=3600, show_spinner="撈台股中文簡稱…")
def _cached_security_names() -> dict:
    """stock_id -> 中文名稱（從 security_categories 撈）"""
    try:
        from data_fetcher import get_all_securities
        secs = get_all_securities()
        return dict(zip(secs['stock_id'].astype(str), secs['name']))
    except Exception:
        return {}


def _push_to_cloud_ui(port, total_balance: float, rebalance_safety_weight: float):
    """推到 finlab cloud"""
    progress = st.progress(0.0, text="PortfolioSyncManager.update() ...")
    try:
        from finlab.portfolio import PortfolioSyncManager
        pm = PortfolioSyncManager()
        progress.progress(0.4, text=f"pm.update(port, total_balance={total_balance:,}, rebalance_safety_weight={rebalance_safety_weight})")
        pm.update(port, total_balance=total_balance, rebalance_safety_weight=rebalance_safety_weight)
        progress.progress(0.7, text="pm.to_cloud() ...")
        pm.to_cloud()
        progress.progress(1.0, text="✅ 已推到 finlab cloud")
        st.success(f"✅ 已推 Portfolio 到 finlab cloud（總資金 ${total_balance:,:,}）")
        with st.expander("📋 PortfolioSyncManager 內容", expanded=False):
            st.text(str(pm))
    except Exception as e:
        progress.empty()
        st.error(f"❌ 推 cloud 失敗：`{type(e).__name__}: {e}`")
        import traceback
        with st.expander("traceback"):
            st.code(traceback.format_exc())
