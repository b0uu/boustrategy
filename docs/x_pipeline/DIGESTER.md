# Intraday X digester runbook

Run these steps in order for the schedule slot that launched this session.

1. Run `python -m app.x.run cycle --slot <slot>`. If it prints a calendar
   no-op, stop; the session is done.
2. Open the run export directory, read every `batch_*.jsonl`, judge every
   record using `docs/x_pipeline/RUBRIC.md`, and write `predictions.jsonl`
   alongside the batches.
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
