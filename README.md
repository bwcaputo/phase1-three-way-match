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

## Scorecard

Seven experiments. Four RPST axes. The scorecard a consulting team runs before a client picks an AP agent.

| Variant | RPST Axis | Model | Accuracy |
|---|---|---|---|
| baseline | — | Sonnet 4.6 | 96.7% |
| tight_tolerance | Tolerance tuning | Sonnet 4.6 | 96.7% |
| cfo_persona | Role | Sonnet 4.6 | 96.7% |
| haiku_ap_persona | Role + Model | Haiku 4.5 | 93.3% |
| prompt_injection | Security | Haiku 4.5 | 90.0% |
| goal_only_playbook | Playbook | Haiku 4.5 | 70.0% |
| no_duplicate_tool | Skills/Tools | Haiku 4.5 | 73.3%* |

\* `no_duplicate_tool` catches 0% of duplicate invoices — silent degradation with no error signal.

The full interactive scorecard is at [`docs/viewer/index.html`](docs/viewer/index.html).

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

# 3. Install Python deps and seed the playground
pip install -r requirements.txt
python scripts/seed_playground.py

# 4. Run the agent on one invoice
python -m scripts.run_agent BILL/2026/0001

# 5. Run a full experiment
python scripts/run_experiment.py experiments/configs/haiku_ap_persona.yaml

# 6. Open the web UI
python app.py
# Then visit http://localhost:5000
```

## Web UI

`app.py` is a lightweight Flask dashboard for the lab. It has three pages:

- **Dashboard** — all variants, accuracy, cost, and per-scenario breakdown in one table
- **Experiment detail** — every run, pass/fail, turns, latency, and error for one variant
- **Run experiment** — pick a config, launch a run, stream the output live

```bash
pip install flask
python app.py
# Optional: python app.py --port 5001 --debug
```

## The eight seeded scenarios

The playground seeds 300 bills across eight scenario types. Each one exercises a different discrepancy type or edge case.

| Scenario | Expected action | Description |
|---|---|---|
| clean | Approve | PO, GR, and invoice all agree |
| price_variance_ok | Approve | Variance within tolerance |
| price_variance_bad | Route/Block | Variance above tolerance |
| qty_over_invoiced | Block | Invoice quantity > received quantity |
| missing_gr | Block | No goods receipt on file |
| duplicate | Block | Same vendor, same total, posted twice |
| partial_shipment | Approve | GR received 50–80% of PO; invoice matches GR |
| blanket_po | Approve | Standing PO, partial drawdown, invoice matches receipt |

## Running experiments

Each experiment is one YAML config in `experiments/configs/`. The harness samples 30 bills at random, runs the agent on each, and writes results to `experiments/<variant>/`.

```bash
# Run one variant
python scripts/run_experiment.py experiments/configs/haiku_ap_persona.yaml

# Run the same variant across multiple seeds to check stability
python scripts/run_multiseed.py experiments/configs/haiku_ap_persona.yaml --seeds 42,99,7

# Compare all variants side-by-side
python scripts/compare_variants.py

# Rebuild the static scorecard
python scripts/build_viewer.py
```

## Model providers

The agent supports swappable model providers through `src/model_adapter.py`.

| Provider | Model prefix | Install |
|---|---|---|
| Anthropic (default) | `claude-*` | `pip install anthropic` |
| OpenAI | `gpt-*`, `o1-*`, `o3-*` | `pip install openai` |
| Ollama (local) | `ollama:*`, `llama*`, `mistral*` | `pip install openai` + Ollama running |

To run against a local Llama model:

```bash
# Start Ollama with a model that supports tool use
ollama pull llama3.1

# Set model in .env or pass it directly
ANTHROPIC_MODEL=llama3.1 python scripts/run_experiment.py experiments/configs/haiku_ap_persona.yaml
```

See [`docs/AGENT_INTERFACE.md`](docs/AGENT_INTERFACE.md) for the full adapter protocol and how to register a custom provider.

## Project layout

```
src/
  models.py           ERP-neutral data shapes (PO, GR, Invoice, MatchResult)
  odoo_client.py      XML-RPC client that maps Odoo fields onto the neutral models
  match.py            Deterministic three-way match — the authoritative decision logic
  tools.py            Tool definitions exposed to the model via the Messages API
  agent.py            Agent loop (provider-agnostic via model_adapter)
  model_adapter.py    Model abstraction layer (Anthropic, OpenAI, Ollama)
scripts/
  seed_playground.py  Seed 300 bills across 8 scenario types into Odoo
  run_agent.py        CLI: run the agent on a single invoice
  run_experiment.py   Run a full experiment from a YAML config
  run_multiseed.py    Run one config across multiple seeds, report stability
  compare_variants.py Side-by-side accuracy table across all experiment dirs
  build_viewer.py     Rebuild docs/viewer/index.html from experiment results
experiments/
  configs/            YAML experiment configs (one per RPST variant)
  baseline/           Results for the Sonnet baseline (frozen reference)
  haiku_ap_persona/   ... and all other variants
docs/
  AGENT_INTERFACE.md  Input/output contract, tool schemas, adapter protocol
  ARCHITECTURE.md     Why the code is structured this way
  viewer/index.html   Self-contained static scorecard
app.py                Flask web UI for the lab
profiles/             Business profile YAMLs for seeding industry-specific playgrounds
tests/
  test_match.py       Unit tests for every discrepancy branch
```

## Why this architecture

Three decisions shape the whole system.

**One, the math lives in Python, not in the model.** `match.py` is a pure function. The LLM calls it via a tool, reads the structured result, and narrates. The model can't invent a dollar amount because it never does arithmetic. If you want an AP agent a CFO will actually deploy, this is the shape.

**Two, every check is recorded.** The `audit_trail` field on the match result is an ordered log of every document pulled, every SKU checked, every number compared, and the final decision. When an auditor asks why invoice BILL/2026/0003 was blocked, the answer is not "the model said so" — it's a timestamped record of the quantities it compared and the tolerance it failed.

**Three, the recommended action is never "done."** The agent recommends approve, route, or block. A human finalizes it. That isn't a limitation — it's the control. Automation without human approval on the exceptions is how an AP department loses its CFO's trust in one bad week.

A deeper write-up lives in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Adapt the sandbox to your business

The playground is configurable through business profile YAMLs. Each profile defines the vendor pool, product catalog, scenario mix, and volume for a specific industry context.

Three sample profiles ship with the project:

| Profile | Vendors | Products | Invoices | Key risk pattern |
|---------|---------|----------|----------|------------------|
| Manufacturer | 50 | 30 | 300 | Price variances on commodity parts |
| Services Firm | 25 | 15 | 150 | Missing GR on services, duplicate retainer bills |
| Distributor | 40 | 25 | 500 | High-volume price shifts on commodities |

To seed a playground from a profile:

```bash
docker compose down -v && docker compose up -d
python scripts/seed_playground.py --profile profiles/profile_distributor.yaml
```

To validate a profile without connecting to Odoo:

```bash
python scripts/seed_playground.py --profile profiles/your_profile.yaml --dry-run
```

## Tests

```bash
pytest
```

Every discrepancy branch and every recommended action is covered with synthetic fixtures — no Odoo or Anthropic calls needed for the test suite. Integration with Odoo is smoke-tested through the seed script.

## Stack

Odoo 17 (open-source ERP, runs in Docker), Python 3.11, Claude API with tool use, Pydantic for schema, pytest for tests, Flask for the lab web UI. Zero enterprise licenses.

## What's next

Phase 2 will extend the agent one of three directions: connect procurement to AP end-to-end, add GL coding to approved invoices, or move the same pattern to inventory anomaly detection. The pick depends on where mid-market pain is loudest. If you run a finance team and want to weigh in, the fastest way to reach me is a note on LinkedIn.
