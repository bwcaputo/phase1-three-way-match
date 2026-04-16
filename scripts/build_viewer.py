"""
build_viewer.py
Reads experiment summary.json and runs.jsonl files, embeds them inline,
and writes docs/viewer/index.html as a self-contained static scorecard.
"""
import json
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "experiments"
OUT_DIR = ROOT / "docs" / "viewer"
OUT_FILE = OUT_DIR / "index.html"

VARIANTS = ["baseline", "tight_tolerance", "cfo_persona", "haiku_ap_persona"]

# ── Load data ──────────────────────────────────────────────────────────────────
data = {}
for v in VARIANTS:
    summary_path = EXPERIMENTS / v / "summary.json"
    runs_path    = EXPERIMENTS / v / "runs.jsonl"

    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    runs = []
    with open(runs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                runs.append(json.loads(line))

    data[v] = {"summary": summary, "runs": runs}

data_json = json.dumps(data, default=str, ensure_ascii=False)

# ── HTML template ──────────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Brian Caputo — ERP Agent Experimentation Lab</title>
<style>
/* ── Reset & base ─────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --accent:  #2563eb;
  --text:    #111827;
  --muted:   #6b7280;
  --border:  #e5e7eb;
  --bg:      #ffffff;
  --bg-alt:  #f9fafb;
}}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--text);
  background: var(--bg);
  line-height: 1.55;
}}

/* ── Layout ───────────────────────────────────────────────── */
.container {{ max-width: 1100px; margin: 0 auto; padding: 0 1rem; }}

/* ── Nav ──────────────────────────────────────────────────── */
nav {{
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 0.6rem 0;
}}
nav .container {{
  display: flex;
  gap: 1.5rem;
  align-items: center;
}}
nav a {{
  color: var(--accent);
  text-decoration: none;
  font-size: 0.9rem;
  font-weight: 500;
}}
nav a:hover {{ text-decoration: underline; }}

/* ── Header ───────────────────────────────────────────────── */
header {{
  padding: 2.5rem 0 1.5rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 2rem;
}}
header h1 {{ font-size: 2rem; font-weight: 700; }}
header .subtitle {{
  font-size: 1.1rem;
  color: var(--muted);
  margin-top: 0.25rem;
}}
header .one-liner {{
  margin-top: 0.6rem;
  font-size: 0.95rem;
  color: var(--text);
}}

/* ── Sections ─────────────────────────────────────────────── */
section {{ margin-bottom: 3rem; }}
section h2 {{
  font-size: 1.25rem;
  font-weight: 700;
  margin-bottom: 1rem;
  padding-bottom: 0.4rem;
  border-bottom: 2px solid var(--border);
}}

/* ── Exec summary ─────────────────────────────────────────── */
.exec-summary p {{
  margin-bottom: 0.75rem;
  max-width: 820px;
  font-size: 0.97rem;
}}

/* ── Tables ───────────────────────────────────────────────── */
.table-wrap {{ overflow-x: auto; }}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}}
thead th {{
  position: sticky;
  top: 42px;          /* below the nav */
  background: var(--bg-alt);
  border-bottom: 2px solid var(--border);
  padding: 0.55rem 0.75rem;
  text-align: left;
  font-weight: 600;
  white-space: nowrap;
}}
tbody tr:nth-child(even) {{ background: var(--bg-alt); }}
tbody tr:nth-child(odd)  {{ background: var(--bg); }}
tbody td {{
  padding: 0.45rem 0.75rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}}
.fail-row {{ background: #fff0f0 !important; border-left: 3px solid #dc2626; }}

/* ── Accuracy colour coding ───────────────────────────────── */
.acc-green  {{ background: #dcfce7; color: #166534; border-radius: 4px;
               padding: 2px 6px; font-weight: 600; white-space: nowrap; }}
.acc-amber  {{ background: #fef9c3; color: #713f12; border-radius: 4px;
               padding: 2px 6px; font-weight: 600; white-space: nowrap; }}
.acc-red    {{ background: #fee2e2; color: #991b1b; border-radius: 4px;
               padding: 2px 6px; font-weight: 600; white-space: nowrap; }}

/* ── Pass / fail badges ───────────────────────────────────── */
.badge-pass {{ color: #166534; font-weight: 700; }}
.badge-fail {{ color: #991b1b; font-weight: 700; }}

/* ── Gartner finding cards ────────────────────────────────── */
.findings-grid {{
  display: flex;
  flex-wrap: wrap;
  gap: 1.25rem;
}}
.finding-card {{
  flex: 1 1 280px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.1rem 1.2rem;
  background: var(--bg);
}}
.finding-card .pillar-badge {{
  display: inline-block;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 2px 8px;
  border-radius: 999px;
  margin-bottom: 0.5rem;
}}
.finding-card h3 {{ font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem; }}
.finding-card p  {{ font-size: 0.88rem; margin-bottom: 0.6rem; }}
.finding-card .evidence {{
  font-size: 0.8rem;
  color: var(--muted);
  font-style: italic;
  border-top: 1px solid var(--border);
  padding-top: 0.5rem;
  margin-top: 0.5rem;
}}

/* card colour variants */
.card-green {{ border-left: 4px solid #16a34a; }}
.card-amber {{ border-left: 4px solid #d97706; }}
.card-blue  {{ border-left: 4px solid #2563eb; }}
.badge-green {{ background: #dcfce7; color: #166534; }}
.badge-amber {{ background: #fef9c3; color: #713f12; }}
.badge-blue  {{ background: #dbeafe; color: #1e40af; }}

/* ── Variant drill-downs ──────────────────────────────────── */
.variant-details {{
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 1rem;
  overflow: hidden;
}}
.variant-details > summary {{
  cursor: pointer;
  list-style: none;
  padding: 0.8rem 1rem;
  background: var(--bg-alt);
  font-weight: 600;
  font-size: 0.97rem;
  border-bottom: 1px solid var(--border);
  user-select: none;
}}
.variant-details > summary::-webkit-details-marker {{ display: none; }}
.variant-details > summary::before {{
  content: "▶ ";
  font-size: 0.75rem;
  color: var(--muted);
}}
.variant-details[open] > summary {{ font-weight: 700; }}
.variant-details[open] > summary::before {{ content: "▼ "; }}
.variant-inner {{ padding: 1rem; }}

/* ── Config small table ───────────────────────────────────── */
.config-table {{ width: auto; margin-bottom: 1.2rem; font-size: 0.85rem; }}
.config-table th {{
  position: static;
  background: var(--bg-alt);
  font-weight: 600;
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--border);
}}
.config-table td {{
  padding: 0.3rem 0.7rem;
  border: 1px solid var(--border);
}}

/* ── Scenario table ───────────────────────────────────────── */
.scenario-section {{ margin-bottom: 1.5rem; }}
.scenario-section h4 {{ font-size: 0.92rem; font-weight: 600; margin-bottom: 0.5rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}

/* ── Trace collapsibles ───────────────────────────────────── */
.trace-row td {{ padding: 0 !important; background: #fafafa !important; }}
.trace-inner {{
  padding: 0.6rem 1rem 0.6rem 2.5rem;
  font-size: 0.82rem;
  color: var(--text);
  border-top: 1px dashed var(--border);
}}
.trace-inner strong {{ color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.04em; }}
.trace-inner p {{ margin: 0.2rem 0 0.5rem; }}
.trace-toggle {{
  background: none;
  border: none;
  color: var(--accent);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0;
  text-decoration: underline;
}}

/* ── Print ────────────────────────────────────────────────── */
@media print {{
  nav {{ position: static; }}
  details {{ display: block; }}
  details[open] {{ display: block; }}
  .variant-details > summary::before {{ content: ""; }}
}}

/* ── Mobile ───────────────────────────────────────────────── */
@media (max-width: 640px) {{
  .findings-grid {{ flex-direction: column; }}
  header h1 {{ font-size: 1.5rem; }}
}}
</style>
</head>
<body>

<!-- NAV -->
<nav>
  <div class="container">
    <a href="#scorecard">Scorecard</a>
    <a href="#findings">Findings</a>
    <a href="#variants">Variants</a>
  </div>
</nav>

<!-- HEADER -->
<header>
  <div class="container">
    <h1>Brian Caputo</h1>
    <p class="subtitle">ERP Agent Experimentation Lab &mdash; Phase 1: Three-Way Match</p>
    <p class="one-liner">Four variants, three Gartner findings, 120 invoices processed by an AI agent against a live Odoo ERP.</p>
  </div>
</header>

<div class="container">

<!-- SECTION 2: EXECUTIVE SUMMARY -->
<section>
  <h2>Executive Summary</h2>
  <div class="exec-summary">
    <p>An AI agent was tested on 120 vendor invoices across six failure-mode scenarios against a live Odoo 17 ERP, running a deterministic three-way match (PO &rarr; GR &rarr; invoice) with tool-use discipline &mdash; the math lives in code, the model orchestrates and narrates.</p>
    <p>Headline finding: Haiku 4.5 matches Sonnet 4.6 at 96.7% accuracy on the AP-clerk prompt at 3.2&times; lower cost and roughly half the latency; the only behavioral divergence between variants was caused by role framing, not model capability.</p>
    <p>All four variants were evaluated against Gartner&rsquo;s six pillars for trustworthy AI; three pillars produced measurable, reproducible findings.</p>
  </div>
</section>

<!-- SECTION 3: SCORECARD -->
<section id="scorecard">
  <h2>Scorecard</h2>
  <div class="table-wrap">
    <table id="scorecard-table">
      <thead>
        <tr>
          <th>Variant</th>
          <th>Model</th>
          <th>Role</th>
          <th>Matcher</th>
          <th>Accuracy</th>
          <th>Cost</th>
          <th>Avg Latency</th>
          <th>Avg Turns</th>
        </tr>
      </thead>
      <tbody id="scorecard-body"></tbody>
    </table>
  </div>
</section>

<!-- SECTION 4: GARTNER FINDINGS -->
<section id="findings">
  <h2>Gartner Pillar Findings</h2>
  <div class="findings-grid">

    <div class="finding-card card-green">
      <span class="pillar-badge badge-green">Reliability</span>
      <h3>Reliability</h3>
      <p>Haiku 4.5 matches Sonnet 4.6 at 96.7% accuracy on the same AP-clerk prompt, at 3.2&times; lower cost ($0.39 vs $1.26) and ~2&times; lower latency (~9s vs ~18s). Model selection is a cost lever, not an accuracy lever, for this task.</p>
      <p class="evidence">Baseline: 96.7% @ $1.26 &middot; Haiku AP: 96.7% @ $0.39</p>
    </div>

    <div class="finding-card card-amber">
      <span class="pillar-badge badge-amber">Fairness</span>
      <h3>Fairness</h3>
      <p>The CFO persona missed a duplicate invoice (BILL/2026/04/0029) that both AP-clerk variants caught. The miss traces to role framing &mdash; &ldquo;lead with dollar exposure&rdquo; de-weighted duplicate caution &mdash; not model capability. The Haiku AP control (same model, AP prompt) caught it correctly.</p>
      <p class="evidence">CFO Persona: 93.3% (1 duplicate miss) &middot; Haiku AP: 96.7% (0 duplicate misses)</p>
    </div>

    <div class="finding-card card-blue">
      <span class="pillar-badge badge-blue">Transparency</span>
      <h3>Transparency</h3>
      <p>The OR matcher (tight_tolerance) traded 1 true positive for 3 false positives on price_variance_ok scenarios. The AND&rarr;OR policy change is visible, measurable, and reversible &mdash; the audit trail shows exactly which invoices flipped and why.</p>
      <p class="evidence">AND (baseline): 5/5 price_variance_ok &middot; OR (tight_tolerance): 2/5 price_variance_ok</p>
    </div>

  </div>
</section>

<!-- SECTION 5: VARIANT DRILL-DOWNS -->
<section id="variants">
  <h2>Variant Drill-Downs</h2>
  <div id="variants-container"></div>
</section>

</div><!-- /.container -->

<!-- EMBEDDED DATA -->
<script id="DATA" type="application/json">
{data_json}
</script>

<script>
// ── Constants ──────────────────────────────────────────────────────────────────
const EXP_ORDER = ['baseline','tight_tolerance','cfo_persona','haiku_ap_persona'];

const VARIANT_LABELS = {{
  baseline:         'Baseline',
  tight_tolerance:  'Tight Tolerance (V1)',
  cfo_persona:      'CFO Persona (V2)',
  haiku_ap_persona: 'Haiku AP Control (V3)',
}};

const SCENARIO_ORDER = [
  'clean','duplicate','missing_gr',
  'price_variance_bad','price_variance_ok','qty_over_invoiced'
];

// ── Helpers ────────────────────────────────────────────────────────────────────
function modelLabel(m) {{
  if (m === 'claude-sonnet-4-6')           return 'Sonnet 4.6';
  if (m === 'claude-haiku-4-5-20251001')   return 'Haiku 4.5';
  return m;
}}

function roleLabel(cfg) {{
  return (cfg.agent && cfg.agent.system_prompt) ? 'CFO' : 'AP Clerk';
}}

function matcherLabel(cfg) {{
  if (cfg.env_overrides && cfg.env_overrides.PRICE_VARIANCE_LOGIC === 'or')
    return 'OR (audit)';
  return 'AND (default)';
}}

function accClass(acc) {{
  if (acc >= 0.95) return 'acc-green';
  if (acc >= 0.90) return 'acc-amber';
  return 'acc-red';
}}

function fmtAcc(summary) {{
  const pct  = (summary.totals.accuracy * 100).toFixed(1) + '%';
  const frac = summary.totals.decisions_correct + '/' + summary.totals.bills_completed;
  return pct + ' (' + frac + ')';
}}

function fmtCost(summary) {{
  return '$' + summary.totals_cost.cost_usd.toFixed(2);
}}

function fmtLatency(summary) {{
  return '~' + Math.round(summary.averages.latency_ms / 1000) + 's';
}}

function fmtTurns(summary) {{
  return summary.averages.turns.toFixed(1);
}}

function fmtDecisions(decisions) {{
  const parts = [];
  if (decisions.approve)          parts.push('approve: ' + decisions.approve);
  if (decisions.route_for_review) parts.push('route: '   + decisions.route_for_review);
  if (decisions.block)            parts.push('block: '   + decisions.block);
  return parts.join(', ') || '—';
}}

function esc(s) {{
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}}

// ── Parse data ─────────────────────────────────────────────────────────────────
const DATA = JSON.parse(document.getElementById('DATA').textContent);

// ── Section 3: Scorecard ───────────────────────────────────────────────────────
function buildScorecard() {{
  const tbody = document.getElementById('scorecard-body');
  EXP_ORDER.forEach(key => {{
    const {{ summary }} = DATA[key];
    const cfg = summary.config;
    const tr = document.createElement('tr');
    const acc = summary.totals.accuracy;
    tr.innerHTML = `
      <td><strong>${{esc(VARIANT_LABELS[key])}}</strong></td>
      <td>${{esc(modelLabel(cfg.agent.model))}}</td>
      <td>${{esc(roleLabel(cfg))}}</td>
      <td>${{esc(matcherLabel(cfg))}}</td>
      <td><span class="${{accClass(acc)}}">${{esc(fmtAcc(summary))}}</span></td>
      <td>${{esc(fmtCost(summary))}}</td>
      <td>${{esc(fmtLatency(summary))}}</td>
      <td>${{esc(fmtTurns(summary))}}</td>
    `;
    tbody.appendChild(tr);
  }});
}}

// ── Section 5: Variant drill-downs ─────────────────────────────────────────────
function buildVariants() {{
  const container = document.getElementById('variants-container');

  EXP_ORDER.forEach(key => {{
    const {{ summary, runs }} = DATA[key];
    const cfg = summary.config;
    const acc = summary.totals.accuracy;

    // ── <details> wrapper ──────────────────────────────────────────────────────
    const details = document.createElement('details');
    details.className = 'variant-details';

    const summaryEl = document.createElement('summary');
    summaryEl.textContent =
      VARIANT_LABELS[key] + ' — ' + modelLabel(cfg.agent.model) +
      ' — ' + (acc * 100).toFixed(1) + '%';
    details.appendChild(summaryEl);

    const inner = document.createElement('div');
    inner.className = 'variant-inner';

    // ── 5a Config table ────────────────────────────────────────────────────────
    inner.innerHTML += `
      <div class="scenario-section">
        <h4>Configuration</h4>
        <table class="config-table">
          <thead><tr><th>Model</th><th>Role</th><th>Matcher</th><th>Sample</th><th>Seed</th></tr></thead>
          <tbody>
            <tr>
              <td>${{esc(modelLabel(cfg.agent.model))}}</td>
              <td>${{esc(roleLabel(cfg))}}</td>
              <td>${{esc(matcherLabel(cfg))}}</td>
              <td>${{summary.totals.bills_completed}}</td>
              <td>${{cfg.sample.seed}}</td>
            </tr>
          </tbody>
        </table>
      </div>
    `;

    // ── 5b Scenario breakdown ──────────────────────────────────────────────────
    let scenRows = '';
    SCENARIO_ORDER.forEach(sc => {{
      const s = summary.by_scenario[sc];
      if (!s) return;
      const cls = accClass(s.accuracy);
      scenRows += `
        <tr>
          <td>${{esc(sc)}}</td>
          <td>${{s.n}}</td>
          <td>${{s.correct}}</td>
          <td><span class="${{cls}}">${{(s.accuracy*100).toFixed(0)}}%</span></td>
          <td>${{esc(fmtDecisions(s.decisions))}}</td>
        </tr>
      `;
    }});

    inner.innerHTML += `
      <div class="scenario-section">
        <h4>Scenario Breakdown</h4>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Scenario</th><th>N</th><th>Correct</th><th>Accuracy</th><th>Decisions</th></tr></thead>
            <tbody>${{scenRows}}</tbody>
          </table>
        </div>
      </div>
    `;

    // ── 5c + 5d Per-invoice table ──────────────────────────────────────────────
    // Sort: mismatches first, then alpha by bill_name
    const sorted = [...runs].sort((a, b) => {{
      const af = a.decision_match === false ? 0 : 1;
      const bf = b.decision_match === false ? 0 : 1;
      if (af !== bf) return af - bf;
      return (a.bill_name || '').localeCompare(b.bill_name || '');
    }});

    const invTbody = document.createElement('tbody');
    sorted.forEach((run, idx) => {{
      const fail  = run.decision_match === false;
      const rowId = key + '_row_' + idx;
      const traceId = key + '_trace_' + idx;

      const tr = document.createElement('tr');
      if (fail) tr.className = 'fail-row';

      const matchBadge = fail
        ? '<span class="badge-fail">FAIL</span>'
        : '<span class="badge-pass">PASS</span>';

      const latSec = run.latency_ms != null
        ? '~' + Math.round(run.latency_ms / 1000) + 's'
        : '—';
      const cost = run.cost_usd != null
        ? '$' + run.cost_usd.toFixed(4)
        : '—';

      tr.innerHTML = `
        <td>${{esc(run.bill_name || '—')}}</td>
        <td>${{esc(run.scenario_type || '—')}}</td>
        <td>${{esc(run.expected_outcome || '—')}}</td>
        <td>${{esc(run.decision || '—')}}</td>
        <td>
          ${{matchBadge}}
          <button class="trace-toggle" onclick="toggleTrace('${{traceId}}')">&#9656; trace</button>
        </td>
        <td>${{cost}}</td>
        <td>${{latSec}}</td>
      `;
      invTbody.appendChild(tr);

      // trace row
      const traceTr = document.createElement('tr');
      traceTr.id = traceId;
      traceTr.className = 'trace-row';
      traceTr.style.display = 'none';

      const discrepancies = (run.discrepancy_codes && run.discrepancy_codes.length)
        ? run.discrepancy_codes.join(', ')
        : 'none';

      const rationale = esc(run.rationale || '—');

      traceTr.innerHTML = `
        <td colspan="7">
          <div class="trace-inner">
            <strong>Rationale</strong>
            <p>${{rationale}}</p>
            <strong>Discrepancies</strong>
            <p>${{esc(discrepancies)}}</p>
            <strong>Turns: ${{run.turns}} &nbsp;|&nbsp; Tool calls: ${{run.tool_calls}}</strong>
          </div>
        </td>
      `;
      invTbody.appendChild(traceTr);
    }});

    const invTable = document.createElement('table');
    invTable.innerHTML = `
      <thead>
        <tr>
          <th>Bill</th><th>Scenario</th><th>Expected</th>
          <th>Decision</th><th>Match</th><th>Cost</th><th>Latency</th>
        </tr>
      </thead>
    `;
    invTable.appendChild(invTbody);

    const invWrap = document.createElement('div');
    invWrap.className = 'scenario-section';
    invWrap.innerHTML = '<h4>Per-Invoice Results</h4>';
    const tableWrap = document.createElement('div');
    tableWrap.className = 'table-wrap';
    tableWrap.appendChild(invTable);
    invWrap.appendChild(tableWrap);

    inner.appendChild(invWrap);
    details.appendChild(inner);
    container.appendChild(details);
  }});
}}

function toggleTrace(id) {{
  const row = document.getElementById(id);
  if (!row) return;
  row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
}}

// ── Bootstrap ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  buildScorecard();
  buildVariants();
}});
</script>
</body>
</html>
"""

# ── Write output ───────────────────────────────────────────────────────────────
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE.write_text(HTML, encoding="utf-8")
print(f"Written: {OUT_FILE}")
print(f"Size:    {OUT_FILE.stat().st_size:,} bytes")
