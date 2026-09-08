# BouStrategy public UI

This package is the read-only public dashboard. It uses the version 2 public API for the live-first
portfolio, paper simulation, decision feed, performance, positions, policy records, runtime activity,
and decision traces. The version 1 API remains available only for old links and clients.

The application expects a separately published public database. From the repository root, publish a
snapshot and start the server with:

```text
python -m app.public.publication --source data/boustrategy.db --public-db data/boustrategy.public.db
python -m app.public.server --db data/boustrategy.db --public-db data/boustrategy.public.db
```

Live publication also needs the operator's `--live-profile` and `--live-account-id` values. They are
deployment settings and aren't stored in this package.

Publication is an operator action. Starting the public server doesn't publish source records, enable a
schedule, or run the agent. See `docs/reasoning/RUNTIME.md` for the runtime worker and scheduler model.

For frontend development, run `npm ci` and `npm run dev`. The Vite development server forwards public
API requests to the local server. A production build from `npm run build` is served by the public
FastAPI application when `public-ui/dist` exists.

Realistic version 2 fixtures are stored in `fixtures/public-v2.json`. Regenerate them only from
disposable databases with:

```text
python public-ui/fixtures/generate.py
```

Fixtures are used by tests and browser review. They aren't a production fallback and aren't loaded by
the application.

Run `npm test`, `npm run type-check`, `npm run lint`, and `npm run build` before release. The redesign
follows the September 2026 handoff while keeping Agent dashboard as the sole top-level navigation
label. [HANDOFF-GAPS.md](HANDOFF-GAPS.md) records the remaining design and operating gaps.
The repository's public release, benchmark, smoke, and recovery procedure is in
[`docs/public-release.md`](../docs/public-release.md).
