import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  ArrowRightLeft,
  Activity,
  Link2,
  BarChart3,
  FlaskConical,
  TrendingUp,
  Gauge,
} from "lucide-react";

const links = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/trading", label: "Trading", icon: ArrowRightLeft },
  { to: "/signals", label: "Signals", icon: Activity },
  { to: "/pairs", label: "Pairs", icon: Link2 },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/backtest", label: "Backtest", icon: FlaskConical },
  { to: "/lead-lag", label: "Lead-Lag Charts", icon: TrendingUp },
  { to: "/regime", label: "Regime State", icon: Gauge },
];

export default function Sidebar() {
  return (
    <aside className="w-56 shrink-0 h-screen sticky top-0 flex flex-col border-r border-[var(--border)] bg-[var(--bg-secondary)]">
      <div className="px-5 py-5 text-lg font-bold tracking-tight">
        Lead-Lag Quant
      </div>

      <nav className="flex flex-col gap-0.5 px-3 flex-1">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-[var(--accent)]/15 text-[var(--accent)] font-medium"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-white/5"
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 text-xs text-[var(--text-secondary)]">
        v0.1.0
      </div>
    </aside>
  );
}
