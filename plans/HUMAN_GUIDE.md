# Human Guide to the Audit and Plans

This file is for you, not for an AI executor. It explains what the audit
found, what each plan changes, where your judgment is genuinely needed, and
the technical concepts behind it all in plain language. Edit it freely. The
numbered plan files (001 to 004) are precise instructions for an AI to
execute; this file is the map.

---

## The one thing to do before anything else

**Your code is not saved in git yet.** Run `git status` and you will see
`app/`, `tests/`, and `pyproject.toml` listed under "untracked files". Git
only protects files you have committed. Right now, if this folder were lost,
your spec would survive (it is committed) but your entire implementation
would not. It also means there is no history: you cannot see what changed,
when, or roll anything back.

Fix is one step:

```
git add .gitignore pyproject.toml app/ tests/
git commit -m "schema and policy baseline"
```

(You may also want to add `plans/` and `skills-lock.json` in the same or a
separate commit, your call.)

---

## The big picture of what was found

Your architecture has a deliberate safety pipeline, and it is a good one:

```
AI reasoning -> Decision Record -> Schema check -> Policy check -> (someday) Order
```

The audit found that both checking layers have **holes in their fences**.
Each hole is small, but this pipeline is the thing standing between an LLM
and your real money, so the fences should be airtight before anything else
gets built on top.

The findings group into three stories:

### Story 1: The schema gate accepts some garbage (Plan 001)

The schema layer is your "is this even a well-formed record?" check. It
currently accepts:

- A ticker made of only spaces, which silently becomes an **empty ticker**.
- Timestamps with no timezone (more on why that matters in the glossary).
- Any random string as a source type, like `"some blog"`, even though your
  spec defines an exact list (SEC, COMPANY_IR, NEWS, X, ...).
- Contradictory X-usage states, like "X was not used" combined with
  "X was the idea source".

None of these can hurt you today because nothing trades yet. But every one
of them is a malformed audit record waiting to happen, and your whole project
thesis is that the audit trail is trustworthy.

### Story 2: The policy gate has scope bugs (Plans 002 and 003)

The policy layer is your rulebook: "this record is well-formed, but is it
*allowed*?" Three rules are mis-scoped:

1. **ADD sneaks past the risk gates.** Your rules block BUY in a RED regime
   and BUY in de-risking mode. But ADD (buying more of something you already
   own) is not blocked. ADD puts new money at risk exactly like BUY does.
   I verified this: an ADD in RED regime, in DE_RISKING mode, is approved
   today. *This one needs your judgment; see the decision points below.*

2. **The weight caps punish winners.** The 20% stock cap applies to every
   decision type. So if NVDA runs up and becomes 25% of your portfolio just
   by appreciating, the policy engine **rejects your HOLD decision**. It
   would even reject a TRIM from 30% down to 25%. The fix: caps only apply
   when you are putting money in (BUY/ADD), not when holding or reducing.

3. **The X rule is too aggressive.** Your written rule is "reject an X-only
   thesis without outside confirmation". Sensible. But the code rejects ANY
   record where X was involved and unconfirmed, including a PASS (where you
   decided to do nothing!) and cases where X argued *against* the trade
   (counter-thesis). A skeptic on X warning you off a trade does not need
   outside confirmation to be safe input.

Plan 003 adds the rules you wrote down but never built: max 2 trades per
day, max 6 holdings. They were unbuildable before because the policy
function only sees one decision at a time; it has no idea how many trades
happened today. Plan 003 gives it a small "portfolio context" input
carrying that information.

### Story 3: The project has no guardrails for its own development (Plan 004)

Right now the only automated check is the test suite. Plan 004 adds two
standard tools (explained in the glossary) that catch mistakes before tests
even run, and creates a root `AGENTS.md` file. That last one matters more
than it sounds: your coding conventions currently live in
`scratchpad/AGENTS.md`, but `scratchpad/` is in `.gitignore`, so **no AI
agent or collaborator working from a fresh copy of this repo can see your
conventions**. The plan publishes them properly.

---

## Decision points that need YOUR judgment

These are places where I made a call you can overrule. Overruling is cheap
before the plans run; just edit the plan file or tell the next agent.

### 1. Should ADD be blocked in RED regime? (Plan 002)

Your doc literally says "reject BUY in RED", nothing about ADD. I read your
spec's *intent* (RED means de-risk, target exposure 0-20%) as "no new money
into high-beta, period", so the plan blocks both.

The counterargument you might hold: averaging into a high-conviction position
during a RED panic is exactly the kind of bold move your framework celebrates
(SB-007: losses do not automatically invalidate a thesis). If that is your
vision, ADD in RED should maybe be allowed but require extraordinary
evidence, rather than be banned.

**Default in the plan: block ADD in RED and in DE_RISKING.** Edit plan 002
step 1 if you disagree.

### 2. Should TRIM and SELL count against the 2-trades-per-day limit? (Plan 003)

The spec says "max executed trades/day: 2" with no exemption. The plan counts
every executed trade (BUY/ADD/TRIM/SELL). But you could argue de-risking
trades should never be blocked by a quota, because blocking a SELL during a
bad day is the opposite of risk control.

**Default in the plan: all four count.** If you want SELL/TRIM exempt, edit
plan 003 step 2 and its tests.

### 3. Max holdings is set to 6 (Plan 003)

Your spec says "3-6 holdings". A hard rule needs one number, so the plan
uses 6 as the ceiling (a 7th position gets rejected). The 3 is treated as a
goal, not a rule. Change `MAX_HOLDINGS` if you want it tighter.

### 4. Theme concentration limit: deliberately NOT built

Your policy doc mentions rejecting "theme concentration" but no number exists
anywhere in your spec. That number is a strategy decision (how much of the
portfolio can be `ai_semiconductors` before it is reckless?). I refused to
invent it. When you pick a number, it slots into the `PortfolioContext`
seam that plan 003 creates.

### 5. The ticker format (Plan 001)

The plan enforces tickers like `NVDA`, `BRK.B`, `BF-B`: letters first, up to
12 characters, US-listing shaped. If you ever want non-US listings, this
rule is the thing to revisit.

---

## What was deliberately NOT planned (and why)

- **Writing your mandate/risk/source policy docs** (`docs/mandate.md` etc.
  are empty files): your own spec says "human strategy is the edge". An AI
  drafting your mandate would be exactly the consensus-flavored slop your
  project exists to avoid. These are yours to write.
- **The sizing-adjustment feature** (policy reducing a target weight instead
  of rejecting): it needs inputs that do not exist yet, like thesis-quality
  scores and liquidity data. The dead placeholder field for it gets removed
  in plan 003; it comes back when the feature is real.

## What to build NEXT, after these plans (your pick)

These came out of the audit as the highest-value next moves, in my suggested
order, but this is vision territory and the call is yours:

1. **Order Intent schema + the approval pipeline.** Your core safety
   principle is "no direct LLM-to-order path". The decision record already
   has an `order_intent_id` field pointing at... nothing. Building the
   Order Intent object and the rule "an intent can only be created from an
   approved decision" turns your safety principle from prose into code.
2. **Saving records to disk/database with idempotency.** Right now records
   only exist in memory during tests. Idempotency (glossary below) is what
   prevents the nightmare scenario: a crash mid-workflow, a restart, and the
   same order placed twice.
3. **The daily price cache** (spec section 6 already names the source:
   yfinance, daily OHLCV). This unblocks regime scoring and the dashboard.

A reasonable instinct is to jump to the fun part (the reasoning agent, the
dashboard). The boring order here is deliberate: every layer of deterministic
safety you finish first makes the fun part safer to turn loose.

---

## How to work with the plan files

- Each plan (001 to 004) is written so an AI agent with zero context can
  execute it: exact files, exact steps, a verification command after every
  step, and STOP conditions so it reports back instead of improvising.
- **You can edit them.** They are markdown, not magic. If a decision point
  above changes your mind, edit the relevant step before execution.
- Run them via something like: "execute plans/001-tighten-decision-record-schema.md"
  in a Claude Code session. Recommended order: 001, 002, 003, 004 (002 must
  come before 003; 004 can happen anytime).
- After each plan runs, the status table in `plans/README.md` should be
  updated by whoever ran it. Glance at it to see where things stand.
- Review the diff after each execution like you would review a human's PR.
  The plans constrain the AI hard, but you are the final gate.

---

## Glossary: the technical concepts, simply

**Schema vs. policy (your two-layer design).** The schema layer asks "is
this record shaped correctly?" like a bouncer checking that an ID is a real
ID. The policy layer asks "is this allowed?" like the bouncer then checking
the age on it. Keeping them separate means each stays simple and testable.

**Pydantic.** The Python library your schemas are built on. You declare what
a record should look like (fields, types, allowed values) and pydantic
rejects anything that does not match. Your `InvestmentDecisionRecord` class
is a pydantic model.

**The whitespace-ticker bug, mechanically.** Pydantic runs its built-in
checks (like "minimum length 1") on the *raw input*, and only afterwards
runs your custom cleanup code (strip spaces, uppercase). So `"   "` passes
the length check (3 characters!), then your cleanup turns it into `""`,
empty, and nothing re-checks it. The fix moves the "must not be empty" check
to after the cleanup.

**Timezone-aware vs. naive datetimes.** A naive timestamp says "June 10,
14:30" with no timezone. 14:30 *where*? In an audit trail for trading (where
market open/close in US Eastern time is everything), ambiguous timestamps
are landmines. "Aware" timestamps carry the timezone, so `14:30 UTC` is one
exact moment forever. The fix forces every timestamp to be aware.

**Enum.** A field that only accepts values from a fixed list. Your
`Decision` enum accepts BUY/ADD/TRIM/SELL/HOLD/PASS/WATCHLIST and nothing
else. Plan 001 turns `source_type` from "any string" into an enum matching
your spec's list.

**Idempotency.** An operation is idempotent if doing it twice has the same
effect as doing it once. Crucial for trading systems: if the system crashes
after sending an order but before recording it, the restart logic must
recognize "this order already went out" instead of sending it again. Stable
IDs (`decision_id`, `order_intent_id`) are what make that recognition
possible.

**Linter (ruff).** A tool that reads your code without running it and flags
mistakes and style drift: unused imports, suspicious patterns, messy
formatting. Like spellcheck for code. Runs in milliseconds.

**Type checker (mypy).** Python normally only discovers type mistakes when
the broken line actually runs. A type checker proves things ahead of time,
like "this function returns a PolicyResult, and everyone using it treats it
as one". Since your code is built on pydantic models with declared types,
mypy catches a whole class of AI-coding mistakes for free.

**Dead field.** `adjusted_final_target_weight` exists on `PolicyResult` but
no code ever sets it, so it is always `None`. Dangerous because a future
caller might read it believing it is computed. Rule of thumb: interface
surface should not promise what the code does not deliver.

**Worktree / drift check.** When an AI executor runs a plan, it may work in
a separate copy of the repo (a worktree) and first checks whether the code
still matches what the plan was written against (drift). This is why
committing your code to git matters: both mechanisms rely on git knowing
about your files.

---

*Generated alongside the 2026-06-12 audit. Iterate on it; it is yours.*
