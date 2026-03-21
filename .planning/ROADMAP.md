# Roadmap: Lead-Lag Quant

## Milestones

- ✅ **v1.0 MVP** — Phases 1–6.1 (shipped 2026-03-21) — see [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)
- 📋 **v1.1** — Planned (run `/gsd:new-milestone` to define)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1–6.1) — SHIPPED 2026-03-21</summary>

- [x] Phase 1: Data Ingestion Pipeline (3/3 plans) — completed 2026-02-18
- [x] Phase 2: Normalization & Returns (2/2 plans) — completed 2026-02-18
- [x] Phase 3: Feature Engineering (2/2 plans) — completed 2026-02-18
- [x] Phase 4: Lead-Lag Engine, Regime & Signals (2/2 plans) — completed 2026-02-18
- [x] Phase 5: Paper Trading Simulation (2/2 plans) — completed 2026-02-19
- [x] Phase 5.1: API Security & Data Integrity Fixes (4/4 plans, INSERTED) — completed 2026-03-21
- [x] Phase 6: Backtest & Visualization (2/2 plans) — completed 2026-03-21
- [x] Phase 6.1: Signal Gate Threshold Fix (1/1 plan, INSERTED) — completed 2026-03-21

Full details: [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

### 🚧 v1.1 (In Progress / Planned)

- [ ] **Phase 7: Outperformance Signal Enhancement** — RS-relative expected target benchmark, RS acceleration condition, per-signal outperformance vs leader baseline

## Phase Details

### Phase 7: Outperformance Signal Enhancement
**Goal**: Signals indicate not just that a follower moves with the leader, but whether it is likely to outpace it — expected_target is compared against the leader's baseline return over the same lag window, and an RS acceleration condition gates signals where the follower is already showing momentum relative to the leader
**Depends on**: Phase 6 (consumes signals, features_lagged_returns, features_relative_strength)
**Milestone**: v1.1
**Requirements**: TBD — defined during planning
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Ingestion Pipeline | v1.0 | 3/3 | Complete | 2026-02-18 |
| 2. Normalization & Returns | v1.0 | 2/2 | Complete | 2026-02-18 |
| 3. Feature Engineering | v1.0 | 2/2 | Complete | 2026-02-18 |
| 4. Lead-Lag Engine, Regime & Signals | v1.0 | 2/2 | Complete | 2026-02-18 |
| 5. Paper Trading Simulation | v1.0 | 2/2 | Complete | 2026-02-19 |
| 5.1. API Security & Data Integrity Fixes | v1.0 | 4/4 | Complete | 2026-03-21 |
| 6. Backtest & Visualization | v1.0 | 2/2 | Complete | 2026-03-21 |
| 6.1. Signal Gate Threshold Fix | v1.0 | 1/1 | Complete | 2026-03-21 |
| 7. Outperformance Signal Enhancement | v1.1 | 0/? | Not started | - |
