# Three-Way Match Agent

An AI agent that reads a vendor invoice, the purchase order it claims to be against, and the goods receipt that proves the goods arrived — and tells an AP clerk whether to pay it, hold it, or block it. Runs against a real Odoo instance in Docker.

## Why this workflow

Three-way match is the control every mid-market finance team says they do and half of them do partially. A purchase order, a goods receipt, and a vendor invoice all have to agree on who, what, how many, and how much before money leaves the company. When a team does it by hand, the same clerk checks thousands of invoices a month, misses the small variances because the small variances look like the big ones, and leaves an audit trail that says "approved by J. Smith" with no supporting evidence.

An agent fits this job because the work is structured, the rules are already written, and the hard part is judgment at the margin — not reading the documents. The agent does the reading and the arithmetic. A human still owns the exceptions.

## What this repo does

Point the agent at a vendor invoice number. It will:

1. Pull the invoice from Odoo
2. Pull the purchase order the invoice references
3. Pull the goods receipt tied to that PO
4. Check the vendor's other invoices for a duplicate
5. Run a deterministic match that flags discrepancies across vendor, quantity, unit price, and totals
6. Recommend one of three actions — **approve**, **route for review**, or **block** — with a plain-English rationale and a full audit trail

The agent narrates. The code decides. The model never computes a dollar amount or decides the final action — that's the only way to make an AP agent that a finance team will trust.

## Watch it run

A four-minute Loom walkthrough is linked at the top of this repo. The video shows the agent on all five seeded scenarios, including the three it's supposed to block.

## Run it yourself

Everything ships in Docker. One command stands up Odoo and Postgres; one command seeds the test data; one command runs the agent.

```bash
# 1. Clone and configure
git clone https://github.com/<your-handle>/phase1-three-way-match.git
cd phase1-three-way-match
cp .env.example .env
# edit .env — add your ANTHROPIC_API_KEY

# 2. Stand up Odoo
docker compose up -d
# Wait ~60 seconds for Odoo to initialize the database on first run.
# Odoo UI: http://localhost:8069 (admin / admin)

# 3. Install Python deps and seed test scenarios
pip install -r requirements.txt
python scripts/seed_odoo.py

# 4. Run the agent on one of the seeded invoices
python -m scripts.run_agent BILL/2026/0001
```

## The five seeded scenarios

The seed script drops five PO/GR/Invoice triples into Odoo so you can watch the agent succeed and fail on purpose. Each one exercises a different discrepancy type.

| # | Scenario | Expected action |
|---|---|---|
| 1 | Clean match — everything agrees | Approve |
| 2 | Vendor billed 15% above PO unit price | Route for review |
| 3 | Vendor billed 12 units, receipt shows 10 | Block |
| 4 | Invoice posted with no goods receipt | Block |
| 5 | Vendor submitted the same invoice twice | Block |

## Project layout

```
src/
  models.py        ERP-neutral data shapes (PO, GR, Invoice, MatchResult)
  odoo_client.py   XML-RPC client that maps Odoo fields onto the neutral models
  match.py         Deterministic three-way match — the authoritative decision logic
  tools.py         Tool definitions exposed to Claude via the Messages API
  agent.py         Claude orchestration loop
scripts/
  seed_odoo.py     Load the five test scenarios into Odoo
  run_agent.py     CLI entry point
tests/
  test_match.py    Unit tests for every discrepancy branch
```

## Why this architecture

Three decisions shape the whole system.

**One, the math lives in Python, not in the model.** `match.py` is a pure function. The LLM calls it via a tool, reads the structured result, and narrates. The model can't invent a dollar amount because it never does arithmetic. If you want an AP agent a CFO will actually deploy, this is the shape.

**Two, every check is recorded.** The `audit_trail` field on the match result is an ordered log of every document pulled, every SKU checked, every number compared, and the final decision. When an auditor asks why invoice BILL/2026/0003 was blocked, the answer is not "the model said so" — it's a timestamped record of the quantities it compared and the tolerance it failed.

**Three, the recommended action is never "done."** The agent recommends approve, route, or block. A human finalizes it. That isn't a limitation — it's the control. Automation without human approval on the exceptions is how an AP department loses its CFO's trust in one bad week.

A deeper write-up lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Tests

```bash
pytest
```

Every discrepancy branch and every recommended action is covered with synthetic fixtures — no Odoo or Anthropic calls needed for the test suite. Integration with Odoo is smoke-tested through the seed script.

## Stack

Odoo 17 (open-source ERP, runs in Docker), Python 3.11, Claude API with tool use, Pydantic for schema, pytest for tests. Zero enterprise licenses.

## What's next

Phase 2 will extend the agent one of three directions: connect procurement to AP end-to-end, add GL coding to approved invoices, or move the same pattern to inventory anomaly detection. The pick depends on where mid-market pain is loudest. If you run a finance team and want to weigh in, the fastest way to reach me is a note on LinkedIn.
