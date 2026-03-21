import { BrowserRouter, Routes, Route } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import Header from "./components/layout/Header";
import DashboardPage from "./pages/DashboardPage";
import TradingPage from "./pages/TradingPage";
import SignalsPage from "./pages/SignalsPage";
import PairsPage from "./pages/PairsPage";
import AnalyticsPage from "./pages/AnalyticsPage";
import BacktestPage from "./pages/BacktestPage";
import LeadLagChartsPage from "./pages/LeadLagChartsPage";
import RegimeStatePage from "./pages/RegimeStatePage";
import { useLiveData } from "./lib/ws";

export default function App() {
  const { prices, pipelineStatus, signals, connected } = useLiveData();

  return (
    <BrowserRouter>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0">
          <Header pipelineStatus={pipelineStatus} connected={connected} />
          <main className="flex-1 overflow-auto p-6">
            <Routes>
              <Route path="/" element={<DashboardPage prices={prices} />} />
              <Route path="/trading" element={<TradingPage />} />
              <Route path="/signals" element={<SignalsPage liveSignals={signals} />} />
              <Route path="/pairs" element={<PairsPage pipelineStatus={pipelineStatus} />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/backtest" element={<BacktestPage />} />
              <Route path="/lead-lag" element={<LeadLagChartsPage />} />
              <Route path="/regime" element={<RegimeStatePage />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  );
}
