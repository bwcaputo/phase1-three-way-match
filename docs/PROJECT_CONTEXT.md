# ERP Agent Experimentation Lab — Project Context

Cross-session reference file. Copy or link this into any Cowork session that needs to know where this project stands.

**Last updated:** 2026-04-17

---

## What this is

A configurable AI agent experimentation lab that runs three-way match (PO, goods receipt, vendor bill) against a live Odoo 17 ERP. The agent processes invoices, the deterministic matcher computes the decision, and the model orchestrates and narrates. Seven experiment variants have run against a 300-invoice labeled playground across 8 scenario types. Results are scored against Gartner's six pillars for trustworthy AI.

This is a personal portfolio project targeting Brian's Wipfli ERP Tech Consulting internship (Summer 2026). It is not a Tallgrass deliverable.

---

## What's shipped (as of 2026-04-17)

**Agent and infrastructure:**
- Odoo 17 Community + Postgres 15 in Docker Compose
- Python agent using Claude Messages API with tool use
- Pure-Python deterministic matcher (math in code, narration in model)
- XML-RPC bridge to Odoo via adapters/odoo_adapter.py
- 300-invoice labeled playground with JSON manifest across 8 scenario types + 10 prompt injection bills
- Experiment runner with YAML configs, env_overrides, cost controls, and per-run ceilings
- Model abstraction layer: AnthropicAdapter, OpenAIAdapter, OllamaAdapter — swap providers via `adapter=` param
- Flask web UI at localhost:5000: dashboard, experiment detail with collapsible invoice cards, live-streaming run page
- Multi-seed runner: `run_multiseed.py` tests stability across seeds, reports mean/std and per-scenario variance

**Seven experiment variants completed:**

| Variant | Display Name | RPST Axis | Model | Accuracy | Cost | Gartner Pillar |
|---------|-------------|-----------|-------|----------|------|----------------|
| baseline | Baseline (Sonnet 4.6) | -- | Sonnet 4.6 | 96.7% (29/30) | $1.26 | Control |
| tight_tolerance | Tight Tolerance (OR Logic) | Policy | Sonnet 4.6 | 90.0% (27/30) | $1.28 | Transparency |
| cfo_persona | CFO Persona | Role | Haiku 4.5 | 93.3% (28/30) | $0.37 | Fairness |
| haiku_ap_persona | AP Clerk Control (Haiku) | Role + Model | Haiku 4.5 | 96.7% (29/30) | $0.39 | Reliability |
| prompt_injection | Prompt Injection Test | Security | Haiku 4.5 | 80%* (8/10) | $0.12 | Security |
| goal_only_playbook | Goal-Only Playbook | Playbook | Haiku 4.5 | 68.6% (24/35) | $0.49 | Accountability |
| no_duplicate_tool | No Duplicate Tool | Skills/Tools | Haiku 4.5 | 77.1% (27/35) | $0.40 | Accountability |

*Prompt injection: 2 AND-logic tolerance misses on low-dollar parts, not injection successes. 10/10 payloads ignored.

**Four Gartner pillar findings confirmed:**
- Reliability: Haiku matches Sonnet at 96.7% accuracy at 3.2x lower cost. Model selection is a cost lever, not accuracy.
- Fairness: CFO persona missed a $47 duplicate the AP clerk caught. Role framing is a fairness surface.
- Transparency: AND-to-OR policy switch traded 1 true positive for 3 false positives. Measurable, reversible, auditable.
- Security: 10/10 prompt injection payloads ignored. Architecture (deterministic matcher) is the defense, not prompt engineering.
- Accountability (two findings): Remove the playbook -> accuracy drops from 96.7% to 68.6%. Remove the duplicate-check tool -> duplicate detection drops to 0% with no error signal. Prescriptive instructions and complete toolkits are load-bearing.

**Multi-seed stability (completed 2026-04-16):**
- `haiku_ap_persona`: seeds 42/99/7 — avg ~93.8%, std <3pp. STABLE.
- `goal_only_playbook`: seeds 42/99/7 — avg ~69.5%, std ~2pp. STABLE.
- `no_duplicate_tool`: seeds 42/99 — 0% duplicate accuracy on both seeds. Silent degradation is not a seed artifact.

**Eight scenario types in playground:**
- clean, price_variance_ok, price_variance_bad, qty_over_invoiced, missing_gr, duplicate (original 6)
- partial_shipment: 50-80% of PO received; invoice matches GR not PO (added 2026-04-16)
- blanket_po: large standing PO, partial drawdown, three-way match passes (added 2026-04-16)

**Public artifacts:**
- GitHub repo: github.com/bwcaputo/phase1-three-way-match
- Static HTML scorecard viewer: docs/viewer/index.html (GitHub Pages)
- First LinkedIn post published 2026-04-16 ("the miss is the feature" angle)

**Scalability layer:**
- seed_playground.py refactored to accept --profile YAML
- Three sample profiles shipped: manufacturer, services firm, distributor
- --dry-run validation flag for profile testing without Odoo

**Pending (API limit resets 2026-05-01):**
- Re-run haiku_ap_persona and baseline against expanded 8-scenario playground to add partial_shipment and blanket_po to by_scenario results
- Command: `python scripts/run_experiment.py experiments/configs/haiku_ap_persona.yaml` then `python scripts/run_experiment.py experiments/configs/baseline.yaml --rebuild-viewer`

---

## Frameworks

**RPST** (from Tallgrass lexicon): Role / Playbook / Skills / Tools. Each experiment varies one or more RPST dimensions. The acronym is RPST, not PRST.

**Gartner's six pillars of AI governance:** Transparency, Fairness, Accountability, Privacy, Security, Reliability. Five of six now have empirical findings (Accountability added via goal_only_playbook and no_duplicate_tool variants). Privacy has not been tested.

---

## Key architecture decisions

- Math in code, narration in model. The LLM never computes totals, variances, or match decisions. The deterministic matcher does. This is why prompt injection is inert.
- AND logic is the default matcher policy. OR is the strict audit-grade mode. Configurable via env var.
- Haiku 4.5 is the default model for variants. Sonnet 4.6 for baselines only. Opus ruled out on cost.
- 30-bill stratified samples (5 per scenario) are the standard. Keeps cost under $0.50/variant on Haiku.

---

## What's next

**Immediate (API resets 2026-05-01):**
- Re-run haiku_ap_persona + baseline against 8-scenario playground
- Rebuild viewer with partial_shipment + blanket_po in the scorecard

**Phase 2 priorities (in order):**
1. Web UI at localhost:5000 is live — demo it in the Loom instead of the terminal
2. Tolerance thresholds as profile-level config (business policy in YAML, not env vars)
3. Test OpenAI and/or Ollama adapter via model_adapter.py — cross-provider comparison variant
4. Vertical expansion: services firm scenarios (T&M billing, missing GR on professional services)

**Content pipeline:**
- Weekly LinkedIn posting goal (started 2026-04-16)
- Next post: security finding ("I injected SYSTEM OVERRIDE into an invoice. The agent ignored it.")
- Future post: scalability angle ("I parameterized the sandbox so anyone can configure it for their business")
- Capstone post (later): "My AI agent project isn't engineer-shaped. It's consultant-shaped."

**Phase 2/3 possibilities (documented in docs/ROADMAP.md):**
- Model abstraction layer (OpenAI, Gemini, local models)
- Workflow abstraction (expense reports, vendor onboarding, PO creation)
- Dataset import path (bring your own labeled manifest)
- UI for non-technical reviewers
- Consulting firm methodology artifact
- Teaching material / workshop curriculum
- Vertical expansion (healthcare RCM, insurance claims, order-to-cash)

---

## Key files

| File | Purpose |
|------|---------|
| docs/SESSION_STATE.md | Living session log, checklist, handoff context |
| docs/ROADMAP.md | Phase 2/3 possibilities (no code until Phase 1 ships) |
| docs/CONTENT_IDEAS.md | LinkedIn post hooks with honesty filter |
| docs/VIEWER_SPEC.md | Build spec for the HTML scorecard viewer |
| docs/viewer/index.html | Static scorecard viewer (GitHub Pages) |
| CLAUDE.md | Cost control, handoff rules, standing decisions |
| experiments/configs/*.yaml | Experiment variant configurations |
| experiments/*/summary.json | Aggregated results per variant |
| experiments/*/runs.jsonl | Per-invoice results with agent reasoning traces |
| profiles/*.yaml | Business profile configs for the playground |
| scripts/run_experiment.py | Experiment runner |
| scripts/run_multiseed.py | Multi-seed stability runner |
| scripts/compare_variants.py | Side-by-side table (--json / --csv flags) |
| scripts/seed_playground.py | Playground seeder (accepts --profile) |
| scripts/build_viewer.py | Viewer HTML generator |
| app.py | Flask web UI (localhost:5000) |
| src/model_adapter.py | Model abstraction layer (Anthropic, OpenAI, Ollama) |
| docs/AGENT_INTERFACE.md | Input/output contract, tool schemas, adapter protocol |
| playground_manifest.json | Ground truth labels for all seeded bills |

---

## Project framing

This is a methodology artifact, not a product. Brian is not competing with Stampli, Tipalti, or AppZen. He's building the thing a consulting partner walks in with before a client picks an AP tool. The competitive landscape scan (completed 2026-04-16) confirmed nobody has published a comparable open-source agent experimentation lab against ERP with labeled ground truth and governance scoring.

Success = learning + consulting credibility. Ship at 85%, iterate in public.
