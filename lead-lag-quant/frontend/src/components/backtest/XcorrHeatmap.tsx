import { useMemo } from "react";
import type { XcorrHeatmapPoint } from "../../types";

interface Props {
  data: XcorrHeatmapPoint[];
}

function corrColor(value: number | null): string {
  if (value == null) return "transparent";
  const intensity = Math.min(Math.abs(value), 1);
  if (value >= 0) {
    return `rgba(34, 197, 94, ${0.1 + intensity * 0.7})`;
  }
  return `rgba(239, 68, 68, ${0.1 + intensity * 0.7})`;
}

function formatDate(dateStr: string): string {
  // Convert YYYY-MM-DD to MM/DD
  const parts = dateStr.split("-");
  if (parts.length === 3) return `${parts[1]}/${parts[2]}`;
  return dateStr;
}

const LAGS = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5];

export default function XcorrHeatmap({ data }: Props) {
  const { dates, cellMap } = useMemo(() => {
    if (data.length === 0) return { dates: [], cellMap: new Map<string, XcorrHeatmapPoint>() };

    const allDates = [...new Set(data.map((d) => d.trading_day))].sort();
    // Show last 30 dates
    const last30 = allDates.slice(-30);

    const map = new Map<string, XcorrHeatmapPoint>();
    for (const pt of data) {
      map.set(`${pt.lag}|${pt.trading_day}`, pt);
    }

    return { dates: last30, cellMap: map };
  }, [data]);

  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-8 text-center">
        <p className="text-sm text-[var(--text-secondary)]">
          No cross-correlation data — run the pipeline first
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <h3 className="text-sm font-medium mb-3">Cross-Correlation Heatmap (Last 30 Days)</h3>
      <div className="overflow-x-auto">
        <table className="border-collapse text-xs">
          <thead>
            <tr>
              <th className="p-1.5 text-left text-[var(--text-secondary)] font-medium whitespace-nowrap min-w-[64px]">
                Lag
              </th>
              {dates.map((d) => (
                <th
                  key={d}
                  className="p-1 text-center text-[var(--text-secondary)] font-medium"
                  style={{ minWidth: "42px" }}
                >
                  {formatDate(d)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {LAGS.map((lag) => (
              <tr key={lag}>
                <td className="p-1.5 text-[var(--text-secondary)] font-medium whitespace-nowrap">
                  {lag > 0 ? `Lag +${lag}` : `Lag ${lag}`}
                </td>
                {dates.map((date) => {
                  const pt = cellMap.get(`${lag}|${date}`);
                  const val = pt?.correlation ?? null;
                  const sig = pt?.is_significant === 1;
                  return (
                    <td
                      key={date}
                      className="p-1 text-center font-mono rounded"
                      style={{
                        backgroundColor: corrColor(val),
                        outline: sig ? "1px solid rgba(255,255,255,0.3)" : undefined,
                      }}
                      title={
                        val != null
                          ? `Lag ${lag > 0 ? "+" : ""}${lag}, ${date}: ${val.toFixed(3)}${sig ? " *" : ""}`
                          : `Lag ${lag}, ${date}: no data`
                      }
                    >
                      {val != null ? val.toFixed(2) : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
