# Scorecard Viewer — Build Spec

**Owner:** Brian Caputo  
**Target:** Single static HTML file for GitHub Pages  
**Last updated:** 2026-04-16

---

## 1. What This Is

A single-page static HTML viewer that presents the four-variant experiment scorecard from the Phase 1 Three-Way Match AP Agent. It serves as the "proof link" from Brian's LinkedIn post and portfolio — the thing a recruiter, CFO, or consulting contact clicks to see real results, not just claims.

**Hosting:** GitHub Pages (static files only, no server)  
**File:** `docs/viewer/index.html` (single file, all CSS/JS inline)  
**Data:** Embed JSON directly in the HTML via `<script>` tags — no fetch calls, no CORS issues

---

## 2. Page Structure (Single Scrolling Page)

Anchor nav at the top. Five sections, this order:

### Section 1: Header
- **Primary:** "Brian Caputo" (name prominent)
- **Subtitle:** "ERP Agent Experimentation Lab — Phase 1: Three-Way Match"
- **One-liner:** "Four variants, three Gartner findings, 120 invoices processed by an AI agent against a live Odoo ERP."
- Clean, professional. Dark text on white, or dark-mode toggle if trivial to add.

### Section 2: Executive Summary (3 sentences max)
- Sentence 1: What was tested (AI agent doing three-way match AP against Odoo 17)
- Sentence 2: Headline finding (Haiku matches Sonnet accuracy at 3.2× lower cost; role framing — not model capability — caused the only behavioral divergence)
- Sentence 3: Framework callout (evaluated against Gartner's six pillars for trustworthy AI)

### Section 3: Scorecard Table
The 4-variant comparison table. Columns:

| Column | Source field | Notes |
|--------|-------------|-------|
| Variant | experiment name | Human-readable label |
| Model | config.agent.model | Display as "Sonnet 4.6" / "Haiku 4.5" |
| Role | "AP Clerk" or "CFO" | Derive from config: null system_prompt = AP Clerk |
| Matcher Logic | "AND" or "OR" | Derive from env_overrides |
| Accuracy | totals.accuracy | Format as "96.7% (29/30)" |
| Cost | totals_cost.cost_usd | Format as "$1.26" |
| Avg Latency | averages.latency_ms | Format as "~17s" (divide by 1000, round) |
| Avg Turns | averages.turns | One decimal |

Row order: baseline, tight_tolerance, cfo_persona, haiku_ap_persona.

Color-code accuracy cells: ≥95% green, 90-94% amber, <90% red.

### Section 4: Gartner Pillar Findings
Three cards or callout boxes, one per finding:

**Reliability** — Haiku 4.5 matches Sonnet 4.6 at 96.7% accuracy on the same AP-clerk prompt, at 3.2× lower cost and ~2× lower latency. Model selection is a cost lever, not an accuracy lever, for this task.

**Fairness** — The CFO persona missed a duplicate invoice (BILL/2026/04/0029) that both AP-clerk variants caught. The miss traces to role framing ("dollar exposure" priority de-weighted duplicate detection), not model capability — proven by the Haiku AP control matching baseline accuracy. Persona design is a fairness surface.

**Transparency** — The OR matcher (tight_tolerance) traded 1 true positive for 3 false positives on price_variance_ok scenarios. The AND→OR policy change is visible, measurable, and reversible — a clean audit trail for policy decisions.

### Section 5: Variant Drill-Downs (Expandable)
One collapsible section per variant. Each contains:

**5a. Config summary**
- Model, role, matcher logic, sample size, seed

**5b. Scenario breakdown table**
From `summary.json → by_scenario`. Columns: Scenario, N, Correct, Accuracy, Decisions (approve/route/block).

Six rows: clean, price_variance_bad, price_variance_ok, qty_over_invoiced, duplicate, missing_gr.

**5c. Per-invoice results table**
From `runs.jsonl`. Columns: Bill, Scenario, Expected, Actual, Match (✓/✗), Cost, Latency.

Sort: mismatches first (✗), then alphabetical by bill name.

**5d. Agent reasoning traces**
For each invoice in the per-invoice table, a collapsible row that shows:
- `rationale` field (the agent's one-paragraph reasoning)
- `discrepancy_codes` array
- `turns` and `tool_calls` count

Highlight mismatches with a red left-border or background tint so they're immediately visible.

---

## 3. Data Embedding Strategy

Claude Code should:
1. Read all four `summary.json` files
2. Read all four `runs.jsonl` files (30 lines each)
3. Read all four config YAML files
4. Embed the combined data as a single JSON object in a `<script>` tag at the top of the HTML
5. Render everything client-side with vanilla JS (no frameworks)

Approximate data size: ~120 run records × ~1KB each + 4 summaries × ~2KB = ~130KB embedded. Fine for a single page.

---

## 4. Styling Requirements

- **No external dependencies** — all CSS inline or in `<style>` tags
- Clean, professional typography (system font stack: -apple-system, Segoe UI, etc.)
- Responsive: readable on mobile (tables scroll horizontally if needed)
- Color palette: neutral grays + one accent color for highlights
- Tables: zebra-striped rows, sticky headers on scroll
- Collapsible sections: simple `<details>/<summary>` elements or minimal JS toggle
- Print-friendly: collapsible sections should expand when printed

---

## 5. File Locations (Absolute Paths)

**Source data to read:**
- `experiments/baseline/summary.json`
- `experiments/baseline/runs.jsonl`
- `experiments/tight_tolerance/summary.json`
- `experiments/tight_tolerance/runs.jsonl`
- `experiments/cfo_persona/summary.json`
- `experiments/cfo_persona/runs.jsonl`
- `experiments/haiku_ap_persona/summary.json`
- `experiments/haiku_ap_persona/runs.jsonl`
- `experiments/configs/baseline.yaml`
- `experiments/configs/tight_tolerance.yaml`
- `experiments/configs/cfo_persona.yaml`
- `experiments/configs/haiku_ap_persona.yaml`

**Output:**
- `docs/viewer/index.html` (single file, everything inline)

---

## 6. Build Notes

- This is a static artifact — no build step, no bundler, no npm
- Must work when opened directly as a file (file://) AND when served by GitHub Pages
- All paths are relative within the HTML (no absolute filesystem paths)
- The embedded data is a snapshot — if experiments re-run, the HTML must be regenerated
- Target: under 200KB total file size
