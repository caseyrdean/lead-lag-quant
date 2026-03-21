# Deferred Items — Phase 06-backtest-visualization

## Pre-existing TypeScript Errors (Out of Scope)

These errors existed before Plan 06-02 started and are in files not touched by this plan.
Confirmed by: `git diff HEAD --stat` shows zero changes in these files.

### Files with errors:
- `frontend/src/components/analytics/EquityChart.tsx` — Recharts Tooltip formatter type mismatch
- `frontend/src/components/analytics/PnlDistributionChart.tsx` — Recharts Tooltip formatter type mismatch
- `frontend/src/components/analytics/TickerPnlChart.tsx` — Recharts Tooltip formatter type mismatch
- `frontend/src/components/charts/CorrelationChart.tsx` — Recharts Tooltip formatter type mismatch
- `frontend/src/components/charts/PriceChart.tsx` — unused import, wrong argument count, Recharts formatter type
- `frontend/src/lib/ws.ts` — Expected 1 argument but got 0, PipelineStatus cast error
- `frontend/src/pages/TradingPage.tsx` — Recharts Tooltip formatter type mismatch

### Root cause:
Recharts updated its `Formatter` type to accept `ValueType | undefined` instead of concrete `number`.
All existing chart components use `(v: number) => ...` formatters that don't match the updated type.

### Recommendation:
Fix all Recharts Tooltip formatters to accept `value: number | undefined` or use type assertion.
This would be a straightforward single-pattern fix across 7 files.
