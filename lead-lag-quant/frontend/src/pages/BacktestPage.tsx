import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Pair, BacktestResult } from "../types";
import BacktestControls from "../components/backtest/BacktestControls";
import BacktestResultCards from "../components/backtest/BacktestResultCards";

export default function BacktestPage() {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [leader, setLeader] = useState("");
  const [follower, setFollower] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [result, setResult] = useState<BacktestResult | null>(null);
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

  function handleRun() {
    if (!leader || !follower || !startDate || !endDate) return;
    setLoading(true);
    api.backtest
      .run(leader, follower, startDate, endDate)
      .then(setResult)
      .catch((err: unknown) => {
        console.error("Backtest run failed:", err);
      })
      .finally(() => setLoading(false));
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Backtest Results</h1>
      <BacktestControls
        pairs={pairs}
        leader={leader}
        setLeader={setLeader}
        follower={follower}
        setFollower={setFollower}
        startDate={startDate}
        setStartDate={setStartDate}
        endDate={endDate}
        setEndDate={setEndDate}
        onRun={handleRun}
        loading={loading}
      />
      <BacktestResultCards result={result} />
    </div>
  );
}
