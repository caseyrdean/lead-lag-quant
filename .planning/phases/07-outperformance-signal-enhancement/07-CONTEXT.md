# Phase 7: Outperformance Signal Enhancement - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Enhance the signal generator so signals indicate not just that a follower correlates with a leader, but whether it is outpacing it. Adds BUY/HOLD/SELL action classification, response window, RS acceleration, and outperformance margin to signal records. Updates the backtest engine to validate outperformance by action. No UI changes in this phase.

</domain>

<decisions>
## Implementation Decisions

### BUY/HOLD/SELL Classification
- Action field added to signal records alongside existing long/short direction (not a replacement)
- All actions are FLAGS ONLY — BUY, HOLD, SELL surface in the dashboard; human executes all trades
- Two BUY conditions, both produce the same `action: BUY` (no sub-tagging):
  1. Follower consistently outperforming leader (RS positive streak)
  2. Follower was underperforming leader and reverses upward for 3+ consecutive sessions
- HOLD: follower RS is within the pair's historical RS volatility band (dynamic, not fixed ±2%)
- SELL: requires N sessions of sustained RS decline below the leader's trajectory (not a single-reading drop)
- SELL from stability/correlation: only flag SELL if the stability score AND correlation strength are on a deteriorating trend, not a one-off dip below threshold
- Each action transition (BUY→HOLD, HOLD→SELL, etc.) is logged with timestamp for full lifecycle audit trail

### RS Acceleration
- Measured as slope of RS series over recent sessions, scaled by pair-specific RS standard deviation (dynamic threshold, not fixed)
- Track BOTH follower RS acceleration AND leader RS deceleration — both present = highest conviction
- RS acceleration is informational metadata on the signal, NOT a hard gate (signal still fires without it)
- BUY only triggers on confirmed positive RS crossover — accelerating-but-still-negative RS does not qualify

### New Signal Fields
- `action`: BUY / HOLD / SELL
- `response_window`: average number of sessions follower stays in BUY state after lag event (hold duration estimate)
- `rs_acceleration`: slope of follower RS relative to pair-specific RS volatility (float)
- `leader_rs_deceleration`: slope of leader RS (float) — captures divergence story
- `outperformance_margin`: expected_target minus leader baseline return over the same lag window
- Action field updates on each pipeline re-run (signals are upserted, not immutable for action)

### Response Window
- Defined as: average duration follower stays in BUY state after a lag event fires
- Computed from historical RS state transitions for the pair
- Gives trader a time-bound expectation: "this signal typically plays out over N sessions"

### Pipeline Scheduler
- Change poll interval from 30 minutes to **15 minutes**
- Applies to `pipeline_scheduler.py` background thread

### Backtest Updates
- Break down existing backtest metrics (hit rate, Sharpe, drawdown) by action: BUY / HOLD / SELL
- Add outperformance comparison: follower realized return vs leader realized return over the response_window
- Validates that BUY signals actually outperformed the leader historically
- No React UI changes in this phase — backtest UI is a separate future phase

### Claude's Discretion
- Exact N sessions for SELL confirmation (symmetrical with BUY's 3-session reversal is a reasonable default)
- SQLite schema design for signal_transitions table
- Exact slope computation method (linear regression vs point-difference) — use whichever is more robust given pair data density

</decisions>

<specifics>
## Specific Ideas

- The pipeline currently runs every 30 minutes — this phase changes it to 15 minutes
- The RS volatility band for HOLD state should be derived from the pair's historical RS std dev, not a global constant
- "Trending toward downturn" for SELL from stability/correlation means a rolling average of the score is declining, not a single below-threshold reading
- Leader deceleration + follower acceleration together = highest conviction BUY scenario

</specifics>

<deferred>
## Deferred Ideas

- React UI updates to show BUY/HOLD/SELL on the Signal Dashboard and Backtest Results page — separate phase after data model is stable
- Leader deceleration as a hard gate (discussed, kept as metadata only for now)
- Per-pair configurable reversal session threshold (discussed, defaulting to 3 for now)

</deferred>

---

*Phase: 07-outperformance-signal-enhancement*
*Context gathered: 2026-03-21*
