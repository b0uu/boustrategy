# Plan 039: Launch the public dashboard and poll live valuations every 15 minutes

> **Executor instructions**: Follow this plan in order and run every verification. Do
> not expose the site until all pre-launch gates pass. If a STOP condition occurs,
> report it; do not improvise. Update this plan's row in `plans/README.md` when done.
>
> **Drift check**: `git diff --stat ec9cfb2..HEAD -- app/broker/collector.py app/public ops docs/public-release.md tests public-ui`
> Existing maintainer-directed UI changes are expected and must be preserved. A hash
> difference alone is not a STOP; a contradicted Current-state signature is.

## Status

- **Priority**: P0
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: none (038 is DONE)
- **Category**: direction, security, ops, product
- **Planned at**: commit `ec9cfb2`, 2026-09-11

## Why this matters

The browser refreshes automatically, but new values appear only after a trusted broker
observation is written and projected into the separate public database. Neither
recurring valuation collection nor publication is supervised, and the origin lacks
the complete hardening required before internet exposure. This plan delivers
15-minute market-session observations, prompt public projection, a loopback-only
origin behind Cloudflare Tunnel, monitoring, stable URLs, and tested rollback.

Do not replace the collector with an unofficial Robinhood client. Broker reads are
currently authenticated through the bot's Codex/MCP identity, fingerprint-check the
account, and use the established storage boundary. Recent reads took about 27-44
seconds. Fifteen minutes (about 26 reads/full session) is the initial balance between
freshness, cost, and failure/rate pressure; one- or five-minute model sessions are not
justified yet.

## Operator decisions

Store non-secret answers in gitignored `ops/public.local.psd1`:

1. **Resolved 2026-09-11**: registrar is Namecheap; Cloudflare DNS delegation for
   `boustrategy.com` is pending nameserver propagation.
2. **Resolved 2026-09-11**: launch directly at the apex hostname
   `https://boustrategy.com`. Do not substitute an `agent.` or `dashboard.` subdomain.
3. Confirm it is intentionally public, without a Cloudflare Access login wall.
4. Complete one interactive Cloudflare authorization. Never paste a tunnel token into
   chat, source, logs, or captured command history.
5. Final agent name/description and a contact or issue-report URL.
6. **Resolved 2026-09-11**: launch without disclaimer text and without analytics,
   cookies, tracking pixels, or third-party telemetry. Do not add substitute legal copy.
7. Accept that this Windows host must stay powered/networked; its trading tasks also
   need the bot's Windows session signed in. A 24/7 SLA requires a later hosted-origin
   migration.
8. Explicit permission before pushing. Local work does not imply push permission.

No Robinhood password, cookie, account number, Cloudflare token, or webhook is needed
in conversation or committed configuration.

## Current state and constraints

- `app/broker/collector.py`: read-only Robinhood session through the bot identity;
  validates fingerprint; `snapshot` persists valuation; cannot review/place orders.
- `ops/run-live-prepare.ps1`: canonical loading/logging/Discord pattern for
  `CollectorModel`, `CodexHome`, and gitignored configuration.
- `ops/install-runtime-tasks.ps1`: interactive/highest principal is required because
  Codex sandboxing fails under batch logon; uses `IgnoreNew` and disabled-by-default.
- `ops/publish-public.ps1`: safe one-shot projection from `data/boustrategy.db` to
  `data/boustrategy.public.db`, deriving enabled profiles from `ops/live.local.json`.
- `app/public/publication.py`: supports `--watch 0.1..60`; the runbook requires an
  external supervisor plus exit, `publication_meta.updated_at`, integrity, and lag
  monitoring.
- `app/public/server.py:328`: binds `127.0.0.1`; keep it. API is `no-store` and private
  routes are absent, but the audit requires response headers and limiting before launch.
- `docs/public-release.md`: authoritative isolation smoke, browser matrix, benchmark,
  stable-ID backup, and corrupt-store recovery.
- Browser refresh is about 30 seconds for feed and 60 seconds for resources. Do not
  add browser-side broker polling.
- Twelve existing `boustrategy-*` tasks were Ready/enabled/successful on 2026-09-11;
  no public or valuation tasks exist. `cloudflared` is not installed.
- Saturday 2026-09-12 is not a market session. A buy is never guaranteed: the next
  scheduled opportunity is Monday 2026-09-14, conditional on reasoning, validation,
  policy, broker review/preflight, market state, and execution.

## Target architecture

```text
Robinhood MCP (read only)
  -> authentic snapshot every 15 min in actual regular session
  -> data/boustrategy.db (private)
  -> supervised publisher (target <=15 s)
  -> data/boustrategy.public.db
  -> read-only FastAPI on 127.0.0.1:8380
  -> cloudflared Windows service -> HTTPS hostname
```

Targets: no overlapping collectors; preserve last good value on failure; successful
changes reach API within 30 seconds; publisher/server restart; tunnel starts at boot;
no private identifiers, paths, prompts, logs, credentials, source DB, or port 8378 are
exposed; backups retain opaque public IDs.

## Commands

| Gate | Command | Expected |
| --- | --- | --- |
| Python | `python -m pytest -q` | all pass |
| Quality | `python -m ruff check .`; `python -m ruff format --check .`; `python -m mypy app tests` | exit 0 |
| UI | `npm --prefix public-ui run test`; `npm --prefix public-ui run type-check`; `npm --prefix public-ui run lint`; `npm --prefix public-ui run build` | exit 0 |
| HTTP | `python -m tests.public.benchmark_http --records 100000 --requests 100 --clients 20` | exit 0, p95 <500 ms |
| Diff | `git diff --check` | no output |

Do not regenerate `public-ui/fixtures/public-v2.json` unless an intentional API shape
change requires it; the repository records that generation is nondeterministic.

## Scope

**In scope**: `app/public/server.py`, narrowly required `app/public/` files,
`ops/run-live-valuation.ps1`, `ops/run-publication-watch.ps1`,
`ops/run-public-server.ps1`, `ops/check-public-health.ps1`,
`ops/install-public-tasks.ps1`, `ops/public.local.example.psd1`, `.gitignore` only for
the local config, relevant `tests/public/` and `tests/broker/`,
`docs/public-release.md`, `README.md` only after launch, and `plans/README.md`.

**Out of scope**: maintainer-owned strategy docs; prompts/policy/order sizing/review or
execution logic; unofficial broker libraries/endpoints; chart interpolation; Access,
analytics, ads, cookies, or accounts; private dashboard/8378; inbound firewall ports;
`0.0.0.0`; replacing the public DB; cloud-origin migration.

## Git workflow

Create `advisor/039-public-launch` only after the current UI has a recovery commit or
can be cleanly excluded. Commit security/tests, wrappers/tasks, runbook, then sanitized
deployment evidence. Never stage unrelated UI/screenshots/data/private config. Do not
push without explicit permission.

## Steps

### 1. Freeze and back up the candidate

Record status, HEAD, tool versions, and UI recovery point. Confirm exactly one intended
enabled profile has a nonempty fingerprint without printing it. Stop publisher, verify
the public DB, and copy it to `data/backups/public/<timestamp>.db`; never copy a WAL
alone.

**Verify**:

```powershell
python -c "import json,pathlib; p=json.loads(pathlib.Path('ops/live.local.json').read_text()); x=[v for v in p['profiles'] if v['enabled']]; assert len(x)==1 and x[0]['broker_account_fingerprint']; print(x[0]['execution_profile_id'])"
python -c "import sqlite3; c=sqlite3.connect('data/boustrategy.public.db'); print(c.execute('pragma integrity_check').fetchone()[0]); c.close()"
```

Expected: intended profile ID, then `ok`; no fingerprint output.

### 2. Harden the public origin

Add headers to every response: `X-Content-Type-Options: nosniff`, restrictive
`Referrer-Policy`, CSP compatible only with built local assets, `Permissions-Policy`
denying unused APIs, and frame denial. Preserve API `Cache-Control: no-store`; do not
add HSTS at the HTTP origin (Cloudflare owns TLS/HSTS).

Add a bounded, expiring per-client API limiter returning 429/`Retry-After`. Only trust
Cloudflare client-IP metadata when arrival through the local tunnel boundary is
provable; otherwise use socket peer. Add `/api/public/v2/health` exposing only status,
public schema/revision, publication timestamp/age; return 503 for unreadable or stale
store. Never reveal paths, counts, host details, IDs, or exceptions.

Tests cover headers on HTML/JSON/404/503; allowance/429/expiry/bounded state/header
spoofing; healthy/stale/corrupt health; and no DB writes/sidecars.

**Verify**: `python -m pytest -q tests/public`; Ruff and mypy pass.

### 3. Add the market-session valuation wrapper

Create `ops/run-live-valuation.ps1` matching `run-live-prepare.ps1`. It must have a
nonblocking mutex, compute America/New_York time through repository calendar helpers,
and no-op on weekends/holidays/outside 09:30-16:00 (respect half-days). Set dedicated
`CODEX_HOME`; invoke only `python -m app.broker.collector ... snapshot`; use a timeout
well below 15 minutes; log sanitized summary/duration/exit; alert on failure and a
configurable consecutive-failure threshold. Never invoke preflight/review/order tools.

Add `-WhatIf` that prints the session decision and sanitized command shape but starts
no model and writes no row. Tests inject times for weekend, holiday, pre-open, 09:30,
midday, 16:00/post-close, half-day, DST, overlap, timeout/failure, and alert redaction.
Store only real observations; UI interpolation may estimate visually, never in data.

**Verify**: broker tests pass; `powershell -NoProfile -ExecutionPolicy Bypass -File
.\ops\run-live-valuation.ps1 -WhatIf` exits 0 with no DB change.

### 4. Add independent publication and server supervisors

Create `ops/run-publication-watch.ps1` and `ops/run-public-server.ps1`. Use absolute
repo paths, timestamped logs, nonzero unexpected-child exits, and sanitized alerts.
Publisher derives profiles exactly like `publish-public.ps1`, runs `--watch 5`, and
never logs fingerprints/arguments. Server requires a valid public DB and built dist,
then binds only loopback 8380. Neither process starts the other or trading schedules.

**Verify** after test-starting both:

```powershell
(Invoke-RestMethod http://127.0.0.1:8380/api/public/v2/health).status
Get-NetTCPConnection -LocalPort 8380 | Select-Object LocalAddress,State
```

Expected: `ok`; listeners only `127.0.0.1`/`::1`.

### 5. Add monitoring and disabled-by-default tasks

`ops/check-public-health.ps1` checks local health, DB integrity/read-only behavior,
publication lag, server, and (when installed) Cloudflare service. Alert only on state
transition/recovery; keep non-secret state under `data/`.

`ops/install-public-tasks.ps1` mirrors existing safe installer behavior and registers:

- `boustrategy-live-valuation`: interactive principal, every 15 minutes weekdays from
  09:30 for 6.5 hours, `IgnoreNew`; wrapper remains holiday/session authority.
- `boustrategy-public-publisher`: logon trigger, long-running/restart/one instance.
- `boustrategy-public-server`: startup/logon after prerequisites, restart/one instance.
- `boustrategy-public-health`: every 5 minutes, bounded/one instance.

Default installation disables these four. `-Enable` enables only them; re-registration
must not touch the existing twelve tasks. Task arguments contain no credentials.

**Verify**: run installer without `-Enable`; all four tasks exist Disabled; exported XML
contains no secrets and correct settings/principal.

### 6. Document operation and local configuration

Add placeholder-only `ops/public.local.example.psd1`; ignore the real file. Update
`docs/public-release.md` with start/stop/restart/status, cadence/cost semantics, browser
vs publication vs broker timing, logs/backup/restore/stable IDs, reboot/sign-in/sleep/
network/MCP-auth/Cloudflare/corruption recovery, credential rotation, and disabling
public exposure without stopping trading. Update root README with the URL only after
launch.

**Verify**: `git check-ignore ops/public.local.psd1` succeeds; secret-pattern review of
`git diff` finds placeholders only.

### 7. Run pre-launch gates and visual acceptance

Run every command in Commands, build, then
`powershell -NoProfile -ExecutionPolicy Bypass -File .\ops\publish-public.ps1 -Quiet`.
Verify public DB integrity. Perform the runbook browser pass at 320, 375, 768, 1200 px,
200% zoom, keyboard-only, and reduced motion; save evidence outside the bundle. The
maintainer must approve this existing UI candidate before exposure.

**Verify**: all commands exit 0; benchmark p95 <500 ms; human visual approval recorded.

### 8. Human checkpoint: install a named Cloudflare Tunnel

STOP until hostname/zone are supplied and the owner authorizes interactively. Install
the current signed Windows `cloudflared`. Use a named production tunnel, never Quick
Tunnel. Route exactly the approved hostname to `http://127.0.0.1:8380`, add the required
catch-all rejection, validate ingress, and install as an Automatic Windows service.
Do not open firewall ports or route 8378; never commit credentials. Initially disable
edge caching for dynamic/API responses and configure baseline TLS/WAF settings.

Official references:

- https://developers.cloudflare.com/tunnel/setup/
- https://developers.cloudflare.com/tunnel/advanced/local-management/as-a-service/windows/
- https://developers.cloudflare.com/tunnel/routing/

**Verify**: `cloudflared --version`; `cloudflared tunnel ingress validate`;
`Get-Service cloudflared` is Running/Automatic; port 8380 remains loopback-only. From
another device HTTPS loads and `/operate`, `/api/private`, random API paths return 404.

### 9. Enable in dependency order and soak

Enable server, publisher, health, then valuation tasks with `-Enable`. Start server and
publisher immediately, keeping the route disabled during a 30-minute soak. Run one
manual valuation only during a real regular session; otherwise wait. Observe six watch/
health cycles, simulate one server and publisher restart, and prove recovery plus one
transition alert.

**Verify**: four tasks enabled/Ready or Running with success results, health `ok`, age
within threshold, and the existing twelve tasks unchanged.

### 10. Open and validate the route

From an unrelated network test homepage, direct route, one decision, APIs, search/
filters/pagination, responsive layout, errors, public headers, and private denylist.
During the next real session prove: task succeeds -> authentic private observation ->
publisher advances within 15 seconds -> health stays good -> browser refresh displays
the point and distinguishes recorded from visual estimates.

This proves freshness, not a trade. Zero trades is valid; execution still requires a
BUY/ADD decision, schema and policy pass, broker review, account-bound preflight,
market conditions, and successful execution.

**Verify**: public HTTPS and health return 200 with required headers/TLS and no internal
disclosure; analytics behavior matches the operator decision.

### 11. Capture evidence and drill rollback

Record sanitized commit/build, hostname, tunnel ID (not credential), task/service state,
test results, backup, health, and screenshots. Disable the tunnel route and prove it
fails closed, then restore it. Prove public tasks stop independently of trading tasks.

Rollback: close route/service; stop public server/publisher/health; restore the known-
good public DB while stopped; integrity-check, republish, smoke/benchmark, reopen.
Leave valuation enabled only for a serving-only incident; disable it for broker auth,
rate, identity, or data-quality incidents.

## Done criteria

- [ ] Full Python/UI gates and benchmark pass (p95 <500 ms).
- [ ] Header, limiter, health, and polling-window tests pass.
- [ ] Four tasks are enabled/healthy; existing twelve unchanged.
- [ ] Exactly one intended profile is published without fingerprint disclosure.
- [ ] Collection cannot overlap or run outside actual regular sessions.
- [ ] Successful observation reaches API within 30 seconds.
- [ ] Origin is loopback-only; no inbound firewall rule exists.
- [ ] Named tunnel service is Automatic/Running; no Quick Tunnel.
- [ ] External HTTPS/responsive/private-route/header/freshness checks pass.
- [ ] Backup and rollback preserve public IDs.
- [ ] No private identifier, path, prompt, log, source data, or credential is exposed.
- [ ] Apex hostname `https://boustrategy.com`, public exposure, agent copy, and
      screenshots are approved;
      launch contains no disclaimer or analytics, per the 2026-09-11 decision.
- [ ] Diff is clean of unrelated changes; no push without permission.
- [ ] `plans/README.md` row is DONE with date/evidence.

## STOP conditions

Stop if broker access needs credentials or unofficial APIs; fingerprint fails or more
than one profile is enabled; interactive bot identity cannot run reliably; cadence
causes auth/rate/terms problems; hardening breaks API/benchmark; any private field is
published; DB paths match/integrity fails/backup is unsafe; origin must bind publicly;
an inbound port/private-dashboard route is requested; hostname/public approval is
missing; TLS/1016/staleness persists after one repair; verification fails twice; a
maintainer-owned strategy document is needed; or unrelated UI changes cannot be
isolated safely.

## Maintenance notes

Review cadence after two weeks using duration, failure, cost, rate pressure, and usage.
Move to five minutes only with evidence; back off to thirty on pressure. A direct feed
is preferable only if an approved provider offers a stable permitted read-only API,
scoped credentials, documented limits, identity guarantees, and a testable contract;
implement it behind existing `AccountObservation`/snapshot interfaces. Keep existing
event-driven snapshots: periodic polling is visualization freshness, not execution
authority. If uptime matters, next replicate only the public-safe DB/static bundle to
a managed origin. Preserve mapping/revocation state on every restore and review CSP
before adding any third-party asset.
