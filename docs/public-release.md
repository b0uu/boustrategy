# Public dashboard release and recovery

The public dashboard reads a separately published SQLite database. Building the UI, starting the
public server, and running its checks don't enable reasoning schedules, invoke a model, or contact a
broker. Publication is the only step here that reads the private source and writes the public store.

## Build and release checks

Run the complete gates from the repository root:

```powershell
python public-ui/fixtures/generate.py
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

Regenerate the fixtures whenever a public payload changes. Two checks make a stale one fail the
build rather than reach production: `tests/public/test_contract.py` compares the committed fixture's
shape against a freshly published API and refuses an uncovered route, and
`public-ui/src/contract.check.ts` assigns `contract-sample.json` to the UI's declared types so a
field the API stopped sending becomes a `tsc` error. Regeneration rewrites opaque IDs and
timestamps, so expect churn in `public-v2.json` even when no shape changed.

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

## Public operation (plan 039)

The public dashboard is served at `https://boustrategy.com` from this host:

```text
Robinhood MCP (read only, bot Codex identity)
  -> boustrategy-live-valuation: one snapshot per 15 min in the regular session
  -> data/boustrategy.db (private)
  -> boustrategy-public-publisher: publication --watch 5
  -> data/boustrategy.public.db
  -> boustrategy-public-server: read-only FastAPI on 127.0.0.1:8380
  -> cloudflared Windows service (named tunnel) -> https://boustrategy.com
```

Nothing listens on a public interface and no inbound firewall rule exists. The private operator
dashboard on 8378 is never routed.

### Tasks and wrappers

`ops/install-public-tasks.ps1` registers four tasks, Disabled unless `-Enable` is passed. It never
touches the twelve digester, review and execution tasks.

| Task | Wrapper | Trigger | Principal |
| --- | --- | --- | --- |
| `boustrategy-public-server` | `ops/run-public-server.ps1` | logon; restarts itself | interactive, limited |
| `boustrategy-public-publisher` | `ops/run-publication-watch.ps1` | logon; restarts itself | interactive, limited |
| `boustrategy-public-health` | `ops/check-public-health.ps1 -Quiet` | every 5 min and at logon | interactive, limited |
| `boustrategy-live-valuation` | `ops/run-live-valuation.ps1` | weekdays 09:37 + every 15 min for 6.5 h | interactive, highest |

The server and publisher wrappers supervise their child, restart it with backoff after an
unexpected exit, alert on each exit and give up with a nonzero code after five exits in 15
minutes. The health task starts an enabled supervisor task that isn't running. A Disabled task is
deliberate and is left alone. Both supervisors also stop an orphaned child of their own kind
before starting, because ending a task doesn't always end its child processes.

Valuation ticks fall at :07, :22, :37 and :52, away from the :00/:15/:30/:45 starts of review
preparation and execution, which run their own broker sessions on the same Codex identity. A tick
is also skipped while one of those tasks is running. `python -m app.broker.valuation` is the
authority on whether a tick observes: weekends, NYSE holidays, pre-open and after the close
(13:00 on half-days) are no-ops. It holds a nonblocking lock so ticks never overlap. It runs only
`app.broker.collector snapshot` with a 480-second backstop that kills the whole Codex process tree.
A failed tick writes nothing, so the last good observation stays public.

Non-secret settings live in the gitignored `ops/public.local.psd1` (see
`ops/public.local.example.psd1`). The Discord webhook stays in `ops/digester.local.psd1`, and the
broker identity stays in `ops/live.local.json`.

### Start, stop and status

```powershell
# Status
Get-ScheduledTask -TaskName 'boustrategy-public-*','boustrategy-live-valuation' |
    Select-Object TaskName, State
Get-Service cloudflared
(Invoke-RestMethod http://127.0.0.1:8380/api/public/v2/health)
powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\check-public-health.ps1

# Start in dependency order
'boustrategy-public-server','boustrategy-public-publisher','boustrategy-public-health' |
    ForEach-Object { Enable-ScheduledTask -TaskName $_ | Out-Null; Start-ScheduledTask -TaskName $_ }
Enable-ScheduledTask -TaskName boustrategy-live-valuation

# Stop one component (disable first so the health task doesn't restart it)
Disable-ScheduledTask -TaskName boustrategy-public-server | Out-Null
Stop-ScheduledTask -TaskName boustrategy-public-server
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object CommandLine -match 'app\.public\.server' |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Use `app\.public\.publication` in the last filter to stop an orphaned publisher. Restart is stop
then start. Preview what a valuation tick would do without starting a model or writing a row:
`powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\run-live-valuation.ps1 -WhatIf`.

### Cadence, cost and timing

A full regular session has 26 valuation ticks. Each is one `gpt-5.6-luna` Codex session with the
Robinhood MCP and has taken 27 to 44 seconds. A half-day has 14. Weekends and holidays start
nothing. Review the cadence after two weeks using duration, failure count, cost and rate pressure.
Move to five minutes only with evidence, and back off to thirty minutes on any auth or rate
pressure.

Three clocks decide what a reader sees:

- **Broker observation**: at most every 15 minutes in session. The recorded `captured_at` is the
  truth, and outside the session the last close observation stands.
- **Publication**: within about 5 seconds of a source change (the watcher's interval).
- **Browser**: the feed refreshes about every 30 seconds and other resources about every 60
  seconds.

A new observation should therefore reach an open browser within about 75 seconds. Only real
observations are stored. The chart may draw between recorded points, but the stored series never
contains estimates.

This cadence is visualization freshness, not execution authority. Reviews and executions still
take their own fresh snapshots.

### Origin hardening

Every response carries `Content-Security-Policy` (self-only scripts, styles, fonts and
connections; no framing), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Permissions-Policy` denying unused device APIs, and
same-origin COOP/CORP. API responses are `no-store`, hashed assets are `immutable` and the HTML
shell is `no-cache`. There is no HSTS at the origin because Cloudflare owns TLS.

API requests are limited per client with a token bucket: 120-request burst, refilling 2 per
second. The state is bounded at 4,096 clients and forgets a client once its bucket refills. An
exhausted client gets 429 with `Retry-After`. The server is started with `--behind-tunnel`, so for
loopback peers it keys on Cloudflare's `CF-Connecting-IP` (IPv6 by /64). It never reads that
header from a non-loopback peer and ignores duplicated or malformed values. Uvicorn's proxy-header
rewriting and access log are off.

`/api/public/v2/health` returns only `status`, `api_version`, `revision`, `published_at` and
`age_seconds`. It answers 503 `unavailable` for a missing, unreadable, WAL-mode or unstamped
store, and 503 `stale` when the store hasn't been stamped for 26 hours. The watcher stamps at least
once per New York day. Finer lag is measured by `python -m app.public.monitor`, which the health
task runs with read access to both stores. It calls publication `stuck` when a source change is
still unpublished after 30 seconds.

### Logs, state and alerts

| What | Where |
| --- | --- |
| Valuation ticks | `data/logs/runtime/valuation-*.log`, broker transcripts in `data/logs/broker/` |
| Publisher / server | `data/logs/runtime/publication-watch-*.log`, `public-server-*.log` (one per supervisor start) |
| Health | `data/logs/runtime/public-health-<date>.log` |
| Streak and transition state | `data/state/live-valuation.json`, `data/state/public-health.json` |

Discord alerts go out:

- **Valuation**: on the first failure, every third consecutive failure and on recovery.
- **Supervisors**: on every unexpected child exit.
- **Health**: only when the set of failing checks changes.

Alert text is a fixed vocabulary: outcome codes and check names, never collector output,
paths, identifiers or response bodies.

### Cloudflare Tunnel

The tunnel is a named, locally managed tunnel, never a Quick Tunnel. The binary is at
`C:\Cloudflared\bin\cloudflared.exe`. The service reads
`C:\Windows\System32\config\systemprofile\.cloudflared\config.yml`:

```yaml
tunnel: <tunnel-uuid>
credentials-file: C:\Windows\System32\config\systemprofile\.cloudflared\<tunnel-uuid>.json
ingress:
  - hostname: boustrategy.com
    service: http://127.0.0.1:8380
  - service: http_status:404
```

The catch-all rule rejects every other hostname. The credential JSON and `cert.pem` are secrets.
They live only in the two `.cloudflared` directories and are never committed, pasted or logged.
The DNS record is a proxied apex CNAME created by `cloudflared tunnel route dns`.

`www.boustrategy.com` is a Cloudflare redirect rule to the apex. The tunnel doesn't route it.

Zone settings to keep:

- SSL/TLS: Always Use HTTPS on, minimum TLS 1.2.
- Speed and optimization: Rocket Loader, Email Address Obfuscation and automatic Web Analytics
  (RUM) off. They inject scripts, which the CSP blocks, and the launch decision is no analytics.
- Caching: the default cache level, with no rule that caches HTML or `/api/*`.

### Recovery

| Situation | Effect and action |
| --- | --- |
| Reboot | All four tasks start at logon. Until the bot account signs in, the site is down and trading stops too. Sign in, then confirm health. |
| Sleep | Sleep isn't allowed on this host. If it happens, tasks catch up (`StartWhenAvailable`). Valuation ticks that were missed aren't back-filled. |
| Network loss | cloudflared reconnects on its own. Health stays ok locally, and Cloudflare shows 1033/530 at the edge until it reconnects. |
| Broker MCP authorization expired | Valuation fails with a session code and alerts. Disable `boustrategy-live-valuation`, re-authorize the Robinhood MCP interactively under the bot's `CODEX_HOME`, run one `-WhatIf` tick and then one in-session tick, and re-enable. |
| Rate or terms pressure | Disable valuation. Serving continues with the last observation. |
| Public server down | Health alerts and restarts the task. Check `public-server-*.log`. |
| Publication stuck | Health reports `publication`. Restart the publisher task and check `publication-watch-*.log`. |
| Corrupt public store | Follow the rollback below. |
| Cloudflare 1016 or TLS errors | Check `Get-Service cloudflared`, `cloudflared tunnel info boustrategy-public` and the DNS CNAME. Repair once, then stop and escalate. |

### Disable public exposure without stopping trading

```powershell
sc.exe stop cloudflared
sc.exe config cloudflared start= demand
```

The site then fails closed at the edge. The server, publisher and all trading tasks keep running.
Restore with `sc.exe config cloudflared start= auto` and `sc.exe start cloudflared`. To stop the
whole public stack, also disable and stop the four public tasks as shown above. Trading tasks are
unaffected either way.

### Rollback

1. Close the route: stop the cloudflared service.
2. Disable and stop the public server, publisher and health tasks, and kill orphans.
3. Restore the most recent known-good file from `data/backups/public/` over
   `data/boustrategy.public.db` while everything is stopped. Never copy a WAL alone. Backups are
   taken with SQLite's backup API, which keeps opaque public IDs and revocations.
4. Run `pragma integrity_check`, then republish with `ops/publish-public.ps1`, the smoke above and
   the HTTP benchmark.
5. Start the server, publisher and health tasks, confirm health, then start cloudflared.

Leave valuation enabled for a serving-only incident. Disable it for broker authorization, rate,
identity or data-quality incidents.

### Credential rotation

- **Tunnel credential**: run `cloudflared tunnel delete` and then `create` for a new tunnel, copy
  the new JSON into the service directory, update `config.yml`, re-route DNS and restart the
  service.
- **Robinhood grant**: revoke it in Robinhood and re-authorize under the bot's `CODEX_HOME`. No
  broker credential exists in this repository.
- **Discord webhook**: replace it in `ops/digester.local.psd1`.

A restore keeps every public ID that was in the backup. Records published after that backup get
new IDs when republished into the restored file, so take a fresh backup after launch and before
any planned maintenance.

### Launch evidence, September 11, 2026

| Item | Result |
| --- | --- |
| Hostname / tunnel | `https://boustrategy.com`, named tunnel `boustrategy-public` (`71da6f41-72c1-42bb-9c18-4b79d83475b5`), cloudflared 2026.9.1 (Authenticode valid, Cloudflare, Inc.), service Automatic/Running with restart-on-failure, 4 IAD edge connections |
| Commit / build | `cd7329a` on `advisor/039-public-launch`; bundle `index-CwwES6dF.js`, `index-YYVox2WR.css` |
| Gates | 537 Python tests, Ruff, format, mypy (162 files); 36 UI tests, tsc, ESLint, build; `git diff --check` clean |
| HTTP benchmark (100k records) | Overview p95 74-108 ms. Feed p95 446-537 ms against a 500 ms target, identical to the pre-change baseline (510/514 ms) on the same host. Accepted by the maintainer as a host condition; hardening adds no measurable latency. GETs left the store unchanged. |
| Browser pass | 320/375/768/1200 px, 200% zoom, reduced motion, keyboard order and focus rings, skip link first: no horizontal overflow and no CSP violations, both local and through the edge. Maintainer approved the UI. |
| Edge checks | 200 with all security headers, `Server: cloudflare`, `cf-cache-status: DYNAMIC`. `/operate`, `/api/private`, random API and asset paths 404. HTTP to HTTPS 301, `www` to apex 301 keeping the query. TLS 1.1 refused. Also fetched from an unrelated network. |
| Disclosure sweep | 11 public responses checked for the account fingerprint, last four digits, local paths, host user, Codex home, 8378, profile config, webhooks and snapshot IDs: no hits. |
| Origin | Listener on `127.0.0.1:8380` only; no inbound firewall rule. |
| Soak | 30 minutes with the route closed: 6 health cycles ok. Server and publisher child crashes restarted automatically. A forced outage produced one FAILING and one recovered transition. The twelve trading tasks were unchanged. |
| Freshness | Manual in-session tick 13:34 ET (41.9 s), scheduled ticks 13:37, 13:52 and 14:07 all succeeded. The 14:07 observation was public at 18:07:35 UTC, under a second after it was written. |
| Rollback drill | Tunnel stopped: edge 530, fails closed while the local origin stays ok. Public stack stopped independently with trading tasks unchanged. Restored to 200. Backup-restore-republish kept every backed-up public ID. |
| Backups | `data/backups/public/20260911-013303.db` (pre-launch), `20260911-140833.db` (post-launch), both `integrity_check` ok |
| Disclaimer / analytics | None, per the maintainer decision. No analytics, cookies or third-party scripts; the CSP blocks injected scripts. |

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
