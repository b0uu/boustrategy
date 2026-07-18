# Sunday X weekly runbook

Run these steps in order.

1. Run `python -m app.x.run cycle --slot weekly`.
2. Author the weekly synthesis, store it with `python -m app.x.run note
   --date <today> --slot weekly --author <session-name> --in <file>`, then run
   `python -m app.x.run weekly-render --date <today>`. Cover narrative deltas
   across the week: what strengthened and what broke; a per-theme rollup of
   headline and notable items; unresolved article-queue entries worth human
   attention; observations from the per-account table about audition
   candidates moving up or down; open research questions; and Monday watch
   items. Roster observations are advisory only—curation is human-only. State
   the next market session explicitly when Monday is a holiday.
3. Until the reasoning worker exists, the thesis-review section is the
   literal line: "No active theses — reasoning worker not yet live." Never
   draft theses here.
4. Seal the weekly capsule locally by copying the database to
   `data/backups/boustrategy-<date>.db`, which is gitignored. Record that
   backup filename as the final line of the weekly synthesis note. Do not
   create a git commit; the public repository must never contain `data/`.
5. Run `python -m app.newsletters.run list` for documents ingested this week.
   In the weekly synthesis, add `New internal reference` with source and title
   only—never newsletter content. Flag every `unparsed` document to the
   maintainer for conversion. Do not annotate newsletters in this session.
