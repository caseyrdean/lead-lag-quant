import type { BacktestResult, XcorrHeatmapPoint, RegimeStateEntry } from "../types";

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  pairs: {
    list: () => request<Record<string, unknown>[]>("/pairs"),
    add: (leader: string, followers: string[]) =>
      request("/pairs", {
        method: "POST",
        body: JSON.stringify({ leader, followers }),
      }),
    remove: (ids: number[]) =>
      request("/pairs", {
        method: "DELETE",
        body: JSON.stringify({ ids }),
      }),
    correlation: (leader: string, followers: string[], days = 180) =>
      request<Record<string, unknown>[]>(
        `/pairs/correlation?leader=${leader}&followers=${followers.join(",")}&days=${days}`
      ),
  },

  trading: {
    portfolio: () => request<Record<string, unknown>>("/trading/portfolio"),
    positions: () => request<Record<string, unknown>[]>("/trading/positions"),
    history: () => request<Record<string, unknown>[]>("/trading/history"),
    priceChart: (ticker: string, days = 365) =>
      request<Record<string, unknown>[]>(`/trading/price-chart/${ticker}?days=${days}`),
    buy: (ticker: string, shares: number, price?: number) =>
      request("/trading/buy", {
        method: "POST",
        body: JSON.stringify({ ticker, shares, price }),
      }),
    sell: (ticker: string, shares: number, price?: number) =>
      request("/trading/sell", {
        method: "POST",
        body: JSON.stringify({ ticker, shares, price }),
      }),
    setCapital: (amount: number) =>
      request("/trading/capital", {
        method: "POST",
        body: JSON.stringify({ starting_capital: amount }),
      }),
  },

  signals: {
    list: (days = 7) => request<Record<string, unknown>[]>(`/signals?days=${days}`),
    execute: () => request("/signals/execute", { method: "POST" }),
  },

  analytics: {
    stats: () => request<Record<string, unknown>>("/analytics/stats"),
    risk: () => request<Record<string, unknown>>("/analytics/risk"),
    equity: (days = 365) =>
      request<Record<string, unknown>[]>(`/analytics/equity?lookback_days=${days}`),
    tickerBreakdown: () =>
      request<Record<string, unknown>[]>("/analytics/ticker-breakdown"),
    pnlDistribution: () =>
      request<Record<string, unknown>[]>("/analytics/pnl-distribution"),
    monthlyHeatmap: () =>
      request<Record<string, unknown>[]>("/analytics/monthly-heatmap"),
  },

  backtest: {
    run: (leader: string, follower: string, startDate: string, endDate: string) =>
      request<BacktestResult>(
        `/backtest/run?leader=${leader}&follower=${follower}&start_date=${startDate}&end_date=${endDate}`
      ),
    xcorr: (leader: string, follower: string, days = 60) =>
      request<XcorrHeatmapPoint[]>(
        `/backtest/xcorr?leader=${leader}&follower=${follower}&days=${days}`
      ),
    regime: (leader: string, follower: string) =>
      request<RegimeStateEntry>(`/backtest/regime?leader=${leader}&follower=${follower}`),
  },

  health: () => request<{ status: string }>("/health"),
};
