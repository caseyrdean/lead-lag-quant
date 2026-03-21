import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Pair, XcorrHeatmapPoint } from "../types";
import XcorrHeatmap from "../components/backtest/XcorrHeatmap";
import RollingOptimalChart from "../components/backtest/RollingOptimalChart";

export default function LeadLagChartsPage() {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [leader, setLeader] = useState("");
  const [follower, setFollower] = useState("");
  const [xcorrData, setXcorrData] = useState<XcorrHeatmapPoint[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.pairs.list().then((d) => {
      const typed = d as unknown as Pair[];
      setPairs(typed);
      if (typed.length > 0) {
        setLeader(typed[0].leader);
        setFollower(typed[0].follower);
      }
    });
  }, []);

  useEffect(() => {
    if (!leader || !follower) return;
    setLoading(true);
    api.backtest
      .xcorr(leader, follower, 90)
      .then((d) => setXcorrData(d))
      .catch((err: unknown) => {
        console.error("xcorr fetch failed:", err);
        setXcorrData([]);
      })
      .finally(() => setLoading(false));
  }, [leader, follower]);

  const leaders = [...new Set(pairs.map((p) => p.leader))].sort();
  const followers = [...new Set(pairs.map((p) => p.follower))].sort();

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Lead-Lag Charts</h1>

      {/* Pair selector */}
      <div className="flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-[var(--text-secondary)]">Leader</label>
          <select
            value={leader}
            onChange={(e) => setLeader(e.target.value)}
            className="px-3 py-2 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">Select leader</option>
            {leaders.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-[var(--text-secondary)]">Follower</label>
          <select
            value={follower}
            onChange={(e) => setFollower(e.target.value)}
            className="px-3 py-2 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">Select follower</option>
            {followers.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        {loading && (
          <span className="text-xs text-[var(--text-secondary)] self-end pb-2">Loading...</span>
        )}
      </div>

      <XcorrHeatmap data={xcorrData} />
      <RollingOptimalChart data={xcorrData} />
    </div>
  );
}
