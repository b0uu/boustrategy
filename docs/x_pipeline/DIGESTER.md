# Intraday X digester runbook

Run these steps in order for the schedule slot that launched this session.

1. Run `python -m app.x.run usage-sync`, then run
   `python -m app.x.run cycle --slot <slot>`. If the cycle prints a calendar
   no-op, stop; the session is done. If it reports the run is stuck with
   status `exported`, an earlier session already exported the posts; continue
   with step 2 on that run.
2. Run `python -m app.x.run media --run <run_id>` to download every image
   attachment into the run's `media/` folder. It prints downloaded, cached and
   failed counts and leaves a `.failed` marker next to any URL it couldn't
   fetch. Never download media with curl or Invoke-WebRequest; they have no
   TLS credentials inside the sandbox. Then open the run export directory,
   read every `batch_*.jsonl`, view the downloaded files for posts that carry
   media, judge every record using `docs/x_pipeline/RUBRIC.md`, and write
   `predictions.jsonl` alongside the batches.
3. Run `python -m app.x.run route --run <run_id> --predictor <session-name>
   --in <predictions.jsonl>`. The session name should encode model and rubric
   version, such as `luna-rubric2`.
4. Write a small synthesis file of 3–8 sentences. State what changed since
   the last run, which theses or themes the headlines touch, contradictions
   between sources, and what the article queue still hides. Use plain claims
   with handles and no hype. Store it with `python -m app.x.run note --date
   <today> --slot <slot> --author <session-name> --in <file>`, then run
   `python -m app.x.run digest-render --date <today>`.
5. For the close run only, read the entire rendered daily digest once for
   coherence. Refine the same-slot note and re-render if anything reads wrong.
6. Put an escalation on the FIRST line of the synthesis note, and never act
   on it: fetch failures; a tripped budget guard as `BUDGET` plus remaining
   reads; or any run exporting more than 150 posts.

## Hard prohibitions

- NEVER launch, or continue into, a reasoning/thesis/decision session.
  The ACTIONABLE marker is a flag for a different worker behind human
  checkpoint 5. This is a structural rule, not a judgment call.
- NEVER write `x_posts.review_status`, edit the roster/`x_accounts`, or
  edit anything under `docs/` except nothing — this runbook grants zero
  doc edits.
- NEVER exceed the budget guard by fetching manually.
- NEVER run `git add`/`git commit` on anything under `data/`, and never
  force-add past `.gitignore`. The repo is PUBLIC; X post content never
  enters git (private-archive doctrine). The database is the capsule —
  your synthesis is already durable via `note`.
