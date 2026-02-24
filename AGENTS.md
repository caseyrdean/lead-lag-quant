# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Lead-Lag Quant is a single-process Python/Gradio quantitative pairs trading platform. It lives entirely under `lead-lag-quant/`. See the `README.md` there for full architecture and workflow documentation.

### Running the app

```bash
cd lead-lag-quant
uv run python main.py        # serves Gradio UI on http://localhost:7860
```

Requires `POLYGON_API_KEY` set in environment or in `lead-lag-quant/.env`. The app auto-creates its SQLite database; no external database services are needed.

The `DB_PATH` config defaults to `[REDACTED]` in source; set `DB_PATH=data/lead_lag_quant.db` in `.env` to use a sensible path.

### Running tests

```bash
cd lead-lag-quant
uv run pytest                 # all tests use in-memory SQLite and mocked API calls; no API key needed
```

14 tests in `test_engine_detector.py` and `test_signals_generator.py` are pre-existing failures (test expectations don't match current implementation thresholds). 133 tests pass.

### Linting

No linter (ruff, flake8, mypy, etc.) is configured in this project.

### Key caveats

- `uv` must be installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and on `PATH` (`~/.local/bin`).
- The `.env` file is gitignored. Each agent session must create it if missing (copy from `.env.example` and set `POLYGON_API_KEY`).
- The app spawns two daemon threads internally (pipeline scheduler + price poller); there are no separate services to start.
