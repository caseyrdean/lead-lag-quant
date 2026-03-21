---
phase: "06-backtest-visualization"
plan: "02"
subsystem: "frontend"
tags: [react, typescript, recharts, tailwind, backtest, visualization]
dependency_graph:
  requires:
    - "Plan 06-01: /api/backtest/run, /api/backtest/xcorr, /api/backtest/regime endpoints"
    - "frontend/src/types/index.ts (Pair type)"
    - "frontend/src/lib/api.ts (request helper)"
  provides:
    - "BacktestPage (UI-05): pair+date range form + stat cards"
    - "LeadLagChartsPage (UI-02): cross-correlation heatmap + rolling optimal chart"
    - "RegimeStatePage (UI-03): regime badge + indicator table"
    - "BacktestResult, XcorrHeatmapPoint, RegimeStateEntry TypeScript interfaces"
    - "api.backtest.run/xcorr/regime client methods"
  affects:
    - "Task 3 (human verify): visual confirmation of all three pages"
tech_stack:
  added: []
  patterns:
    - "HTML table heatmap (XcorrHeatmap) — same technique as MonthlyHeatmap, avoids SVG cell overflow"
    - "rgba color intensity scaling: abs(correlation) maps to 0.1–0.8 alpha on green/red"
    - "Recharts LineChart for RollingOptimalChart — optimal lag per date derived from xcorr data"
    - "Regime badge via className switch on regime string (Bull/Bear/Base/Failure/Unknown)"
key_files:
  created:
    - "frontend/src/components/backtest/BacktestControls.tsx"
    - "frontend/src/components/backtest/BacktestResultCards.tsx"
    - "frontend/src/components/backtest/XcorrHeatmap.tsx"
    - "frontend/src/components/backtest/RollingOptimalChart.tsx"
    - "frontend/src/components/backtest/RegimeStatePanel.tsx"
    - "frontend/src/pages/BacktestPage.tsx"
    - "frontend/src/pages/LeadLagChartsPage.tsx"
    - "frontend/src/pages/RegimeStatePage.tsx"
  modified:
    - "frontend/src/types/index.ts"
    - "frontend/src/lib/api.ts"
    - "frontend/src/App.tsx"
    - "frontend/src/components/layout/Sidebar.tsx"
decisions:
  - "XcorrHeatmap uses HTML table not Recharts — 11 lags x 30 days = 330 cells; SVG rendering would be slow and no hover affordance needed"
  - "RollingOptimalChart derives optimal lag per day by preferring significant points (is_significant=1) before falling back to all lags"
  - "Recharts Tooltip formatter fixed to accept ValueType (not typed number) — pre-existing pattern in other components used incorrect types"
  - "Pre-existing TypeScript errors in 7 unrelated chart files logged to deferred-items.md; not fixed (out-of-scope, not caused by this plan)"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-03-21"
  tasks_completed: 2
  tasks_total: 3
  files_created: 8
  files_modified: 4
---

# Phase 6 Plan 02: React Visualization Pages Summary

**One-liner:** Three React pages (BacktestPage, LeadLagChartsPage, RegimeStatePage) consuming the Plan 06-01 FastAPI endpoints, with five supporting components, three new routes, and three sidebar links — all using Recharts or HTML table technique, no Plotly.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Types, API client, five backtest components | 261a9e1 | types/index.ts, lib/api.ts, components/backtest/* (5 files) |
| 2 | Three pages, routes, sidebar links | 2aa70d8 | pages/BacktestPage.tsx, LeadLagChartsPage.tsx, RegimeStatePage.tsx, App.tsx, Sidebar.tsx |

## What Was Built

**Types (frontend/src/types/index.ts)** — three new interfaces appended:
- `BacktestResult` — leader/follower, dates, total_trades, winning_trades, hit_rate (decimal), mean_return_per_trade, annualized_sharpe, max_drawdown (negative decimal)
- `XcorrHeatmapPoint` — lag (-5 to +5), trading_day, correlation (nullable), is_significant (0/1)
- `RegimeStateEntry` — regime string, trading_day, rs_value, price_vs_21/50ma, atr_ratio, volume_ratio, vwap_rejection_streak, is_flagged

**API client (frontend/src/lib/api.ts)** — `api.backtest` group added:
- `run(leader, follower, startDate, endDate)` → `BacktestResult`
- `xcorr(leader, follower, days=60)` → `XcorrHeatmapPoint[]`
- `regime(leader, follower)` → `RegimeStateEntry`

**Components (frontend/src/components/backtest/):**
- `BacktestControls.tsx` — leader/follower selects + date inputs + Run Backtest button (disabled when loading or fields empty)
- `BacktestResultCards.tsx` — four stat cards (Hit Rate with trade count subtitle, Mean Return/Trade, Annualized Sharpe, Max Drawdown); null shows placeholder
- `XcorrHeatmap.tsx` — HTML table, 11 lag rows × last 30 unique dates, rgba color cells (green=positive, red=negative), significant cells get outline, empty shows placeholder
- `RollingOptimalChart.tsx` — Recharts LineChart, derives optimal correlation per day (prefer significant, fall back to all), limit 90 days
- `RegimeStatePanel.tsx` — regime badge with color (Bull=green, Bear=red, Base=amber, Failure/Unknown=gray), indicator table with formatted values

**Pages:**
- `BacktestPage.tsx` (UI-05) — mounts pair list on load, wires BacktestControls + BacktestResultCards
- `LeadLagChartsPage.tsx` (UI-02) — inline pair selects, fetches xcorr on pair change, shows XcorrHeatmap + RollingOptimalChart
- `RegimeStatePage.tsx` (UI-03) — inline pair selects, fetches regime on pair change, shows RegimeStatePanel

**Routing and navigation:**
- `App.tsx` — three new `<Route>` elements: `/backtest`, `/lead-lag`, `/regime`
- `Sidebar.tsx` — three new links: Backtest (FlaskConical), Lead-Lag Charts (TrendingUp), Regime State (Gauge)

## Awaiting

Task 3 is a `checkpoint:human-verify` — human verification of the three pages in the running app.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed RollingOptimalChart Recharts Tooltip formatter type**
- **Found during:** Task 1 verification (npm run build)
- **Issue:** `formatter={(value: number, ...) => ...}` — Recharts `Formatter<ValueType, NameType>` expects `ValueType | undefined`, not `number`
- **Fix:** Changed to `formatter={(value, _name, props) => { const num = typeof value === "number" ? value : 0; ... }}`
- **Files modified:** `frontend/src/components/backtest/RollingOptimalChart.tsx`
- **Commit:** included in 261a9e1

### Out-of-Scope Pre-existing Errors

7 files have pre-existing TypeScript errors (Recharts Tooltip formatter pattern) that were present before this plan. Logged to `.planning/phases/06-backtest-visualization/deferred-items.md`. Not fixed.

- `frontend/src/components/analytics/EquityChart.tsx`
- `frontend/src/components/analytics/PnlDistributionChart.tsx`
- `frontend/src/components/analytics/TickerPnlChart.tsx`
- `frontend/src/components/charts/CorrelationChart.tsx`
- `frontend/src/components/charts/PriceChart.tsx`
- `frontend/src/lib/ws.ts`
- `frontend/src/pages/TradingPage.tsx`

`npm run build` exits non-zero due to these pre-existing errors, but `tsc --project tsconfig.app.json --noEmit` produces zero errors in any file this plan created or modified.

## Self-Check: PASSED

Files verified:
- `frontend/src/components/backtest/BacktestControls.tsx` — exists
- `frontend/src/components/backtest/BacktestResultCards.tsx` — exists
- `frontend/src/components/backtest/XcorrHeatmap.tsx` — exists
- `frontend/src/components/backtest/RollingOptimalChart.tsx` — exists
- `frontend/src/components/backtest/RegimeStatePanel.tsx` — exists
- `frontend/src/pages/BacktestPage.tsx` — exists
- `frontend/src/pages/LeadLagChartsPage.tsx` — exists
- `frontend/src/pages/RegimeStatePage.tsx` — exists

Commits verified:
- `261a9e1` — Task 1: types, api client, five components
- `2aa70d8` — Task 2: three pages, routes, sidebar
