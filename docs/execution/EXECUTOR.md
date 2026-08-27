# Execution-only Robinhood runbook

This worker executes one already-approved live order intent. It does not research investments,
change a thesis, choose a ticker, resize an order, create a decision record, or consume triggers.
It must be connected only to the Robinhood Agentic account assigned to its execution profile.

Live placement remains disabled unless all of these inputs already exist:

- one schema-valid, policy-approved `LIVE` order intent with an `execution_profile_id`;
- an enabled matching profile from the gitignored `ops/live.local.json`;
- a fresh broker preflight containing the matching account fingerprint, account equity, buying
  power, current position value, bid, ask, quote time, tradability, fractional eligibility, and
  regular-market-hours state;
- one unexpired `LiveExecutionPacket` persisted by `python -m app.broker.run packet`.

For one packet, follow this order:

1. Confirm the packet's `agent_provider` matches this worker and its account alias identifies the
   dedicated Robinhood Agentic account connected to this worker. Stop on any mismatch.
2. Confirm the packet has not expired. Never place from an expired packet. Refresh broker state
   and build a new packet instead.
3. Use Robinhood's account, position, quote, and tradability tools to verify that the packet still
   matches current broker state. Stop if the account fingerprint, ticker, side, notional, limit
   price, buying power, fractional eligibility, or regular-hours state differs.
4. Call Robinhood's equity order-review tool using exactly the packet fields. Never increase size,
   change side, change ticker, change order type, or substitute an account.
5. If broker review returns an error, warning that changes the economics, or fields that don't
   exactly match the packet, record `FAILED` and stop. Otherwise append the `REVIEWED` event.
6. If the packet says `require_human_approval=true`, stop for approval. Otherwise place the exact
   reviewed order once.
7. If placement returns an ambiguous error or times out, query Robinhood order history before any
   retry. Never retry placement until absence of the order is established.
8. Persist the `SUBMITTED` broker execution record and append the `SUBMITTED` lifecycle event
   through `python -m app.broker.run`. Both records must name the exact packet reviewed and placed.
   Never edit SQLite directly.
9. Reconcile Robinhood order status until it reaches `FILLED`, `PARTIALLY_FILLED`, `CANCELED`, or
   `FAILED`. Append each distinct broker update with its actual timestamp.

The execution worker must not continue into another packet automatically. One fresh execution-only
session handles one packet. Options, crypto, margin, shorts, market orders, extended-hours orders,
transfers, and orders outside the packet are out of scope.
