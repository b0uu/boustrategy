# Plan 014: Backfill re-hydration — enrich pre-012/013 posts with context and media by ID lookup

> Executor instructions: follow exactly; verify each step; STOP on mismatch.
> Branch `advisor/014-backfill-rehydration`, do NOT push, don't touch
> plans/README.md. Never touch any real database path — in-memory/tmp only.

## Status

- Priority P1 (live trial; the maintainer is labeling a context-poor backlog)
- Effort: S-M. Depends on 012, 013 (landed on local main). Planned at local main `410aeed`, 2026-07-14.

## Why this matters

1,348 unreviewed backfill posts predate thread-context (012) and media
capture (013): their `conversation_id`, `reply_context`, and `media_json`
are empty even where the original post has a parent or images. Labeling
them context-blind either mislabels posts or wastes maintainer time on
click-throughs. X's tweet lookup (`GET /2/tweets?ids=...`, ≤100 per
request) returns posts by ID with the full modern field set, so the
enrichment columns can be back-filled for ~$7 of read budget. The command
only runs when the maintainer invokes it — build ≠ spend.

**Hard rules**: only rows with `review_status = 'unreviewed'` may be
updated (enforced in the SQL WHERE, not just the caller) — reviewed rows
keep their label/input pairing frozen. Only the three enrichment columns
are written; `text`, `posted_at`, `handle`, `url`, `review_status` are
never modified. Budget guard before every batch.

## Current state (local main `410aeed`)

- `app/x/client.py`: `_map_tweet(tweet, handle, fetched_at, included, media_included)` builds XPost incl. conversation_id/reply_context/media; `_map_media` parses `includes.media`; `fetch_user_posts` uses params `tweet.fields=created_at,text,note_tweet,conversation_id,referenced_tweets,attachments`, `expansions=referenced_tweets.id,attachments.media_keys`, `media.fields=...`; returns `FetchResult(posts, billed_reads)`; billed_reads counts data + includes.tweets (not media). Bearer token via env, raises if unset. Only httpx importer.
- `app/x/posts.py`: `XPost` (with media: list[MediaItem]), `reads_remaining`, `record_post_reads`, `MAX_MONTHLY_POST_READS = 4000`, `mark_reviewed` (statuses captured|skipped|significant).
- `app/x/run.py`: argparse CLI `seed|fetch|review|status`; `_cmd_fetch` has budget-guard pattern (`reads_remaining(conn) <= _BUDGET_FLOOR: stop`); `_BUDGET_FLOOR = 100`.
- Tests: 119 passing; gates: pytest, ruff check, ruff format --check, mypy strict.

## Scope

IN: `app/x/client.py`, `app/x/posts.py`, `app/x/run.py`, `tests/x/test_client.py`, `tests/x/test_posts.py`.
OUT: labeling server; storage schema (no migration needed — columns exist); signals; anything else.

## Steps

1. **client**: add `fetch_posts_by_ids(post_ids: list[str]) -> FetchResult` —
   GET `{BASE}/tweets` with `ids=` (comma-joined, caller passes ≤100) and the
   SAME tweet.fields/expansions/media.fields params as `fetch_user_posts`
   (factor the params dict into a module constant to avoid divergence).
   Map via existing `_map_tweet`; handle comes from the tweet's own data?
   No — the lookup response has `author_id`, not handle, and `_map_tweet`
   takes handle as a parameter. For re-hydration the handle is irrelevant
   (only enrichment columns get written back), so pass a placeholder
   handle explicitly (e.g. `"__rehydrate__"`) with a one-line why-comment.
   Missing/deleted ids appear in the response `errors` array — return
   count of missing via the existing FetchResult? Do not change
   FetchResult; instead have the function return `FetchResult` and let
   missing simply be absent from posts (the CLI reports the difference).
   billed_reads = len(data) + len(includes.tweets), same as fetch.
2. **posts**: add `update_post_enrichment(conn, post: XPost) -> bool` —
   `UPDATE x_posts SET conversation_id=?, reply_context=?, media_json=?
   WHERE post_id=? AND review_status='unreviewed'`; returns rowcount > 0;
   commits.
3. **run**: add `rehydrate` command: select post_ids
   `WHERE review_status='unreviewed' AND conversation_id=''` (the pre-012
   era marker) oldest-first; process in batches of 100; before each batch
   require `reads_remaining(conn) > len(batch) + _BUDGET_FLOOR` else print
   budget state and stop cleanly; call injectable
   `fetch_by_ids=fetch_posts_by_ids`; `record_post_reads(billed_reads)`;
   `update_post_enrichment` per returned post; print per-batch progress
   and final summary: updated / missing (requested minus returned) /
   reads used / remaining.
4. **tests** (fakes only, no network): (a) `fetch_posts_by_ids` param
   construction + mapping via a fake payload with parent include and
   media (test the pure parts; if the httpx call is inline, factor the
   response-parsing into a testable helper); (b) `update_post_enrichment`
   updates an unreviewed row and returns True; returns False and changes
   NOTHING for a row with review_status='significant' (assert columns
   unchanged); (c) `rehydrate` with a fake fetch: only empty-conversation
   unreviewed ids requested, enrichment written, reads recorded, and it
   stops before fetching when budget is exhausted (fake not called).
5. Gates: pytest -q (report count, ~119+5), ruff check, ruff format
   --check, mypy app tests → all exit 0. `git status --porcelain` clean.

## STOP conditions

- Current-state signatures don't match local main `410aeed`.
- You find yourself modifying text/posted_at/review_status or touching
  reviewed rows — the enrichment-only rule is the design.
- FetchResult would need a schema change — report instead.

## Maintenance notes

- Missing ids (deleted posts) are themselves signal — the account
  scrutiny ledger's deletion tracking can consume the rehydrate summary
  later; v1 just prints counts.
- After the maintainer runs `rehydrate` once, the labeling UI shows
  context/media for the whole backlog; a second run is a cheap no-op
  (selector finds only still-empty rows, minus 24h-dedup billing nuance).
