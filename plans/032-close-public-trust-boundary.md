# Plan 032: Make the published store the only source for public reads and keep account identity out of it

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Ordering note (added 2026-09-08)**: plan 037 retires the public v1
> routes and `app/public/projection.py` entirely and drops the private
> source path from `create_public_app`. Run 037 FIRST. After it lands, skip
> Steps 1, 2 and 4 of this plan (they are superseded) and execute only
> Steps 3, 5 and 6 (checkpoint identity digest, release-gate test, X-excerpt
> rule); the done criteria that mention `db_path`/`open_readonly(path)` are
> then already satisfied. If 037 has NOT landed, execute this plan as written.
>
> **Drift check (run first)**: the in-scope files are UNTRACKED in git at the
> time of writing (the whole `app/public/` package is uncommitted work), so
> `git diff` cannot detect drift. Instead compare every "Current state"
> excerpt below against the live file with `sed -n '<start>,<end>p' <file>`.
> On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `40b317b` (branch `advisor/030-private-dual-agent-dashboard`, working tree uncommitted), 2026-09-08

## Why this matters

The public dashboard is designed around one boundary: the internet-facing
FastAPI process reads only a separately produced, read-only "published" SQLite
file (`data/boustrategy.public.db`), which the trusted publisher fills after
applying every publication rule (portfolio scope, live-profile gating,
revocation, withdrawal, source approval). Today that boundary fails open in two
ways:

1. Both `/api/public/v1/*` routes silently fall back to reading the **private
   source database** whenever the published file does not exist, using a
   projection that applies none of the publication rules. A renamed, deleted,
   or not-yet-created public file turns the public API into a reader of the
   private store, exposing decisions that were never approved for publication
   and decisions that were revoked (revocation state lives only in the public
   store).
2. The publisher writes the live broker account fingerprint and the live
   execution profile IDs in cleartext into the published file's
   `publication_checkpoint` row. The release doctrine in
   `docs/public-release.md` says no execution profile or account fingerprint
   may appear in the public artifact. No route serves the row today, but the
   file is what gets copied to the internet host.

A third, smaller gap: the maintainer's decision (plans/README.md, "Dashboard X
content") is that only BouStrategy claim summaries and links may be public,
never X post content. The source-excerpt path permits an X-typed source's
excerpt to reach the public UI as a quoted block if an author sets one flag.
This plan makes that structural.

After this plan: the public process never opens the private database; the
published file contains no account fingerprint or profile ID; X-typed sources
never carry an excerpt into the public store.

## Current state

Files and roles:

- `app/public/server.py` — builds the public FastAPI app. `create_public_app(db_path, frontend_dir, *, public_db_path)` takes BOTH the private source path and the published path.
- `app/public/projection.py` — the legacy "v1" projector that reads decision records directly from the source database. Still used at publication time for the paper view (`publication.py:900`), so it must NOT be deleted.
- `app/public/publication.py` — the trusted publisher; `publish()` writes the checkpoint at lines ~201-246.
- `app/public/explanations.py` — builds the public source list (`eligible_sources`) and narrative projection.
- `app/public/database.py` — `open_readonly(path)`; returns an in-memory empty connection when the file does not exist.
- `tests/public/test_public_dashboard.py` — currently exercises the v1 routes AGAINST the source database without publishing (the behavior this plan removes).
- `tests/public/test_public_v2.py` — `seed(source, count)` helper and v2 route tests; the exemplar for "seed source, publish, query".
- `tests/public/test_release.py` — release-gate tests; the exemplar for "assert the public file contains no private strings".

### Excerpt A — `app/public/server.py:22-33` (app construction)

```python
def create_public_app(
    db_path: str | Path,
    frontend_dir: str | Path = "public-ui/dist",
    *,
    public_db_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="BouStrategy public dashboard", docs_url=None, redoc_url=None, openapi_url=None
    )
    path = Path(db_path)
    published = Path(public_db_path) if public_db_path else path.with_name(f"{path.stem}.public.db")
    assets = Path(frontend_dir)
```

### Excerpt B — `app/public/server.py:51-59` (v1 dashboard fallback)

```python
    @app.api_route(
        "/api/public/v1/dashboard", methods=["GET", "HEAD"], response_model=PublicDashboard
    )
    def public_dashboard() -> PublicDashboard:
        if not published.exists():
            with open_readonly(path) as conn:
                return projection.dashboard(conn, include_history=False)
        with open_readonly(published) as conn:
            return queries.legacy_dashboard(conn)
```

### Excerpt C — `app/public/server.py:61-90` (v1 decision fallback)

```python
    def public_decision(ticker: str, created_at: str) -> PublicDecision:
        if published.exists():
            ...
                result = queries.legacy_decision(conn, matches[0][0])
        else:
            with open_readonly(path) as conn:
                result = projection.decision(conn, ticker, created_at)
        if result is None:
            raise HTTPException(404, "public decision not found")
        return result
```

### Excerpt D — `app/public/server.py:351-359` (CLI)

```python
def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.public.server")
    parser.add_argument("--db", default="data/boustrategy.db")
    parser.add_argument("--public-db")
    parser.add_argument("--port", type=int, default=8380)
    args = parser.parse_args()
    uvicorn.run(
        create_public_app(args.db, public_db_path=args.public_db), host="127.0.0.1", port=args.port
    )
```

### Excerpt E — `app/public/server.py:41-49` (existing 503 handler — reuse its shape)

```python
    @app.exception_handler(sqlite3.Error)
    async def unavailable(request: Request, exc: sqlite3.Error) -> JSONResponse:
        logging.getLogger(__name__).exception("Public store read failed", exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "public_data_unavailable"},
            headers={"Retry-After": "30"},
        )
```

### Excerpt F — `app/public/publication.py:201-232` (checkpoint content)

```python
            checkpoint = json.dumps(
                {
                    "version": 7,
                    "accounting_clock": accounting_clock,
                    "profiles": sorted(live_profiles),
                    "account": live_account_id,
                    "changes": changes,
                },
                sort_keys=True,
            )
            previous_row = target.execute(
                "SELECT content FROM publication_checkpoint WHERE singleton=1"
            ).fetchone()
            previous = json.loads(previous_row[0]) if previous_row and not rebuild else None
            current = json.loads(checkpoint)
            if changes and previous == current:
                return counts
            same_configuration = bool(
                changes
                and previous
                and previous["version"] == current["version"]
                and previous["profiles"] == current["profiles"]
                and previous["account"] == current["account"]
                ...
```

`live_profiles` is a tuple of execution profile IDs and `live_account_id` is the
broker account fingerprint (compared against `broker_account_fingerprint` at
`publication.py:~498-502`). Both are private producer inputs per
`docs/public-release.md:45-47`.

### Excerpt G — `app/public/explanations.py:18-33` (source list)

```python
    for public_id, raw in conn.execute(
        "SELECT s.public_id, s.record_json FROM public_source_records s WHERE NOT EXISTS "
        "(SELECT 1 FROM public_source_records n WHERE n.supersedes=s.revision_id)"
    ):
        source = PublicSourceRecord.model_validate_json(raw)
        if source.approved_for_publication and source.access == "public":
            sources[source.source_ref] = {
                "public_id": public_id,
                "title": source.title,
                "publisher": source.publisher,
                "published_on": source.published_on.isoformat() if source.published_on else None,
                "source_type": source.source_type,
                "url": source.url,
                "excerpt": source.excerpt if source.excerpt_approved else None,
            }
```

`app/public/projection.py:33` lists `"X"` among `_PUBLIC_SOURCE_TYPES`, and
`app/schemas/public_authoring.py:~98` allows `source_type == "X"`.

### Excerpt H — `tests/public/test_public_dashboard.py:13-28` (tests that enshrine the fallback)

```python
def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    db_path = tmp_path / "public.db"
    return TestClient(create_public_app(db_path, tmp_path / "missing-ui")), db_path


def test_public_api_has_only_read_methods_and_empty_states(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    response = client.get("/api/public/v1/dashboard")

    assert response.status_code == 200
    assert response.json()["performance"]["status"] == "unavailable"
    assert response.json()["decisions"] == []
```

Note the misleading name: `db_path` here is a SOURCE database (the test later
does `connect(db_path)` and inserts decision records), and the v1 route reads it
directly because no published file exists. `test_public_v2.py:36-44`
(`test_readonly_missing_database_never_creates_file_and_rejects_writes`) also
asserts `client.get("/api/public/v1/dashboard").status_code == 200` with no
published file.

### Repo conventions that apply

- AGENTS.md: crash early; no protective try/except; no single-use helpers; comments only for non-obvious business logic; plain pytest functions in arrange/act/assert style.
- Public read tests follow the pattern in `tests/public/test_public_v2.py:47-52`: `seed(source)`, `publish(source, public)`, `TestClient(create_public_app(source, public_db_path=public))`, then GET.
- Publication doctrine (`docs/public-release.md:98-102`): "no execution profile, account fingerprint, source key, local path, raw prompt, broker ID, or worker log appears" in the public surface.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install (once) | `python -m pip install -e .[dev]` | exit 0 |
| Public tests | `python -m pytest -q tests/public` | all pass |
| Full tests | `python -m pytest -q` | 506+ pass (count grows with new tests) |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format | `python -m ruff format --check .` | `N files already formatted` |
| Types | `python -m mypy app tests` | `Success: no issues found` |

## Scope

**In scope** (the only files you should modify):
- `app/public/server.py`
- `app/public/publication.py` (checkpoint block only, lines ~201-232, plus the `"version"` bump)
- `app/public/explanations.py` (the `eligible_sources` loop only)
- `tests/public/test_public_dashboard.py`
- `tests/public/test_public_v2.py` (the one v1 assertion at line ~43 only)
- `tests/public/test_release.py` (add one test)
- `tests/public/test_explanations.py` (add one test)
- `docs/public-release.md` (one sentence: the server no longer takes `--db`)
- `docs/reasoning/RUNTIME.md` lines 158-159 (fix `data/public.db` to `data/boustrategy.public.db` while you are there — the two runbooks currently disagree)

**Out of scope** (do NOT touch, even though they look related):
- `app/public/projection.py` — still used by `publish()` for the paper view at publication time. Do not delete or edit it.
- `app/public/queries.py`, `app/public/activity.py` — the v2 read path is already published-store-only.
- `public-ui/` — no frontend change; the v1 response shapes are unchanged for the published case.
- Any other checkpoint semantics (the `changes` tuple comparison, `same_configuration` logic) beyond replacing the two identity fields.
- Response-hardening headers (CSP etc.) — a separate follow-up, not this plan.

## Git workflow

- Branch: `advisor/032-close-public-trust-boundary`, created from the current working branch. NOTE: the working tree contains a large uncommitted delta that is not yours. Do not stage or commit files outside the in-scope list. Use `git add <explicit paths>` only, never `git add -A` or `git add .`.
- Commit message style (from `git log`): conventional prefix, e.g. `fix: refresh live state at submission`. Use `fix: serve public routes only from the published store`.
- Do NOT push or open a PR.

## Steps

### Step 1: Remove the private-source fallback from both v1 routes

In `app/public/server.py`:

1. In `public_dashboard()` (Excerpt B) replace the `if not published.exists(): ...` block so the route raises `HTTPException(503, "public_data_unavailable", headers={"Retry-After": "30"})` when `published.exists()` is false, and otherwise reads from `published` exactly as today. Match the body shape of the existing sqlite3 handler (Excerpt E): the JSON body must be `{"detail": "public_data_unavailable"}`.
2. In `public_decision()` (Excerpt C) delete the `else:` branch that calls `projection.decision(conn, ticker, created_at)`; when `published.exists()` is false raise the same 503.
3. Remove the now-unused `projection` import if nothing else in `server.py` uses it (check with `grep -n "projection\." app/public/server.py`).

Keep `path` (the source path) in `create_public_app` for now — Step 2 removes it.

**Verify**: `python -m pytest -q tests/public/test_public_dashboard.py` → FAILS on the v1 tests (expected; Step 4 fixes them). `python -m ruff check app/public/server.py` → passes.

### Step 2: Stop the public process from knowing the private database path

In `app/public/server.py`:

1. Change the signature to `create_public_app(public_db_path: str | Path, frontend_dir: str | Path = "public-ui/dist") -> FastAPI`. Remove `db_path`, remove the `path` variable and the `path.with_name(...)` default. `published = Path(public_db_path)`.
2. Search the file for every remaining use of `path` that referred to the source and delete it. There must be no `open_readonly(path)` left.
3. Update `main()` (Excerpt D): remove the `--db` argument; make `--public-db` required (`required=True`); call `create_public_app(args.public_db, ...)`.
4. Update every caller. Run `grep -rn "create_public_app(" app tests public-ui/fixtures` and change each call from `create_public_app(source, ..., public_db_path=public)` to `create_public_app(public, ...)`. Known callers at time of writing: `tests/performance/test_reporting.py:369`, `tests/public/benchmark_http.py:247,257`, `tests/public/test_activity.py:107`, `tests/public/test_explanations.py:77,209,282,335`, `tests/public/test_public_v2.py` (several), `tests/public/test_release.py:~39`, `tests/public/test_public_dashboard.py:15`. If `grep` shows callers outside the in-scope list other than these test files, STOP (see STOP conditions) — but editing the call expression in any `tests/**` or `public-ui/fixtures/*.py` file is permitted for this step.
5. In `docs/public-release.md:70` change the serve command to `python -m app.public.server --public-db data/boustrategy.public.db --port 8380` and adjust the surrounding sentence if it mentions `--db`.

**Verify**: `grep -rn "open_readonly(path)" app/public/server.py` → no matches. `python -m mypy app tests` → `Success`.

### Step 3: Replace account fingerprint and profile IDs in the checkpoint with a digest

In `app/public/publication.py` (Excerpt F):

1. Compute `identity = hashlib.sha256(json.dumps({"profiles": sorted(live_profiles), "account": live_account_id}, sort_keys=True).encode("utf-8")).hexdigest()` immediately before building `checkpoint`. `hashlib` and `json` are already imported.
2. In the checkpoint dict replace the two keys `"profiles"` and `"account"` with a single key `"identity": identity`.
3. Bump `"version": 7` to `"version": 8` so every existing published store refreshes its projections once (this is the established mechanism; `docs/plan-031-audit.md` records version 7 doing the same).
4. In the `same_configuration` expression replace the two comparisons `previous["profiles"] == current["profiles"] and previous["account"] == current["account"]` with `previous["identity"] == current["identity"]`.
5. Search the rest of `publication.py` for any other read of `previous["profiles"]` or `previous["account"]` (`grep -n '\["profiles"\]\|\["account"\]' app/public/publication.py`). If any exist outside the block you edited, STOP.

The equality-only comparison keeps the incremental-publish behavior intact; the
digest is compared, never decoded.

**Verify**: `python -m pytest -q tests/public/test_release.py tests/public/test_public_v2.py` → pass.

### Step 4: Rewrite the v1 tests to go through publication

In `tests/public/test_public_dashboard.py`:

1. Change `_client` to create a source db AND publish it: seed the source with whatever records the test needs, call `publish(source, public)`, return `TestClient(create_public_app(public, tmp_path / "missing-ui"))` plus the source path. Model the seed/publish sequence after `tests/public/test_public_v2.py:47-52`. Tests that insert records after creating the client must call `publish(source, public)` again before asserting on the route.
2. Add one new test `test_v1_routes_return_503_when_published_store_is_absent`: create the app with a public path that does not exist, GET `/api/public/v1/dashboard` and `/api/public/v1/decisions/NVDA/2026-06-10T00:00:00Z`; assert status 503, JSON `{"detail": "public_data_unavailable"}`, and `Retry-After` header `30` on both. Also assert the public file was NOT created (`not public.exists()`).
3. In `tests/public/test_public_v2.py` (~line 43) change `assert client.get("/api/public/v1/dashboard").status_code == 200` to `== 503`.

**Verify**: `python -m pytest -q tests/public` → all pass.

### Step 5: Add a release-gate test that the published file carries no account identity

In `tests/public/test_release.py` add `test_published_store_contains_no_profile_or_account_identity`:

- Arrange: `seed(source)`; call `publish(source, public, live_profiles=("codex",), live_account_id="f" * 16)` (the test helper `_profile()` in `tests/reason/test_live_submit.py` uses fingerprints like `"0" * 16`; any 16-char string is fine here).
- Act: read the whole published file as bytes: `blob = public.read_bytes()`; also read the checkpoint row: `json.loads(conn.execute("SELECT content FROM publication_checkpoint").fetchone()[0])`.
- Assert: `b"codex" not in blob` is too broad if a decision mentions the word; instead assert `b'"profiles"' not in blob`, `b'"account"' not in blob`, `("f" * 16).encode() not in blob`, and the checkpoint dict has key `"identity"` and no key `"profiles"` or `"account"`.

**Verify**: `python -m pytest -q tests/public/test_release.py` → passes, including the new test.

### Step 6: Never publish an excerpt for an X-typed source

In `app/public/explanations.py` (Excerpt G) change the excerpt expression to
`source.excerpt if source.excerpt_approved and source.source_type != "X" else None`.
Add a one-line comment above it stating the business rule: X post content is
never republished; only the claim summary and link are public (decision
recorded in `plans/README.md`, "Dashboard X content").

In `tests/public/test_explanations.py` add
`test_x_typed_source_never_publishes_an_excerpt`, modeled on the existing test
around line 77-92 that asserts `detail["narrative"]["sources"][0]["excerpt"] is None`:
register a source with `source_type="X"`, `excerpt="PRIVATE_X_TEXT"`,
`excerpt_approved=True`, `approved_for_publication=True`, `access="public"`;
publish; fetch the decision detail; assert the excerpt is `None` and
`"PRIVATE_X_TEXT"` does not appear anywhere in the published file bytes. Look at
how that existing test builds its source record (`source_record(...)` helper at
`tests/public/test_explanations.py` and `save_public_source`) and reuse it.

**Verify**: `python -m pytest -q tests/public/test_explanations.py` → passes.

### Step 7: Full gates

Run all commands in the table. Then `git status --short` and confirm only in-scope files changed (plus the files whose `create_public_app(` call you updated in Step 2).

## Test plan

- `tests/public/test_public_dashboard.py`: existing v1 tests now seed → publish → read; new 503 test for the absent published store.
- `tests/public/test_release.py`: new test that the published file has no `profiles`/`account` keys and no fingerprint bytes.
- `tests/public/test_explanations.py`: new test that X-typed source excerpts are never materialized.
- Pattern: `tests/public/test_public_v2.py` (seed/publish/client), `tests/public/test_release.py:27-60` (release-gate assertions).
- Verification: `python -m pytest -q` → all pass, 3 new tests.

## Done criteria

- [ ] `grep -n "db_path\|open_readonly(path)" app/public/server.py` → no matches
- [ ] `grep -n '"profiles"\|"account"' app/public/publication.py` → no matches
- [ ] `grep -n '"version": 8' app/public/publication.py` → one match
- [ ] `python -m pytest -q` exits 0
- [ ] `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app tests` all exit 0
- [ ] `git status --short` shows no modified files outside the in-scope list and the Step 2 call-site files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt does not match the live file.
- `grep -rn "create_public_app(" app` shows a caller inside `app/` other than `app/public/server.py:main`.
- `previous["profiles"]` or `previous["account"]` is read anywhere in `publication.py` outside the checkpoint block in Excerpt F.
- A v2 test (`tests/public/test_public_v2.py`, `test_activity.py`) starts failing after Step 3 for a reason other than the version bump forcing a full refresh — that would mean the `same_configuration` change altered incremental semantics.
- The `public-ui/fixtures/generate.py` script calls `create_public_app` with a source path in a way you cannot update without changing its output JSON.

## Maintenance notes

- Any new public route must read from `published` only. There is now no source-path variable in `server.py` to reach for; keep it that way.
- If the checkpoint ever needs to expose which profiles were published (for operator diagnostics), expose it from the PRIVATE dashboard by recomputing the digest, not by storing the raw values in the public file.
- Deferred follow-ups (not this plan): response-hardening headers on the public server (CSP, `X-Content-Type-Options`, `Referrer-Policy`); per-IP request limiting before internet exposure; retiring the v1 routes in favor of v2 once the maintainer decides the deprecation.
- Reviewer focus: confirm the 503 body shape matches the existing sqlite3 handler so the frontend's "unavailable" state handling stays uniform; confirm the version bump is 8 and no other checkpoint key changed.
