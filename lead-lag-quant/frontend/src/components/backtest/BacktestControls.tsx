import type { Pair } from "../../types";

interface BacktestControlsProps {
  pairs: Pair[];
  leader: string;
  setLeader: (v: string) => void;
  follower: string;
  setFollower: (v: string) => void;
  startDate: string;
  setStartDate: (v: string) => void;
  endDate: string;
  setEndDate: (v: string) => void;
  onRun: () => void;
  loading: boolean;
}

export default function BacktestControls({
  pairs,
  leader,
  setLeader,
  follower,
  setFollower,
  startDate,
  setStartDate,
  endDate,
  setEndDate,
  onRun,
  loading,
}: BacktestControlsProps) {
  const leaders = [...new Set(pairs.map((p) => p.leader))].sort();
  const followers = [...new Set(pairs.map((p) => p.follower))].sort();

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
      <div className="flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-[var(--text-secondary)]">Leader</label>
          <select
            value={leader}
            onChange={(e) => setLeader(e.target.value)}
            className="px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
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
            className="px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          >
            <option value="">Select follower</option>
            {followers.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-[var(--text-secondary)]">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-[var(--text-secondary)]">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          />
        </div>

        <button
          onClick={onRun}
          disabled={loading || !leader || !follower || !startDate || !endDate}
          className="px-5 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium transition-opacity disabled:opacity-40 hover:opacity-90"
        >
          {loading ? "Running..." : "Run Backtest"}
        </button>
      </div>
    </div>
  );
}
