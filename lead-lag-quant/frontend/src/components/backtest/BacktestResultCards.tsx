import type { BacktestResult } from "../../types";

interface Props {
  result: BacktestResult | null;
}

interface CardProps {
  label: string;
  value: string;
  subtitle?: string;
}

function Card({ label, value, subtitle }: CardProps) {
  return (
    <div className="p-4 rounded-xl bg-[var(--bg-secondary)] border border-[var(--border)]">
      <p className="text-xs text-[var(--text-secondary)] mb-1">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
      {subtitle && (
        <p className="text-xs text-[var(--text-secondary)] mt-1">{subtitle}</p>
      )}
    </div>
  );
}

export default function BacktestResultCards({ result }: Props) {
  if (!result) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
        <p className="text-sm text-[var(--text-secondary)]">
          Run a backtest to see results
        </p>
      </div>
    );
  }

  const hitRate = (result.hit_rate * 100).toFixed(1);
  const meanReturn = (result.mean_return_per_trade * 100).toFixed(2);
  const sharpe = result.annualized_sharpe.toFixed(2);
  const drawdown = (result.max_drawdown * 100).toFixed(1);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Card
        label="Hit Rate"
        value={`${hitRate}%`}
        subtitle={`${result.total_trades} trades`}
      />
      <Card label="Mean Return / Trade" value={`${meanReturn}%`} />
      <Card label="Annualized Sharpe" value={sharpe} />
      <Card label="Max Drawdown" value={`${drawdown}%`} />
    </div>
  );
}
