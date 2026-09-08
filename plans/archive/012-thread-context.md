# Plan 012: Thread context — parent-post capture, conversation grouping, consolidated review

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> a STOP condition occurs, stop and report — do not improvise. Commit on
> branch `advisor/012-thread-context`, one commit per step or logical unit,
> short lowercase imperative messages, do NOT push. Do not update
> `plans/README.md` — the reviewer maintains the index.
>
> **Drift check (run first)**: `git diff --stat 175c70c..HEAD -- app/ tests/`
> (drift in docs/ or plans/ is fine; drift in app/ or tests/ beyond commits
> `18ab8db`/`26ebb59` — which touch only docs — means STOP).

## Status

- **Priority**: P1 (live trial is running; every day without this collects context-poor replies)
- **Effort**: M
- **Depends on**: 010, 011 (landed on main)
- **Category**: direction
- **Planned at**: commit `26ebb59` (main also carries docs-only commits), 2026-07-13

## Why this matters

The X trial is LIVE with a real database (`data/boustrategy.db`, 1,398
posts). Replies fetched today store only their own text — "Yes, and TSMC
confirmed this" is unreviewable and, worse, untrainable: the maintainer
labels with thread context (via click-through) that the stored input
lacks, so the future relevance gate would train on mismatched input/label
pairs. Maintainer decisions (2026-07-13):

1. Fetch and store one level of parent context (`referenced_tweets`
   expansion + `conversation_id`).
2. Show that context in the review UI above the post.
3. Consolidate multiple unreviewed posts by the SAME handle in the SAME
   conversation into one review action.

**Live-database constraint (hard)**: `data/boustrategy.db` already exists
with trial data. All schema changes must be additive and idempotent
(ALTER TABLE ADD COLUMN guarded by a column-existence check). Existing
rows keep empty context — that is expected and fine. Nothing may rewrite,
delete, or re-fetch existing rows.

**Billing conservatism**: whether expansion-included parent posts bill as
reads is not clearly documented. Count them: `record_post_reads` gets
`len(data) + len(includes.tweets)`.

## Current state (all on main)

- `app/x/client.py` — `fetch_user_posts(user_id, handle, since_id=None)`:
  params `{"max_results": "100", "tweet.fields": "created_at,text,note_tweet"}`,
  GET `{BASE}/users/{user_id}/tweets`, maps via module-level
  `_map_tweet(tweet: dict[str, Any], handle: str, fetched_at: datetime) -> XPost`
  (prefers `note_tweet.text` when present). Only module importing httpx.
- `app/x/posts.py` — `XPost` (pydantic, extra="forbid": post_id, handle,
  posted_at, text, url, fetched_at), `insert_new_posts` (INSERT OR
  IGNORE), `record_post_reads(conn, count, month=None)`,
  `unreviewed_posts(conn, limit=50)` ordered oldest-first,
  `mark_reviewed(conn, post_id, review_status)`.
- `app/x/run.py` — `_cmd_fetch(conn, resolve_ids=..., fetch_posts=...)`
  with injectable fetchers; calls `fetch_posts(account.user_id,
  account.handle, since_id)` then `insert_new_posts` +
  `record_post_reads(len(posts))`.
- `app/storage/database.py` — `connect(db_path)` runs `_SCHEMA`
  executescript (`CREATE TABLE IF NOT EXISTS` only — it will NOT add
  columns to existing tables; that's why step 1 adds a migration helper).
  `x_posts` columns today: post_id, handle, posted_at, text, url,
  fetched_at, review_status.
- `app/labeling/server.py` — FastAPI app factory `create_app`; endpoints
  `GET /`, `GET /api/next`, `POST /api/skip`, `POST /api/capture`;
  per-request sqlite connections; single HTML template string with
  vanilla JS.
- Tests: 94 passing. Gates: pytest, ruff check, ruff format --check, mypy
  strict — all must stay green.
- Conventions (`AGENTS.md`): crash early; no premature abstractions;
  "why" comments only; append-only stores; tests mirror app/.

## Scope

**In scope** (create/modify only these):

- `app/storage/database.py` (migration helper + updated x_posts DDL for
  fresh databases)
- `app/x/client.py`, `app/x/posts.py`, `app/x/run.py`
- `app/labeling/server.py`
- `tests/x/test_client.py`, `tests/x/test_posts.py`,
  `tests/labeling/test_server.py` (extend)
- `tests/storage/test_records.py` — ONLY if a migration test fits better
  there; otherwise don't touch.

**Out of scope**: full ancestor-chain walking (one parent level only);
re-fetching or backfilling context for existing rows; quote-tweet
expansion beyond what `referenced_tweets` returns; any LLM logic; any
change to signals/schemas/policy.

## Steps

### Step 1: additive migration

In `app/storage/database.py`: update the `x_posts` CREATE statement (for
fresh databases) to include two new columns, and add a migration for
existing databases:

```sql
conversation_id TEXT NOT NULL DEFAULT '',
reply_context TEXT NOT NULL DEFAULT ''
```

Migration pattern (runs inside `connect` after the executescript):

```python
def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
```

called with `{"conversation_id": "TEXT NOT NULL DEFAULT ''", "reply_context": "TEXT NOT NULL DEFAULT ''"}`.

**Verify**: create a db with the OLD schema (easiest: in a test, create a
table via the old DDL, then call `connect` on that path) and assert both
columns exist after connect; also `connect(':memory:')` then
`SELECT conversation_id, reply_context FROM x_posts` → exit 0.

### Step 2: XPost + storage

`app/x/posts.py`: add to `XPost`:

```python
    conversation_id: str = ""
    reply_context: str = ""
```

(defaults keep every existing constructor call and test valid). Extend
`insert_new_posts` INSERT to write both columns, and every SELECT that
builds XPost objects (`unreviewed_posts`, and any row→XPost mapping) to
read them.

**Verify**: `python -m pytest tests/x -q` → existing tests pass unchanged.

### Step 3: client — request and map context

`app/x/client.py`:

1. Params become:
   `tweet.fields=created_at,text,note_tweet,conversation_id,referenced_tweets`
   plus `expansions=referenced_tweets.id`.
2. Parse `includes.tweets` from the response into a dict
   `{tweet_id: text}` (prefer `note_tweet.text` for included tweets too —
   reuse the same preference logic).
3. Extend `_map_tweet(tweet, handle, fetched_at, included: dict[str, str])`:
   - `conversation_id` = `tweet.get("conversation_id", "")`.
   - If the tweet has a `referenced_tweets` entry of type `replied_to`
     whose id is in `included`, set
     `reply_context = included[parent_id]`; else `""`. (Quoted tweets:
     same treatment if type `quoted` — a quote without context has the
     identical reviewability problem; one mechanism covers both. If a
     tweet has both, prefer `replied_to`.)
4. `fetch_user_posts` returns `(posts, total_returned)` — NO. Keep the
   signature `-> list[XPost]` to avoid rippling through run.py's
   injectable seam; instead count includes by having `fetch_user_posts`
   fold them in: return the posts list, and expose the billing count as
   `len(posts) + len(includes)` via... simplest honest approach: change
   the return to a small NamedTuple `FetchResult(posts: list[XPost],
   billed_reads: int)` and update `_cmd_fetch` + its fake-fetch tests
   accordingly. This is the one deliberate interface change; keep it
   contained.

**Verify**: extend `tests/x/test_client.py` (see Test plan) →
`python -m pytest tests/x/test_client.py -q` passes.

### Step 4: fetch orchestration

`app/x/run.py` `_cmd_fetch`: adapt to `FetchResult`;
`record_post_reads(conn, result.billed_reads)`; everything else
unchanged. Update the existing since_id regression test's fake fetch to
return a `FetchResult`.

**Verify**: `python -m pytest tests/x -q` → all pass.

### Step 5: review UI — context display + same-thread consolidation

`app/labeling/server.py`:

1. `GET /api/next` currently returns the single oldest unreviewed post.
   Change: after selecting that post, also select any OTHER unreviewed
   posts with the same `handle` AND same non-empty `conversation_id`
   (ordered by posted_at). Return the anchor post plus a `thread` array
   (the additional posts' id/text/posted_at) and `reply_context`.
2. Template: when `reply_context` is non-empty, render it in a visually
   distinct quoted block labeled "in reply to" ABOVE the post text. When
   `thread` is non-empty, render the additional same-user posts below the
   anchor as one continuous thread view.
3. `POST /api/skip` and `POST /api/capture` accept an optional
   `thread_post_ids: list[str]` — skip marks ALL of them skipped;
   capture saves the signal against the anchor `post_id` and marks the
   anchor captured and the rest of the thread posts ALSO captured (they
   were reviewed as one unit; leaving them unreviewed would re-present
   them). The JS sends the thread ids it displayed.

Keep the thin-skin rule: the grouping query lives in `app/x/posts.py` as
`unreviewed_thread_posts(conn, handle, conversation_id, exclude_post_id) -> list[XPost]`,
not inline SQL in the server.

**Verify**: `python -m pytest tests/labeling -q` → passes with new tests.

### Step 6: gates + live smoke

All four gates. Then a live smoke against the REAL database is explicitly
FORBIDDEN in this worktree (never touch `data/`); instead do an offline
end-to-end: seed an in-memory db with a fake FetchResult containing a
reply + its parent in includes, run `_cmd_fetch` with the fake, assert
the stored post has `reply_context` set, then TestClient `GET /api/next`
shows it.

## Test plan (extensions)

`tests/x/test_client.py`:
1. `_map_tweet` sets `conversation_id` and picks up `reply_context` from
   the included parents dict for a `replied_to` reference.
2. A quoted (not replied_to) reference also populates `reply_context`.
3. A post with no references has empty context fields.

`tests/x/test_posts.py`:
4. Round-trip: insert an XPost with context fields, `unreviewed_posts`
   returns them intact.
5. Migration: old-schema db gains the two columns on `connect` (step 1
   verify as a real test).
6. `unreviewed_thread_posts` returns same-handle same-conversation
   unreviewed posts excluding the anchor, and nothing across different
   conversations/handles.
7. Billing: `_cmd_fetch` with a fake returning
   `FetchResult(posts=[2 posts], billed_reads=3)` records 3 reads.

`tests/labeling/test_server.py`:
8. `/api/next` includes `reply_context` and the `thread` array for
   grouped posts.
9. Skip with `thread_post_ids` marks all listed posts skipped.
10. Capture with `thread_post_ids` marks anchor + thread captured and
    stores one signal.

Verification: `python -m pytest -q` → all pass (94 + 10 = 104, or
adjusted if step edits change existing counts — report the real number).

## Done criteria

- [ ] `python -m pytest -q` exits 0; ~10 new tests
- [ ] All four gates exit 0
- [ ] Migration proven by test: old-schema db upgrades on connect, no data loss
- [ ] `grep -n "expansions" app/x/client.py` → `referenced_tweets.id` present
- [ ] Billing counts includes (test 7 passes)
- [ ] `data/` untouched (`git status --porcelain` shows nothing under data/; the dir is gitignored anyway — also confirm no code writes to a hardcoded real db path in tests)
- [ ] `git status --porcelain` clean after commits; only in-scope files changed

## STOP conditions

- Current-state signatures don't match main.
- The migration approach would require anything beyond ADD COLUMN.
- You need to change `CapturedSignal` or any schema in `app/schemas/` —
  out of scope; report.
- Any test wants to touch `data/boustrategy.db` — never; report instead.

## Maintenance notes

- One parent level is a deliberate cap; full-chain walking multiplies
  reads and is deferred until the trial shows deep threads matter.
- Backfilled rows (pre-012) have empty context; the maintainer labels
  those with a self-contained-claim convention. The relevance-gate plan
  must treat empty-context replies from before this landed as
  lower-confidence training examples.
- The `FetchResult.billed_reads` conservatism (includes counted) may
  overcount if X doesn't bill includes; if observed spend runs below
  recorded reads, that's why — adjust only with evidence from the billing
  console.
