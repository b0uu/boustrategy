# Public dashboard release and recovery

The public dashboard reads a separately published SQLite database. Building the UI, starting the
public server, and running its checks don't enable reasoning schedules, invoke a model, or contact a
broker. Publication is the only step here that reads the private source and writes the public store.

## Build and release checks

Run the complete gates from the repository root:

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy app tests
npm --prefix public-ui run test
npm --prefix public-ui run type-check
npm --prefix public-ui run lint
npm --prefix public-ui run build
git diff --check
```

The browser bundle has no production fixture fallback. `public-ui/fixtures/public-v2.json` and its
router are test-only files and aren't imported by `public-ui/src`.

The release matrix is split across tests that each own a real failure boundary:

| State or risk | Coverage |
| --- | --- |
| Empty, one and many decisions; live and paper scope; search, filters, cursors and revision restart | `tests/public/test_public_v2.py`, `public-ui/src/main.test.tsx` |
| All-cash, unfunded, sold-out, zero-position, partial and stale values; corrected flows and fills | `tests/performance/test_reporting.py`, `tests/public/test_public_v2.py`, `public-ui/src/main.test.tsx` |
| Active, stale, failed, no-action, retry, manual, paused and disabled runtime states | `tests/public/test_activity.py`, `tests/reason/test_runtime.py`, `tests/reason/test_scheduler.py`, `public-ui/src/main.test.tsx` |
| Missing historical detail, old public stores, exact legacy links and retraction | `tests/public/test_explanations.py`, `tests/public/test_public_v2.py`, `public-ui/src/main.test.tsx` |
| Private-field filtering, safe source URLs, escaped public text and sanitized JSON or CSV | `tests/public/test_public_dashboard.py`, `tests/public/test_explanations.py`, `public-ui/src/main.test.tsx` |
| Built-SPA route isolation, read-only GET and HEAD, transaction rollback and concurrent publication | `tests/public/test_release.py` |

## Publish

Build the UI before starting the public process:

```powershell
npm --prefix public-ui run build
python -m app.public.publication --source data/boustrategy.db --public-db data/boustrategy.public.db
```

Live publication also needs each deliberately included `--live-profile` and the matching
`--live-account-id`. These are private producer inputs. Don't put them in frontend configuration or
release logs.

Keep source and public paths distinct. Back up the public database before replacing it because its
opaque ID mapping preserves stable decision and activity URLs. Publishing with `--rebuild` into the
same public database keeps that mapping and manual revocations. Publishing into a new empty database
creates new IDs.

Publication commits projections and its checkpoint in one transaction. If it exits before commit,
leave the target in place and rerun the same command. The next run repeats the dirty work without
exposing a partial snapshot. A missing or invalid source fails before it can withdraw the current
public records. The public server rejects a WAL-mode public database, so a trusted publisher must
finish and checkpoint it before handoff.

Continuous publication uses `--watch SECONDS`, but that command isn't a service installer. Run it
under an explicit supervisor and monitor its exit status, `publication_meta.updated_at`, file health,
and publication lag. A heartbeat-only update doesn't rebuild decision or accounting history.

## Serve and smoke a prepared public store

Start the server against an already published database:

```powershell
python -m app.public.server --public-db data/boustrategy.public.db --port 8380
```

In another PowerShell session, record hashes and inspect the public surfaces:

```powershell
$sourceBefore = (Get-FileHash -Algorithm SHA256 .\data\boustrategy.db).Hash
$publicBefore = (Get-FileHash -Algorithm SHA256 .\data\boustrategy.public.db).Hash

$live = Invoke-RestMethod http://127.0.0.1:8380/api/public/v2/portfolios/live/overview
$paper = Invoke-RestMethod http://127.0.0.1:8380/api/public/v2/portfolios/paper/overview
$feed = Invoke-RestMethod 'http://127.0.0.1:8380/api/public/v2/decisions?portfolio_id=live&limit=25'
$runtime = Invoke-RestMethod http://127.0.0.1:8380/api/public/v2/portfolios/live/runtime

foreach ($path in @('/operate', '/api/private')) {
    try {
        (Invoke-WebRequest ("http://127.0.0.1:8380" + $path)).StatusCode
    } catch {
        [int]$_.Exception.Response.StatusCode
    }
}

$sourceAfter = (Get-FileHash -Algorithm SHA256 .\data\boustrategy.db).Hash
$publicAfter = (Get-FileHash -Algorithm SHA256 .\data\boustrategy.public.db).Hash
$sourceBefore -eq $sourceAfter
$publicBefore -eq $publicAfter
```

Both private-route checks must return 404 and both hash comparisons must return `True`. Inspect the
response values rather than treating HTTP 200 as data completeness. Live must never fall back to
paper. Null equity, cash, returns, model labels, runtime, or trace sections remain unavailable. Check
that every feed link resolves, its portfolio scope matches, and no execution profile, account
fingerprint, source key, local path, raw prompt, broker ID, or worker log appears.

For the browser pass, use the built app at 320, 375, 768, and 1200px, then repeat at 200% zoom and with
reduced motion. Check keyboard focus, disclosures, safe source links, direct decision routes, Back
scroll restoration, search and pagination, paper separation, and withdrawn-record cleanup. Wide data
tables may scroll within their own region; the document itself must not overflow horizontally.

## Synthetic HTTP benchmark

Run the benchmark as a module so Python resolves imports from the checkout under review:

```powershell
python -m tests.public.benchmark_http --records 100000 --requests 100 --clients 20
```

The benchmark creates disposable files, seeds realistic large decision details plus explicit compact
feed rows, starts a real Uvicorn server on a random localhost port, and sends 100 requests per route
with 20 concurrent clients. It separately records direct-feed SQL count and query-plan evidence. It
fails if GET changes the database checksum or creates WAL or SHM sidecars.

Measured September 7, 2026 on Windows Server 2019, Python 3.14.2, six logical CPUs:

| Measurement | Result |
| --- | ---: |
| Seed 100,000 rich records | 15.674 s |
| Feed HTTP p50 / p95 | 299.502 ms / 426.470 ms |
| Overview HTTP p50 / p95 | 46.404 ms / 55.094 ms |
| Maximum feed / overview response | 21,748 bytes / 534 bytes |
| Direct feed SQL statements / returned rows | 7 / 25 |
| Direct serialized feed size | 22,517 bytes |

The feed query used the covering `public_feed` index for portfolio, revocation, withdrawal, creation
time, and public ID ordering. Both measured routes were below the initial 500 ms p95 target. These are
synthetic host measurements, not a production latency promise.

## Retraction and recovery checks

A revoked or withdrawn detail and export must return 410. Its row must leave feed/search results and
position links, and the browser must clear any loaded trace, snippets, links, and export controls.
API responses use `Cache-Control: no-store`, so there is no ETag or intermediary-cache invalidation
path to reconcile.

If the public file is corrupt, stop the server and restore the most recent known-good public backup.
Republish from the source into that restored file to retain its opaque IDs. Use a new empty file only
when changing public URLs is acceptable. Don't copy a live WAL file by itself. Verify the restored
database with the release tests, the HTTP benchmark, and the read-only smoke before serving it again.


## Audit completion, September 8, 2026

The audited main tree passed 506 Python tests in `scratchpad/audit-venv`, 26 React tests,
Ruff lint and full formatting checks, strict mypy over 160 files, TypeScript, ESLint,
production build and `git diff --check`. The isolated environment used corrected runtime
security floors and pip 26.2.1. `pip check` passed, PyPI metadata listed no advisories
for its 50 installed package versions, and npm audit reported zero known vulnerabilities.
Upstream test-client deprecation warnings remain. Markdown examples are explicitly
excluded from Ruff formatting; Python source checks still cover the full tree.

A fresh module benchmark in that environment measured:

| Measurement | Audit result |
| --- | ---: |
| Records / clients / requests per route | 100,000 / 20 / 100 |
| Seed | 17.698 s |
| Feed HTTP p50 / p95 | 293.602 / 370.728 ms |
| Overview HTTP p50 / p95 | 57.069 / 71.770 ms |
| Direct feed / overview SQL statements | 7 / 4 |
| Maximum feed / overview response | 21,748 / 534 bytes |
| Feed rows | 25 |

The feed used the covering `public_feed` index. GET preserved the database checksum
and created no WAL/SHM sidecars. Host: Windows Server 2019, Python 3.14.2, six logical CPUs.
These audit results supplement the earlier release/browser measurements above.

Publication checkpoint version 7 refreshes projections after the audit's accounting
changes. New paper fills use `next_open_v2`; historical fills remain `legacy_close_v1`.
Reconstructed paper benchmarks are withheld for corporate-action convention mismatch.
The public positions view recognizes a formerly funded account's `zero_balance` state.

No real source publication, deployment or activation occurred. See
[the audit record](plan-031-audit.md) and [operating assessment](execution-assessment.md).
The recommendation is a private dashboard over the persisted runtime, with authenticated
controls and fresh snapshot/broker reconciliation capabilities completed before unattended live use.
