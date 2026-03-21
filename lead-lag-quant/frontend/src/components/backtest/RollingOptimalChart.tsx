import { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { XcorrHeatmapPoint } from "../../types";

interface Props {
  data: XcorrHeatmapPoint[];
}

interface OptimalPoint {
  date: string;
  correlation: number;
  lag: number;
}

export default function RollingOptimalChart({ data }: Props) {
  const chartData = useMemo<OptimalPoint[]>(() => {
    if (data.length === 0) return [];

    const dateMap = new Map<string, XcorrHeatmapPoint[]>();
    for (const pt of data) {
      const existing = dateMap.get(pt.trading_day) ?? [];
      existing.push(pt);
      dateMap.set(pt.trading_day, existing);
    }

    const allDates = [...dateMap.keys()].sort();
    const last90 = allDates.slice(-90);

    return last90.map((date) => {
      const points = dateMap.get(date)!;
      // Prefer significant points; fall back to all
      const significant = points.filter((p) => p.is_significant === 1 && p.correlation != null);
      const candidates = significant.length > 0 ? significant : points.filter((p) => p.correlation != null);

      if (candidates.length === 0) {
        return { date, correlation: 0, lag: 0 };
      }

      const best = candidates.reduce((a, b) =>
        Math.abs(a.correlation ?? 0) >= Math.abs(b.correlation ?? 0) ? a : b
      );

      return {
        date,
        correlation: best.correlation ?? 0,
        lag: best.lag,
      };
    });
  }, [data]);

  if (chartData.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
        <p className="text-sm text-[var(--text-secondary)]">No rolling correlation data</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <h3 className="text-sm font-medium mb-3">Rolling Optimal Correlation</h3>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.07)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "var(--text-secondary)" }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[-1, 1]}
            tick={{ fontSize: 10, fill: "var(--text-secondary)" }}
            tickLine={false}
            tickCount={5}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--bg-secondary)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            formatter={(value, _name, props) => {
              const num = typeof value === "number" ? value : 0;
              const lag = (props.payload as OptimalPoint | undefined)?.lag ?? 0;
              return [`${num.toFixed(3)} (Lag ${lag > 0 ? "+" : ""}${lag})`, "Optimal Correlation"];
            }}
            labelFormatter={(label) => `Date: ${label}`}
          />
          <Line
            type="monotone"
            dataKey="correlation"
            stroke="var(--accent)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
