export interface Pair {
  id: number;
  leader: string;
  follower: string;
  created_at: string;
}

export interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  current_price: number | null;
  unrealized_pnl: number | null;
  exit_flag: boolean;
  opened_at: string;
}

export interface Portfolio {
  cash_balance: number;
  starting_capital: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  win_rate: number;
}

export interface Signal {
  signal_id: number;
  leader: string;
  follower: string;
  signal_date: string;
  direction: string;
  sizing_tier: string;
  stability_score: number;
  correlation_strength: number;
  expected_target: number | null;
  invalidation_threshold: number | null;
  data_warning: string | null;
  generated_at: string;
  executed: number;
}

export interface Trade {
  trade_id: number;
  ticker: string;
  side: string;
  shares: number;
  price: number;
  realized_pnl: number | null;
  executed_at: string;
  notes: string;
}

export interface TradeStats {
  total_closed: number;
  winning: number;
  losing: number;
  win_rate: number;
  profit_factor: number;
  payoff_ratio: number;
  best_trade: number;
  worst_trade: number;
  avg_trade: number;
  total_realized_pnl: number;
  expectancy: number;
}

export interface RiskMetrics {
  sharpe_ratio: number;
  max_drawdown_dollar: number;
  max_drawdown_pct: number;
  calmar_ratio: number;
  recovery_factor: number;
}

export interface OhlcBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma20: number | null;
  ma50: number | null;
  rsi: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_hist: number | null;
}

export interface EquityPoint {
  date: string;
  value: number;
  drawdown_pct: number;
}

export interface PnlDistEntry {
  realized_pnl: number;
}

export interface MonthlyHeatmapEntry {
  year: string;
  month: number;
  pnl: number;
}

export interface CorrelationPoint {
  date: string;
  [ticker: string]: string | number | null;
}

export interface TickerBreakdown {
  Ticker: string;
  Trades: number;
  "Win Rate (%)": number;
  "Total P&L ($)": number;
  "Avg P&L ($)": number;
  "Best ($)": number;
  "Worst ($)": number;
}

export interface PipelineStatus {
  step: string;
  message: string;
}

export interface WsMessage {
  type: "prices" | "pipeline_status" | "new_signal";
  data: Record<string, unknown>;
}

export interface BacktestResult {
  leader: string;
  follower: string;
  start_date: string;
  end_date: string;
  total_trades: number;
  winning_trades: number;
  hit_rate: number;
  mean_return_per_trade: number;
  annualized_sharpe: number;
  max_drawdown: number;
}

export interface XcorrHeatmapPoint {
  lag: number;
  trading_day: string;
  correlation: number | null;
  is_significant: number;
}

export interface RegimeStateEntry {
  regime: string;
  trading_day: string | null;
  rs_value: number | null;
  price_vs_21ma: number | null;
  price_vs_50ma: number | null;
  atr_ratio: number | null;
  volume_ratio: number | null;
  vwap_rejection_streak: number | null;
  is_flagged: number;
}
