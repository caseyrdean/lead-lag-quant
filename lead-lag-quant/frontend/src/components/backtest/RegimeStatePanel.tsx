import type { RegimeStateEntry } from "../../types";

interface Props {
  data: RegimeStateEntry | null;
  loading: boolean;
}

function regimeBadgeStyle(regime: string): string {
  switch (regime.toLowerCase()) {
    case "bull":
      return "bg-green-500/20 text-green-400 border-green-500/40";
    case "bear":
      return "bg-red-500/20 text-red-400 border-red-500/40";
    case "base":
      return "bg-amber-500/20 text-amber-400 border-amber-500/40";
    case "failure":
    case "unknown":
    default:
      return "bg-gray-500/20 text-gray-400 border-gray-500/40";
  }
}

function fmt(value: number | null, mode: "pct" | "ratio"): string {
  if (value == null) return "—";
  if (mode === "pct") return `${(value * 100).toFixed(1)}%`;
  return value.toFixed(2);
}

function fmtStreak(value: number | null): string {
  if (value == null) return "—";
  return `${value} session${value !== 1 ? "s" : ""}`;
}

export default function RegimeStatePanel({ data, loading }: Props) {
  if (loading) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
        <p className="text-sm text-[var(--text-secondary)]">Loading...</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
        <p className="text-sm text-[var(--text-secondary)]">
          No regime data — run the pipeline first
        </p>
      </div>
    );
  }

  const rows: { label: string; value: string }[] = [
    { label: "RS Value", value: fmt(data.rs_value, "pct") },
    { label: "Price vs 21MA", value: fmt(data.price_vs_21ma, "pct") },
    { label: "Price vs 50MA", value: fmt(data.price_vs_50ma, "pct") },
    { label: "ATR Ratio", value: fmt(data.atr_ratio, "ratio") },
    { label: "Volume Ratio", value: fmt(data.volume_ratio, "ratio") },
    { label: "VWAP Rejection Streak", value: fmtStreak(data.vwap_rejection_streak) },
    { label: "Distribution Flagged", value: data.is_flagged === 1 ? "Yes" : "No" },
  ];

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4 space-y-4">
      {/* Regime badge */}
      <div className="flex items-center gap-3">
        <span
          className={`px-4 py-1.5 rounded-full border text-sm font-semibold uppercase tracking-wide ${regimeBadgeStyle(data.regime)}`}
        >
          {data.regime === "Unknown" ? "No Signal" : data.regime}
        </span>
        {data.trading_day && (
          <span className="text-xs text-[var(--text-secondary)]">
            As of {data.trading_day}
          </span>
        )}
      </div>

      {/* Indicator table */}
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr>
            <th className="text-left text-xs text-[var(--text-secondary)] font-medium pb-2">
              Indicator
            </th>
            <th className="text-right text-xs text-[var(--text-secondary)] font-medium pb-2">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, value }) => (
            <tr key={label} className="border-t border-[var(--border)]">
              <td className="py-2 text-[var(--text-secondary)]">{label}</td>
              <td className="py-2 text-right font-mono tabular-nums">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
