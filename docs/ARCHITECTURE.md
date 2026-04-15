# Architecture

This document explains how the three-way match agent is built and why the structure is what it is. The audience is anyone asking the fair question: **"Would I deploy this against my AP inbox?"** The answer to that is a function of three design choices — math in Python, an always-on audit trail, and a human on every exception.

## The problem the architecture has to solve

Finance teams do not have a "we want AI" problem. They have a trust problem. An AP agent that approves ten invoices correctly and then hallucinates a $47,000 payment on the eleventh is worse than no agent at all, because the first ten build confidence and the eleventh costs the CFO's job. Any architecture worth deploying has to make the failure modes of a language model survivable.

The three that matter:

1. **Invented numbers.** The model writes a fluent sentence with a dollar amount it computed instead of fetched.
2. **Invisible reasoning.** The model blocks an invoice and no one can reconstruct why six months later when the vendor disputes it.
3. **Silent autonomy.** The model makes the final call on an edge case no one told it how to handle.

The architecture below is a direct response to each one.

## Decision 1: The math lives in Python

`src/match.py` is a pure function. It takes three Pydantic objects and returns a `MatchResult`. No LLM, no randomness, no I/O. Every discrepancy — quantity mismatch, price variance, missing goods receipt, duplicate invoice, vendor mismatch, invoiced-not-ordered — is detected by straight comparison against tolerances read from environment variables. The recommended action (`approve` / `route_for_review` / `block`) is a deterministic function of the discrepancies.

The LLM's only job is orchestration and narration. It calls `fetch_purchase_order`, `fetch_vendor_invoice`, `fetch_goods_receipt`, `check_for_duplicate_invoices`, and `run_three_way_match`. The system prompt says it explicitly: *"Do not compute totals, quantities, or variances yourself. The run_three_way_match tool is the only source of the recommended action and the dollar amounts. Never override it."*

The payoff: the model cannot hallucinate a dollar amount, because it never does arithmetic. The amounts it narrates are the amounts the tool returned. If the Odoo client is correct and the match function is tested, the agent's statement about money is true by construction.

A concrete example. In the over-invoiced scenario (seed scenario 3), the vendor billed 12 units at $100 each against a PO for 10 units. The model's narration sounds like this: *"Blocking invoice BILL/2026/0003 for $1,200. The vendor billed 12 units of WIDGET-A but the goods receipt shows 10 received. Delta of +2 units, outside tolerance. Route to AP lead."* Every number in that sentence — $1,200, 12, 10, +2 — came from the `MatchResult` object the tool returned. The model composed English around structured data. It did not add anything up.

## Decision 2: Every check is recorded

`MatchResult.audit_trail` is an ordered list of strings. It starts with the invoice-to-PO reference check, records each SKU compared with the quantities and prices on all three documents, and ends with the final action. It is produced by the same deterministic function that produced the decision, which means the audit trail and the decision can never disagree.

When an auditor or a vendor disputes a block six months later, the answer is not "the model said so." The answer is a timestamped record of the specific tolerances the invoice failed and the specific quantities that triggered the flag. The evidence dictionary on each `Discrepancy` carries the raw numbers. The rationale string carries the plain-English summary. Together they replace the clerk's initial and date with something a court could read.

This is also how the agent survives silent drift. If tolerances change — say the CFO loosens price variance from 2% to 5% — the audit trail records the tolerance that was in effect when the decision was made. Old decisions remain explainable under the rules that were live when they were made.

## Decision 3: The agent recommends. A human decides.

The system has three actions and only three: approve, route for review, block. None of them move money. Approval means "this invoice is safe for the AP lead to post." Routing means "a human needs to look at this." Blocking means "do not post until this is resolved." Nothing about the architecture writes a payment, releases a hold, or talks to the bank.

This is not a limitation waiting to be removed. It is the control. Every finance team that has ever trusted an autonomous system has eventually regretted the case the system handled without asking. The structure here — agent proposes, human disposes — is how AP departments stay out of trouble. The speed comes from the agent clearing the obvious cases fast enough that the humans have time to handle the exceptions well, not from the agent replacing the humans.

The product boundary is also the consulting boundary. Clients will ask *"can it just auto-approve the clean ones?"* The right answer is "yes, once you've watched it run for a month and you've tuned your tolerances to your data." Automation earned over time beats automation assumed on day one.

## How the pieces fit together

```
                    ┌────────────────────────────────────┐
                    │           run_agent CLI            │
                    │  python -m scripts.run_agent BILL..│
                    └──────────────────┬─────────────────┘
                                       │
                                       ▼
                    ┌────────────────────────────────────┐
                    │         agent.py (Claude)          │
                    │   orchestrates tool calls, narrates│
                    │   output. Never computes amounts.  │
                    └──────────────────┬─────────────────┘
                                       │ tool use
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
     ┌─────────────────────┐  ┌──────────────────┐  ┌────────────────────┐
     │  odoo_client.py     │  │   match.py       │  │   models.py        │
     │  XML-RPC to Odoo.   │  │   Deterministic  │  │   Pydantic models  │
     │  Maps native fields │  │   matcher. Pure  │  │   (ERP-neutral).   │
     │  onto neutral shape │  │   function.      │  │                    │
     └─────────────────────┘  └──────────────────┘  └────────────────────┘
```

`models.py` is deliberately ERP-neutral. The Odoo client is the only file that speaks in `purchase.order`, `stock.picking`, and `account.move`. A NetSuite client or a Dynamics 365 client would implement the same three `get_*` methods and the rest of the stack would not notice. This is the shape that scales to a consulting practice: you rewrite one file per ERP, not the whole agent.

## What the agent cannot do, and why that's the point

The agent cannot:
- Post a journal entry
- Release or approve a payment
- Modify a PO, receipt, or invoice in Odoo
- Decide a tolerance change

The agent can:
- Read the three documents
- Run the match
- Narrate the result to a clerk
- Log the audit trail

If the scope of "can" feels small, that's the correct reaction. The scope is the product. Expanding it is a decision the client's CFO makes after watching the agent run on real invoices for long enough to trust what it handles and what it escalates. The Phase 2 artifact will propose the first safe expansion — most likely GL coding on approved invoices, where the model suggests a code and a human accepts or overrides it.

## Tolerance tuning

The four knobs live in `.env`:

- `PRICE_VARIANCE_TOLERANCE_USD` — absolute price delta tolerated before a `PRICE_VARIANCE` flag
- `PRICE_VARIANCE_TOLERANCE_PCT` — percentage price delta tolerated (both USD and PCT must be exceeded to flag)
- `QUANTITY_VARIANCE_TOLERANCE` — unit delta tolerated between invoiced and received quantity

Defaults are conservative: $5 or 2% on price, zero units on quantity. The defaults should surface more flags than any real AP team wants in production — that is intentional. A new deployment should run for two weeks with the defaults, review what routed for review, and raise the tolerances to match the actual error profile in the vendor base. Owned by the controller, not by the engineer.

## What to look at first when something breaks

- **Odoo field mapping off.** Every seed scenario surfaces a realistic bug. If the agent says "PO not found" on a PO that exists in the UI, the first place to look is `odoo_client.py` — Odoo has renamed fields between major versions and the XML-RPC mapping may need a tweak.
- **Tool-use loop stalls.** Bump `max_turns` in `agent.py` or tighten the error messages returned by `ToolDispatcher` so the model has something to react to.
- **False positive blocks.** The matcher may be right and the tolerance may be wrong. Check the audit trail for the specific delta that triggered the flag, then raise the tolerance in `.env`.
- **False negative approves.** Write a new test case in `tests/test_match.py` with the exact scenario that slipped through. The test will fail. Fix the matcher. The test will pass. Ship.

That last pattern — surface a miss, write the test, fix the code — is how the match logic earns its way to fewer false approvals over time. The Python matcher is the only place that behavior can be pinned down. A model can learn to narrate better; only code can learn to be correct.
