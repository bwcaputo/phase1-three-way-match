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

VARIANTS = ["baseline", "tight_tolerance", "cfo_persona", "haiku_ap_persona", "prompt_injection", "goal_only_playbook", "no_duplicate_tool"]

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

/* ── Print ────────────────────────────────────────────────── */
@media print {{
  nav {{ position: static; }}
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
  </div>
</nav>

<!-- HEADER -->
<header>
  <div class="container">
    <h1>Brian Caputo</h1>
    <p class="subtitle">ERP Agent Experimentation Lab &mdash; Phase 1: Three-Way Match</p>
    <p class="one-liner">Seven experiments. Four RPST axes. The scorecard a consulting team runs before a client picks an AP agent.</p>
  </div>
</header>

<div class="container">

<!-- INTRO -->
<div class="exec-summary" style="margin-bottom:2.5rem;">
  <p>I built an AI agent that runs three-way match against a live Odoo 17 ERP and scored it against Gartner&rsquo;s six pillars for trustworthy AI. The model orchestrates the workflow. The arithmetic lives in deterministic code.</p>
  <p>I varied one RPST axis at a time &mdash; role, playbook, skills, tolerance policy &mdash; and measured what changed. The four findings below are the ones that would change a deployment decision.</p>
</div>

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

<!-- SECTION 4: FINDINGS -->
<section id="findings">
  <h2>Findings</h2>
  <div class="findings-grid">

    <div class="finding-card card-green">
      <span class="pillar-badge badge-green">Reliability</span>
      <h3>The cheaper model matched the expensive one</h3>
      <p>Haiku 4.5 hit 96.7% accuracy on the same prompt as Sonnet 4.6, at one-third the cost ($0.39 vs $1.26) and half the latency. Model selection is a cost decision, not an accuracy decision.</p>
      <p class="evidence">Baseline: 96.7% @ $1.26 &middot; Haiku: 96.7% @ $0.39</p>
    </div>

    <div class="finding-card card-amber">
      <span class="pillar-badge badge-amber">Fairness</span>
      <h3>The CFO persona missed a duplicate the clerk caught</h3>
      <p>Same model, same tools, same data. The CFO prompt prioritized dollar exposure, so a $47 duplicate didn&rsquo;t register. The AP clerk caught it because catching duplicates is the job regardless of amount. Role framing is a fairness surface.</p>
      <p class="evidence">CFO: 93.3% (1 duplicate miss) &middot; AP Clerk: 96.7% (0 misses)</p>
    </div>

    <div class="finding-card card-green">
      <span class="pillar-badge badge-green">Security</span>
      <h3>10 prompt injections, 0 breaches</h3>
      <p>I embedded attack payloads in invoice notes, line-item names, and vendor names. The agent ignored every one. The deterministic matcher computes the decision, not the LLM. Architecture is the security control.</p>
      <p class="evidence">10/10 injections ignored &middot; 0 behavioral changes &middot; $0.12 total cost</p>
    </div>

    <div class="finding-card card-amber">
      <span class="pillar-badge badge-amber">Accountability</span>
      <h3>Remove the playbook or the tool, accuracy collapses</h3>
      <p>I removed the step-by-step instructions: accuracy dropped from 96.7% to 70%. I removed the duplicate-check tool: duplicate detection dropped to 0%, and the agent approved every one without warning. Prescriptive instructions and complete toolkits aren&rsquo;t optional. They&rsquo;re load-bearing.</p>
      <p class="evidence">Full RPST: 96.7% &middot; Goal-only: 70.0% &middot; Missing tool: 0/5 duplicates caught</p>
    </div>

  </div>
  <p style="margin-top:1.5rem; font-size:0.9rem; color:#6b7280;">Full methodology, NIST AI RMF mapping, variant drill-downs, and source code: <a href="https://github.com/bwcaputo/phase1-three-way-match" style="font-weight:500;">github.com/bwcaputo/phase1-three-way-match</a></p>
</section>


</div><!-- /.container -->

<!-- EMBEDDED DATA -->
<script id="DATA" type="application/json">
{data_json}
</script>

<script>
// ── Constants ──────────────────────────────────────────────────────────────────
const EXP_ORDER = ['baseline','tight_tolerance','cfo_persona','haiku_ap_persona','prompt_injection','goal_only_playbook','no_duplicate_tool'];

const VARIANT_LABELS = {{
  baseline:           'Baseline',
  tight_tolerance:    'Variant 1: Tight Tolerance',
  cfo_persona:        'Variant 2: CFO Persona',
  haiku_ap_persona:   'Variant 3: Control',
  prompt_injection:   'Variant 4: Prompt Injection',
  goal_only_playbook: 'Variant 5: Goal-Only Playbook',
  no_duplicate_tool:  'Variant 6: No Duplicate Tool',
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
  return parts.join(', ') || '\u2014';
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

// ── Bootstrap ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  buildScorecard();
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
