# Session State — ERP Three-Way Match Agent

Living doc. Updated at the end of each working session so any next session (Cowork, Claude Code, or human memory) picks up without re-deriving context.

**Last updated:** 2026-04-16 (Claude Code: V2 cfo_persona + V3 haiku_ap_persona run; attribution resolved)

---

## What landed this session (Claude Code, 2026-04-16)

V2 `cfo_persona` and V3 `haiku_ap_persona` (control) run. Attribution resolved.

- **V2 `cfo_persona` (Haiku 4.5, CFO system prompt):** 28/30 = 93.3%, $0.37. One new miss: `BILL/2026/04/0029` (duplicate, approved). Also the known `BILL/2026/04/0087` miss (price_variance_bad, AND logic).
- **V3 `haiku_ap_persona` (Haiku 4.5, baseline AP system prompt — control):** 29/30 = 96.7%, $0.39. `BILL/2026/04/0029` was caught correctly. Only miss: the known `BILL/2026/04/0087`.

**Attribution: V2 duplicate miss (`BILL/2026/04/0029`) was caused by the CFO persona, not Haiku model capability.** Haiku + AP persona catches it. Haiku + CFO persona misses it. The CFO framing — "lead with dollar exposure, skip procedural detail" — suppressed the agent's caution on a duplicate that had a relatively small dollar amount. That is a Fairness and Reliability finding.

**Full scorecard (4 variants):**

| Variant | Model | Role | Matcher | Accuracy | Cost | Latency |
|---|---|---|---|---|---|---|
| baseline | Sonnet 4.6 | AP clerk | AND | 96.7% (29/30) | $1.26 | ~17s |
| tight_tolerance | Sonnet 4.6 | AP clerk | OR | 90.0% (27/30) | $1.28 | ~17s |
| cfo_persona | Haiku 4.5 | CFO | AND | 93.3% (28/30) | $0.37 | ~9s |
| haiku_ap_persona | Haiku 4.5 | AP clerk | AND | 96.7% (29/30) | $0.39 | ~9s |

Key findings:
1. Haiku + AP persona matches Sonnet accuracy at 3.2× lower cost — strong cost/reliability story.
2. CFO persona costs 1 duplicate detection — role framing affects decision behavior, not just voice (Fairness finding).
3. OR matcher trades 1 true positive for 3 false positives — policy knob with documented tradeoff (Transparency finding).

**This is a Cowork moment.** Go interpret the four-variant scorecard and decide whether it's shippable for the LinkedIn post draft. See checklist item below.

---

## What landed this session (Claude Code, 2026-04-15 evening)

Variant 1 (`tight_tolerance`) scaffolded. Baseline matcher restored. Nothing run yet.

- **`src/match.py` — `PRICE_VARIANCE_LOGIC` env var added.** Default is `and` (AND logic, baseline behavior). Set to `or` to flip to OR logic without touching the matcher source. The baseline is fully restored at AND — 96.7% / 29/30 is the honest number again.
- **`scripts/run_experiment.py` — `env_overrides` added to `ExperimentConfig`.** Any YAML config can now declare `env_overrides: {KEY: value}` and the runner will inject those before starting. Printed to console at run time so the audit trail is clear.
- **`experiments/configs/tight_tolerance.yaml` created.** Variant 1 config. Sets `PRICE_VARIANCE_LOGIC: or`, keeps model=Sonnet 4.6 (same as baseline to isolate the single logic change). Expected: `price_variance_bad` flips to 5/5, `price_variance_ok` may drop.

**Variant 1 is ready to run.** Command:
```
python -m scripts.run_experiment experiments/configs/tight_tolerance.yaml
```

**Variant 1 run complete.** Results: 27/30 = 90.0%, $1.28 spend.

| Scenario | Baseline (AND) | V1 tight_tolerance (OR) | Delta |
|---|---|---|---|
| price_variance_bad | 4/5 (80%) | 5/5 (100%) | +1 ✓ |
| price_variance_ok | 5/5 (100%) | 2/5 (40%) | -3 ✗ |
| all others | 20/20 | 20/20 | 0 |
| **Overall** | **29/30 (96.7%)** | **27/30 (90.0%)** | **-2** |

Outputs: `experiments/tight_tolerance/runs.jsonl`, `experiments/tight_tolerance/summary.json`

**This is a Cowork moment.** The numbers are clean — OR logic trades 1 true positive for 3 false positives on price_variance_ok. That tradeoff is the scorecard content for the Reliability and Transparency pillars. The framing question is: which story do you want to tell? (a) "AND is the conservative, dollar-safe policy — a $0.31 variance on a $2.40 part doesn't warrant AP manager attention even at 12.9%," or (b) "OR is the auditor-grade policy — any percent exception gets flagged regardless of dollar size." That decision shapes variant narrative and what comes next.

---

## What landed this session (Cowork, 2026-04-15 PM)

Strategy and framing session. No code changes, no experiments run. What got decided:

- **Cost model clarified.** Max plan covers Cowork + Claude Code under one subscription. Only the agent runs (direct API calls via the Python `anthropic` library) hit per-token billing. Revised Phase 1 API budget: **$50–100 total, $200 hard ceiling** on the console. Build-side work is effectively free for Brian on Max.
- **CLAUDE.md cost-control block drafted** (not yet pasted into repo). Rules: Haiku 4.5 default for variants, Sonnet 4.6 for baseline/hero only, no Opus. 30-bill stratified samples. Cache Odoo queries across variants. Per-run cost ceilings $0.15 Sonnet / $0.06 Haiku.
- **CLAUDE.md session-handoff block drafted** (not yet pasted into repo). Tells Claude Code when to kick Brian back to Cowork: results interpretation, judgment calls, prose, or stalling.
- **Scalability story framed** as three layers: (1) business profile via YAML — Phase 1, (2) industry-specific scenario library — Phase 2, (3) ERP adapter swap — Phase 2+. Only Layer 1 is in scope for Phase 1. This transforms the LinkedIn hook from "AP agent on toy Odoo" to "configurable agent lab, 20 minutes to any mid-market profile."
- **Competitive positioning resolved.** Not competing with Stampli / Bill.com / Tipalti / AppZen / Braintrust / Langfuse. Building a methodology artifact — the thing a Wipfli partner walks in with *before* a client picks an AP tool. Vertical differentiator: ERP-specific scenarios, failure modes, audit trail.
- **Pre-publish research checkpoint saved to auto-memory.** Before any public artifact (LinkedIn, Loom, blog) goes out, refresh the competitive landscape scan — the 2026 AP-agent and agent-eval markets move fast.

**Next Cowork moment (top of the list):** resolve the `BILL/2026/04/0087` question from the baseline. Is it a tolerance-calibration issue, a seed-label semantics issue, or a real miss? That decides whether 96.7% is the story or whether baseline gets re-scored.

---

## What landed this session (Cowork, 2026-04-15 late evening — post-Variant 1)

The round-trip ran cleanly. Cowork diagnosed, Claude Code executed, Cowork interpreted. Four things moved:

- **`BILL/2026/04/0087` fully diagnosed and framed.** Root cause identified as the AND-logic in `src/match.py` line 135 combined with low per-unit prices producing sub-$5 absolute deltas. Framing decision: do NOT silently fix. Keep baseline at 96.7% as the honest number. Run the tightened matcher as Variant 1 to make the tradeoff legible. This converts the miss into the demonstration artifact for the Reliability and Transparency pillars.
- **Variant 1 (`tight_tolerance`) spec delivered to Claude Code.** One-paragraph spec covering RPST dimension swapped (Tool), hypothesis, expected tradeoff, Gartner pillars pressure-tested, output artifact. Claude Code scaffolded it cleanly using an env-var-controlled matcher so baseline remained restorable.
- **UI direction decided: lightweight static HTML viewer.** Rejected Streamlit (feels like an MBA class project, tethers to the repo) and Next.js (months of scope creep). The viewer reads `experiments/<name>/runs.jsonl` and `summary.json`, renders six-pillar scorecards side-by-side, hosts on GitHub Pages, links directly from the LinkedIn post. Zero backend. Loom-friendly. Non-technical readers scroll through a scorecard, they do not run experiments. That is the correct bar. Build after at least three variants have run.
- **`docs/CONTENT_IDEAS.md` created.** Scratchpad for LinkedIn post hooks with an honesty rule: things listed are legitimately rare, with an explicit "not rare" section to keep the file honest. Six entries. Candidate for first post: "the miss is the feature" — Variant 1 numbers write the narrative on their own. Publish only after at least one more variant has run so the scorecard has depth.

**Next Cowork moment (top of the list):** resolve the AND-vs-OR policy framing question raised by the Variant 1 results. The scorecard tradeoff is clean (AND: 96.7% total, 80% on price_variance_bad; OR: 90.0% total, 100% on price_variance_bad, 40% on price_variance_ok). The consulting question is which policy posture the lab recommends as "default" for mid-market AP, and whether the scorecard presents them as equals or names a preferred default with caveats. That decision shapes Variant 2's hypothesis.

---

## What landed this session (Cowork, 2026-04-15 late evening — policy + V2 framing + CLAUDE.md)

Three decisions closed out. Claude Code is unblocked.

- **Policy default resolved.** AND logic (baseline, 96.7%) is the lab's recommended default for mid-market AP. OR logic (V1, 90.0%) is the strict audit-grade mode for regulated industries, high-fraud-risk contexts, or environments where systematic percent-level price creep outranks AP-manager bandwidth. Scorecard should present both as a policy knob, not a "winner/loser." Rationale: mid-market AP's scarcest resource is reviewer attention; a $0.31 variance on a $2.40 part is not worth vendor friction and delayed early-pay discount.
- **Variant 2 hypothesis set.** **CFO persona role swap.** Rerun the 30-bill sample with a CFO persona in the agent's system prompt instead of the default AP-analyst framing. Same Playbook, Skills, Tools. Model: Haiku 4.5 (cost-control default for variants). PRST axis: **R** (Roles). Gartner pillar under test: **Fairness** — does changing role framing shift decisions on identical inputs? Either outcome is a finding. If decisions shift, that is the Fairness story. If they do not, that is the architecture claim (matcher is the arbiter, not the narration).
- **CLAUDE.md created and pasted into repo.** `phase1-three-way-match/CLAUDE.md` now contains the Cost Control block, the Cowork↔Claude Code Handoff block, and the Standing Decisions block (including the AND-as-default policy). Both earlier drafts are no longer floating; the rules bind the next session.

**Next Cowork moment (top of the list):** interpret Variant 2 results once Claude Code runs them. If the CFO persona shifts decisions on borderline bills (especially price_variance_ok), that is the Fairness pillar story for the scorecard. If it does not, write up the consistency result as the architecture claim. Either way, results come back to Cowork before Variant 3 gets scoped.

---

## Gartner pillars pressure-tested by the four-variant scorecard

Reliability (cost-accuracy frontier via Haiku vs Sonnet), Fairness (role-framing effect via CFO vs AP persona on Haiku), Transparency (policy-knob tradeoff via AND vs OR matcher). Three of six pillars. Accountability is implicit in the audit trail. Privacy and Security have not been pressure-tested. Prompt-injection and PII-leakage tests remain on the checklist as optional pre-post polish or as Phase 1.5 content.

**Next Cowork moment (top of the list):** decide whether the scorecard is shippable for the LinkedIn post, or whether one more variant (Security via prompt injection, for example) runs first. Before any public artifact: refresh the competitive landscape scan per the pre-publish checkpoint in auto-memory.

---

## Where the project is right now

**Phase 1 agent works end-to-end against a labeled 300-invoice playground.** Ground truth validated — one duplicate bill and one qty_over bill both blocked with reasons matching the manifest.

### Stack, as running
- Odoo 17 Community + Postgres 15 in Docker Compose (`phase1-three-way-match/docker-compose.yml`)
- Python agent using Claude Messages API with tool-use (`agent/loop.py`, `agent/tools.py`)
- XML-RPC bridge to Odoo (`adapters/odoo_adapter.py`)
- Pydantic models for ERP-neutral contracts
- Pure-Python deterministic matcher — math in code, narration in model
- Rich library for CLI output

### What's labeled in the playground
50 vendors (tagged `PLAYGROUND`), 30 SKU-prefixed products (`PG-...`), ~330 invoices across six scenarios:

| Scenario | Expected | Share |
|---|---|---|
| clean | approve | ~75% |
| price_variance_ok | approve | ~4% |
| price_variance_bad | route | ~8% |
| qty_over_invoiced | block | ~5% |
| missing_gr | block | ~3% |
| duplicate | block | ~6% |

Manifest at `playground_manifest.json` (project root). Seed script at `scripts/seed_playground.py`. Clean reset: `docker compose down -v && docker compose up -d`.

### Validated demo artifacts
- `BILL/2026/03/0020` — duplicate of `BILL/2026/03/0019`. Agent blocks. 5 tool calls.
- `BILL/2026/04/0024` — Pacific Rim Abrasives, four qty-mismatch lines totaling ~$611 overbilled. Agent blocks. 5 tool calls.

Raw agent output saved to `demo_artifacts/pacific_rim_qty_over.txt` (qty_over example).

### Baseline run captured (2026-04-15)
- Config: `experiments/configs/baseline.yaml` — Sonnet 4.6, max_turns=12, default playbook + tools
- Sample: 30 bills, stratified flat (5 per scenario × 6 scenarios) — required by cost-control rules
- Result: **29/30 = 96.7% accuracy**, $1.26 total spend, 4 turns avg, 17.4s/bill avg latency
- Per-scenario: clean 5/5, duplicate 5/5, missing_gr 5/5, price_variance_ok 5/5, qty_over_invoiced 5/5, **price_variance_bad 4/5**
- One miss: `BILL/2026/04/0087` (PO P00253, $112.19) — labeled `price_variance_bad`, agent approved with empty discrepancy list. Rationale: "within tolerance." Likely the deterministic matcher (`src/match.py`) treated the variance as inside the configured tolerance bands (`PRICE_VARIANCE_TOLERANCE_USD=$5`, `PRICE_VARIANCE_TOLERANCE_PCT=2%`). NOT necessarily an agent reasoning failure — could be tolerance calibration or seed-label semantics.
- Outputs: `experiments/baseline/runs.jsonl`, `experiments/baseline/summary.json`, `experiments/baseline/plan.json`

---

## The project is no longer "a three-way match demo"

It's becoming an **agent experimentation lab** with a realistic sandbox, reproducible experiments, and evaluation against Gartner's six pillars of AI governance. The three-way match is the first task the lab runs experiments against.

### Framework axes (RPST — from Tallgrass lexicon)

The Tallgrass-canonical acronym is RPST: Role / Playbook / Skills / Tools. Same four elements as the earlier "PRST" shorthand used in prior notes, different letter order. Using RPST everywhere going forward to match the client's framework.
- **P**laybook — the rules/steps the agent follows
- **R**oles — the persona/perspective given to the agent
- **S**kills — reasoning patterns available to it
- **T**ools — what it can call

Each experiment varies one or more RPST dimensions and measures the delta.

### Evaluation structure (Gartner's six pillars of AI governance)
- **Transparency** — can a reviewer reconstruct why the agent decided what it decided?
- **Fairness** — does the agent behave consistently across vendor/product patterns?
- **Accountability** — is there a clear audit trail, a clear owner, a clear hold?
- **Privacy** — does it leak PII or restricted fields?
- **Security** — does it resist prompt injection in invoice notes/vendor names?
- **Reliability** — does it give the same answer twice on the same input? Does it degrade gracefully?

The eventual LinkedIn narrative is a consulting brief scored against these pillars — not an engineering demo.

---

## Running checklist (reprioritized at each session)

### Now (validation → experiment runner)
- [x] Seed 300-invoice labeled playground
- [x] Validate ground truth with one duplicate + one qty_over run
- [x] Build `scripts/run_experiment.py` — YAML config, iterates manifest subset, logs decision + turns + tokens + latency + cost per run, writes `experiments/<name>/runs.jsonl` and `summary.json`. Includes `--dry-run`, `--limit N`, `--reaggregate` modes. Per-run cost ceilings honored ($0.15 Sonnet / $0.06 Haiku).
- [x] Prove baseline: 96.7% on 30-bill flat-stratified sample, $1.26 spend, captured in `experiments/baseline/`
- [x] **Resolve the BILL/2026/04/0087 question** — diagnosed as matcher AND-logic artifact. Framing decision: keep baseline at 96.7%, run tightened matcher as Variant 1. See Open Questions #1.
- [x] **Scaffold Variant 1: `tight_tolerance`** — config at `experiments/configs/tight_tolerance.yaml`, `PRICE_VARIANCE_LOGIC` env var added to `src/match.py`, `env_overrides` wired into runner. Baseline restored to AND (96.7%).
- [x] **Run Variant 1: `tight_tolerance`** — 27/30 = 90.0%, $1.28. OR fixed price_variance_bad (5/5) but dropped price_variance_ok to 2/5. See tradeoff table above.
- [x] **Variant 2 scoped: `cfo_persona` role swap.** RPST axis = R. Gartner pillar under test = Fairness. Model = Haiku 4.5. Sample = 30 bills. Same Playbook/Skills/Tools as baseline.
- [x] Run Variant 2: `cfo_persona`. Results: 28/30 = 93.3%, $0.37, ~9s latency. New miss on `BILL/2026/04/0029` (duplicate). Same miss on `BILL/2026/04/0087` as baseline (expected, AND logic unchanged).
- [x] **Run Variant 3: `haiku_ap_persona` (control).** 29/30 = 96.7%, $0.39. `BILL/2026/04/0029` caught. Attribution: CFO persona caused V2 duplicate miss, not Haiku model capability. Fairness finding confirmed.
- [ ] **Cowork: interpret 4-variant scorecard, decide if shippable for LinkedIn post draft.** 4 variants × 3 RPST axes covered = enough for minimum viable scorecard. See scorecard table in "What landed" section above.
- [ ] Design remaining RPST variants if scorecard needs more depth (e.g., "no duplicate-check tool," "terse playbook"). Per cost-control rules: variants on Haiku 4.5, 30 bills, $0.06/run ceiling.
- [ ] Build static HTML scorecard viewer (after Cowork green-lights it)

### Soon (demo polish)
- [ ] Design three UI mockups as HTML artifacts — the PowerShell UI will not be in the Loom
- [ ] Build the chosen web dashboard
- [ ] Build naive-vs-disciplined split-screen agent (shows hallucination risk without discipline)
- [ ] Save 3–5 clean agent runs to `demo_artifacts/` with scenario labels in filenames

### Scalability (Layer 1 of configurable-sandbox story)
- [ ] Parameterize `seed_playground.py` with profile YAML configs — vendors, products, scenario mix, PO volume, date range live in config not code
- [ ] Ship 2–3 sample profiles (`profile_manufacturer.yaml`, `profile_services_firm.yaml`, `profile_distributor.yaml`)
- [ ] README section: "adapt the sandbox to your business in 20 minutes"
- [ ] Phase 2 deferrals documented: Layer 2 (industry-specific sce