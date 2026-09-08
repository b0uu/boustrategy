# Plan 032: Keep account identity out of the published store and never publish X-typed excerpts

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: the in-scope files under `app/public/` are
> UNTRACKED in git (uncommitted plan-031 work), so `git diff` cannot detect
> drift. Instead run each `grep`/`sed` command in the "Current state" section
> and confirm the output matches what is shown. On a mismatch, treat it as a
> STOP condition.
>
> **History**: rewritten 2026-09-08 after plan 037 landed. 037 already removed
> the public v1 routes, `app/public/projection.py`, and the private source
> path from `create_public_app`, so the earlier version of this plan's
> "source-database fallback" finding is closed. Two findings remain.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plan 037 (DONE; this plan assumes its state)
- **Category**: security
- **Planned at**: commit `0702ddd` (branch `advisor/037-retire-finished-subsystems`; `app/public/*` still uncommitted in the working tree), 2026-09-08

## Why this matters

The public dashboard reads only a separately produced SQLite file
(`data/boustrategy.public.db`) that the trusted publisher fills. That file is
what gets copied to the internet host, so nothing account-identifying may be
in it. Two gaps remain:

1. The publisher writes the live broker account fingerprint and the live
   execution profile IDs in cleartext into the published file's
   `publication_checkpoint` row. `docs/public-release.md:45-47` calls these
   "private producer inputs" and `:98-102` requires that no execution profile
   or account fingerprint appear in the public surface. No route serves the
   row today; the file itself is the leak.
2. The maintainer's standing decision (plans/archive/README.md, "Dashboard X
   content": claim summaries and links only, X post content is never
   republished) is enforced for decision claims but not for source excerpts:
   an X-typed source's excerpt reaches the public narrative and the React
   `<blockquote>` if an author sets `excerpt_approved`. One mis-set flag
   publishes third-party post text.

After this plan: the checkpoint stores a digest of the identity inputs and
never the values; X-typed sources never carry an excerpt into the public store;
both are covered by tests that read the published file's bytes.

## Current state

Files and roles:

- `app/public/publication.py` — the trusted publisher. `publish(source_path, public_path, *, live_profiles=(), live_account_id=None, rebuild=False)` at line 180.
- `app/public/explanations.py` — `eligible_sources(conn)` builds the public source list (lines 13-32).
- `tests/public/test_release.py` — release-gate tests; exemplar for "seed → publish → assert on the published file".
- `tests/public/test_explanations.py` — has `source_record(**changes)` (line 25) building a `PublicSourceRecord` with `excerpt="PRIVATE_EXCERPT"`, and `save_public_source` from `app.storage.public_records`.
- `tests/public/test_public_v2.py` — `seed(source, count=3)` at line 19.

### Excerpt A — every checkpoint identity read in `publication.py`

Run `grep -n '"profiles"\|"account"\|"version"' app/public/publication.py` and confirm exactly these six lines:

```
215:                    "version": 7,
217:                    "profiles": sorted(live_profiles),
218:                    "account": live_account_id,
233:                and previous["version"] == current["version"]
234:                and previous["profiles"] == current["profiles"]
235:                and previous["account"] == current["account"]
260:                and previous["version"] == current["version"]
261:                and previous["profiles"] == current["profiles"]
262:                and previous["account"] == current["account"]
```

(Line 215 is the version; the comparisons at 233-235 are inside the
`same_configuration = bool(...)` expression; the comparisons at 260-262 are
inside the later `if (changes and previous and ...)` early-return block that
only bumps `publication_meta.updated_at`.) There are exactly TWO comparison
sites; both change.

`sed -n 213,222p app/public/publication.py`:

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
```

`hashlib` and `json` are already imported in `publication.py` (lines 8-9).

### Excerpt B — `app/public/explanations.py:22-31`

```python
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

`PublicSourceRecord` (`app/schemas/public_authoring.py:90-103`) has
`source_type: Literal["SEC", "COMPANY_IR", "NEWS", "X", "PRICE_DATA", "MACRO", "ETF_ISSUER"]`,
`excerpt: Text | None = None`, `excerpt_approved: bool = False`.

### Excerpt C — `tests/public/test_explanations.py:25-42` (helper)

```python
def source_record(**changes: object) -> PublicSourceRecord:
    return PublicSourceRecord.model_validate(
        {
            "revision_id": "revision-private",
            "source_ref": "internal-source",
            "recorded_at": NOW,
            "title": "Quarterly results",
            "publisher": "Company IR",
            "published_on": "2026-06-10",
            "source_type": "COMPANY_IR",
            "url": "https://example.com/results#revenue",
            "access": "public",
            "approved_for_publication": True,
            "excerpt": "PRIVATE_EXCERPT",
            **changes,
        }
    )
```

The first test in that file (`test_public_narrative_feed_exports_and_source_retraction`,
lines 45-100) shows the full seed → `publish(source, public)` →
`TestClient(create_public_app(public))` → `GET /api/public/v2/decisions?portfolio_id=paper&q=...`
→ `GET /api/public/v2/decisions/{public_id}` sequence and asserts
`detail["narrative"]["sources"][0]["excerpt"] is None` (because
`excerpt_approved` defaults to False). Model the new test on it.

### Repo conventions that apply

- AGENTS.md: crash early; no single-use helpers; comments only for non-obvious business logic; plain pytest functions, arrange/act/assert.
- Publication changes that alter existing projections bump the checkpoint `"version"` so existing public stores refresh (`docs/plan-031-audit.md`: version 7 did this).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Public tests | `python -m pytest -q tests/public` | all pass |
| Full tests | `python -m pytest -q` | all pass |
| Lint | `python -m ruff check .` | `All checks passed!` |
| Format | `python -m ruff format --check .` | `N files already formatted` |
| Types | `python -m mypy app tests` | `Success: no issues found` |
| Frontend | `npm --prefix public-ui run test` | 26 pass (uses the checked-in fixture; do not regenerate it) |

## Scope

**In scope** (the only files you should modify):
- `app/public/publication.py` — lines 213-222 (checkpoint dict), 233-235 and 260-262 (the two comparison sites) only
- `app/public/explanations.py` — the `excerpt` line in Excerpt B only
- `tests/public/test_release.py` — add one test
- `tests/public/test_explanations.py` — add one test

**Out of scope** (do NOT touch):
- `app/public/server.py`, `app/public/queries.py`, `app/public/activity.py` — already published-store-only after plan 037.
- Any other checkpoint semantics (`changes` tuple comparison, `accounting_clock`, `same_configuration`'s remaining clauses).
- `public-ui/` — no frontend change.
- Response-hardening headers and rate limiting — separate backlog items.

## Git workflow

- Branch: `advisor/032-close-public-trust-boundary`, created from `advisor/037-retire-finished-subsystems`. The tree still contains a large uncommitted delta that is not yours: stage only in-scope paths with `git add <path>`; never `git add -A` or `git add .`.
- Commit message: `fix: keep account identity and X excerpts out of the published store`.
- Do NOT push.

## Steps

### Step 1: Replace the identity fields in the checkpoint with a digest

In `app/public/publication.py`:

1. Immediately before `checkpoint = json.dumps(` (line 213) add:
   ```python
   identity = hashlib.sha256(
       json.dumps(
           {"profiles": sorted(live_profiles), "account": live_account_id}, sort_keys=True
       ).encode("utf-8")
   ).hexdigest()
   ```
   with a one-line comment: the published file must not contain the profile IDs or the account fingerprint; equality on the digest is all the checkpoint needs.
2. In the checkpoint dict replace the two lines `"profiles": sorted(live_profiles),` and `"account": live_account_id,` with `"identity": identity,`.
3. Change `"version": 7` to `"version": 8`.
4. At BOTH comparison sites (lines 234-235 and 261-262) replace the two lines
   `and previous["profiles"] == current["profiles"]` / `and previous["account"] == current["account"]`
   with the single line `and previous["identity"] == current["identity"]`.
5. Re-run `grep -n '"profiles"\|"account"' app/public/publication.py` → no matches.

**Verify**: `python -m pytest -q tests/public` → all pass (existing tests republish from scratch, so the version bump only forces one refresh).

### Step 2: Release-gate test that the published file carries no identity

In `tests/public/test_release.py` add
`test_published_store_contains_no_profile_or_account_identity`:

- Arrange: `source, public = tmp_path / "source.db", tmp_path / "public.db"`; `seed(source)`.
- Act: `publish(source, public, live_profiles=("codex",), live_account_id="f" * 16)`; `blob = public.read_bytes()`; open the public file with `open_readonly(public)` and read `json.loads(conn.execute("SELECT content FROM publication_checkpoint").fetchone()[0])`.
- Assert: `b'"profiles"' not in blob`; `b'"account"' not in blob`; `("f" * 16).encode() not in blob`; the checkpoint dict has key `"identity"` (64 hex chars) and has neither `"profiles"` nor `"account"`; `checkpoint["version"] == 8`.

(`publish` with a `live_account_id` and no live records is valid: the
fingerprint check at `publication.py:512` only fires when live snapshots exist.)

**Verify**: `python -m pytest -q tests/public/test_release.py` → passes, including the new test.

### Step 3: Never publish an excerpt for an X-typed source

In `app/public/explanations.py` (Excerpt B) change the excerpt line to:

```python
"excerpt": source.excerpt if source.excerpt_approved and source.source_type != "X" else None,
```

with a one-line comment above it: X post content is never republished; only
the claim summary, title, publisher and link are public (maintainer decision,
plans/archive/README.md "Dashboard X content").

**Verify**: `python -m ruff check app/public/explanations.py` → passes.

### Step 4: Test that X-typed excerpts never materialize

In `tests/public/test_explanations.py` add
`test_x_typed_source_never_publishes_an_excerpt`, modeled on the first test in
the file (lines 45-100):

- Arrange: `save_public_source(conn, source_record(source_type="X", excerpt="PRIVATE_X_TEXT", excerpt_approved=True, url="https://x.com/someone/status/1"))`; seed one decision whose `source_claims` references `"internal-source"` with `source_type="X"` and `public_safe=True` (copy the claim shape from the first test and change the type); `process_decision(...)`; `publish(source, public)`.
- Act: fetch the decision detail through the v2 feed and detail routes as the first test does.
- Assert: every entry in `detail["narrative"]["sources"]` has `excerpt is None`; `b"PRIVATE_X_TEXT" not in public.read_bytes()`; and a positive control in the same test: republishing after `save_public_source(conn, source_record(revision_id="revision-2", source_ref="ir-source", source_type="COMPANY_IR", excerpt="APPROVED_IR_TEXT", excerpt_approved=True))` referenced by a second claim yields `excerpt == "APPROVED_IR_TEXT"` for that source (so the rule is type-specific, not a blanket suppression).

If wiring the positive control through claims is awkward, split it into a
second test; do not drop it.

**Verify**: `python -m pytest -q tests/public/test_explanations.py` → passes.

### Step 5: Full gates

Run every command in the table; `git status --short` shows only the four in-scope files changed by you.

## Test plan

- `tests/public/test_release.py`: published file has no `profiles`/`account` keys and no fingerprint bytes; checkpoint version is 8.
- `tests/public/test_explanations.py`: X-typed excerpt never materializes; non-X approved excerpt still does.
- Verification: `python -m pytest -q` → all pass, 2 new tests.

## Done criteria

- [ ] `grep -n '"profiles"\|"account"' app/public/publication.py` → no matches
- [ ] `grep -n '"identity"' app/public/publication.py` → 3 matches (dict key + two comparisons)
- [ ] `grep -n '"version": 8' app/public/publication.py` → one match
- [ ] `grep -n 'source_type != "X"' app/public/explanations.py` → one match
- [ ] `python -m pytest -q` exits 0 with the two new tests present
- [ ] `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy app tests` exit 0
- [ ] `npm --prefix public-ui run test` exits 0 with the fixture file unchanged (`public-ui/fixtures/public-v2.json` is not regenerated by this plan)
- [ ] `git status --short` shows no changes outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- The `grep` in Excerpt A does not return exactly those six lines (a third comparison site or a new identity field exists).
- A v2 test in `tests/public/test_public_v2.py` or `test_activity.py` fails after Step 1 for a reason other than the version bump forcing a full refresh.
- `PublicSourceRecord` no longer has `source_type`/`excerpt_approved` with the shapes shown.
- `npm --prefix public-ui run test` fails after your change. (Do NOT use a byte-diff of `public-ui/fixtures/public-v2.json` as a check: the generator embeds `published_at`, `server_now` and random public/claim/source ids, so two consecutive runs on an unchanged tree differ by ~700 lines. Leave the fixture file as it is; the React tests are the contract check. Corrected 2026-09-08 after an executor STOP.)

## Maintenance notes

- If operator diagnostics ever need to show which profiles were published, recompute the digest on the PRIVATE side; never store the raw values in the public file.
- Any new public source field must be reviewed against the X-content rule; the type check in `eligible_sources` is the single enforcement point.
- Deferred: response-hardening headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`) and per-IP request limiting on the public server; both are in the backlog in `plans/README.md`.
