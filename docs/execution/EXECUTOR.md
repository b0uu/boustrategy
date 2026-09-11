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

For the initial live trial, use a 60-second maximum quote age. Discard an expired packet and
rebuild it from a new broker preflight quote. Never extend an existing packet's expiry.

For one packet, follow this order:

1. Confirm the packet's `agent_provider` matches this worker and its account alias identifies the
   dedicated Robinhood Agentic account connected to this worker. The broker grant may expose
   several accounts, including personal ones; compute the SHA-256 fingerprint of each candidate
   account identifier and use only the account whose first 16 hex characters equal the packet's
   `broker_account_fingerprint`. Stop on any mismatch.
2. Confirm the packet has not expired. Never place from an expired packet. Refresh broker state
   and build a new packet instead.
3. Use Robinhood's account, position, quote, and tradability tools to verify that the packet still
   matches current broker state. Stop if the account fingerprint, ticker, side, notional, buying
   power, fractional eligibility, or regular-hours state differs, or if the market has moved
   against the packet: on a BUY the current ask is above the packet's `limit_price`, on a SELL the
   current bid is below it. That last case is a normal, labeled stop: outcome `blocked` with
   `reason_code` `price_above_allowed_range` (`price_below_allowed_range` on a SELL). A quote that
   moved in the order's favor is not a mismatch. Keep the packet's `limit_price` exactly; never
   re-price the order.
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
session handles one packet. Options, crypto, margin, shorts, extended-hours orders, transfers, and
orders outside the packet are out of scope. Market orders are used only for fractional shares, as
the review step below describes, and only inside the packet's allowed price.

## Tool and record mapping

The unattended executor session runs from the repository root with the Robinhood MCP server
connected. Use these exact mappings; the trusted CLI rejects anything that doesn't fit.

- **Account selection.** Call `get_accounts`, then for each account number run
  `python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].strip().encode()).hexdigest()[:16])" <number>`
  and use only the account whose result equals the packet's or intent's fingerprint. Never print a
  full account number.
- **Preflight.** `get_equity_quotes` for bid, ask and the broker quote timestamp;
  `get_equity_tradability` for tradable and fractional eligibility; `get_portfolio` for
  `account_equity` (total value including cash) and `buying_power`; `get_equity_positions` for
  `current_position_value` in the ticker (0 if none). Write `data/broker/preflight_<intent>.json`:
  `{"execution_profile_id","broker_account_fingerprint","account_equity","buying_power","ticker",
  "current_position_value","bid","ask","quote_at","tradable","fractionable","regular_market_hours"}`
  with `quote_at` as an ISO 8601 timestamp carrying a timezone offset.
- **Packet.** `python -m app.broker.run packet --intent-id <intent> --preflight <file>` prints the
  packet with `execution_packet_id`, `notional`, `limit_price` and `expires_at`. The packet's
  `limit_price` is the allowed price: 1% from the price the review recorded (`reference_price`),
  never past the decision's entry bound. When the packet is refused, the command exits 2 and
  prints `{"blocked": true, "reason_codes": [...], "ask", "bid", "allowed_price", ...}`. If the
  only code is `stale_quote`, refresh the preflight and rebuild, at most three times. Otherwise end
  the session with outcome `blocked` and `reason_code` set to the first code printed
  (`price_above_allowed_range`, `price_above_entry_band`, `outside_regular_market_hours`,
  `spread_too_wide`, `insufficient_buying_power`, ...), and put the ask and allowed price in
  notes. A price outside the allowed range or entry band is a normal outcome, not a fault: the
  market has left the level the thesis was priced at. Never widen a band, re-quote to chase one,
  or place around it.
- **Review.** Robinhood places fractional shares only as a market order sized by
  `dollar_amount`; it rejects fractional `quantity` on limit orders at placement. So when
  `notional / limit_price` is less than one whole share, review a `type` `market` order with
  `dollar_amount` equal to `notional`, good-for-day, regular hours only. The packet's
  `limit_price` is then the price guard, not a broker field: re-read the quote immediately before
  review and again before placement, and stop with outcome `blocked` and `reason_code`
  `price_above_allowed_range` if a BUY's ask is above `limit_price` (`price_below_allowed_range`
  if a SELL's bid is below it). When the order is one whole share or more, review a
  `type` `limit` order at exactly `limit_price` with `quantity` equal to `notional / limit_price`
  rounded down to whole shares. An estimated cost at or slightly below `notional` is not a change
  in economics. If the response changes the symbol, side, type, amount or quantity, time in
  force or market hours, or warns, record a `FAILED` event and stop with outcome
  `review_rejected`.
- **REVIEWED event.** `python -m app.broker.run event --in <file>` with
  `{"broker_event_id":"bev_<packet>_reviewed","broker_execution_record_id":"ber_<packet>",
  "order_intent_id","execution_packet_id","execution_profile_id","status":"REVIEWED",
  "occurred_at":<now>,"detail":<review summary>}`. It must be recorded before `expires_at`.
- **Place once.** `place_equity_order` with the identical reviewed fields, after the final quote
  check above, plus `ref_id` set to the UUID derived from the packet, which Robinhood requires
  in UUID form: `python -c "import uuid,sys; print(uuid.uuid5(uuid.NAMESPACE_URL, sys.argv[1]))" <execution_packet_id>`.
  The same packet always yields the same UUID, so the broker still deduplicates a repeat. Never call it twice for one packet. On an ambiguous error or timeout,
  call `get_equity_orders` for the account and look for that order before deciding anything.
- **Record.** `python -m app.broker.run record --in <file>` with
  `{"broker_execution_record_id":"ber_<packet>","order_intent_id","execution_packet_id",
  "execution_profile_id","account_alias","ticker","side","order_type":"LIMIT",
  "requested_notional":<packet notional, not quantity times price>,"limit_price":<limit>,"submitted_at":<now>,
  "status":"SUBMITTED","broker_order_id":<broker id>,"execution_price":0}`, then append the
  `SUBMITTED` event (`bev_<packet>_submitted`).
- **Reconcile.** Poll `get_equity_orders` by order id about every 20 seconds for up to five
  minutes. Append `FILLED` (detail `execution_price=<average>`), `PARTIALLY_FILLED`, `CANCELED`
  or `FAILED` events (`bev_<packet>_<status>`) with the broker's timestamps. An order still open
  after five minutes stays `SUBMITTED`; report outcome `submitted`.
- **Report.** Finish with the JSON object the session schema requires: the intent id, the
  outcome, the packet id, the record id, the broker order id, `reason_code` and short notes.
  Every `blocked` outcome must carry a `reason_code` from the schema's list; a block without one
  is flagged to the operator as a problem.
