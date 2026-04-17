"""
app.py -- Flask web UI for the Three-Way Match Experimentation Lab.

Pages:
  GET  /                          Dashboard: stat cards, variants table, scenario matrix
  GET  /experiment/<name>         Detail: summary cards, per-scenario table, invoice cards
  GET  /run                       Run form: pick config, optional seed
  POST /run                       Redirect to streaming page
  GET  /run/stream                SSE: stream subprocess output

Usage:
  python app.py
  python app.py --port 5001
  python app.py --host 0.0.0.0 --port 8080 --debug
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from flask import Flask, Response, abort, redirect, render_template_string, request, url_for

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parent
EXPERIMENTS = REPO_ROOT / "experiments"
CONFIGS_DIR = EXPERIMENTS / "configs"
GITHUB_REPO = "https://github.com/bwcaputo/phase1-three-way-match"
GITHUB_PAGES_VIEWER = f"{GITHUB_REPO}/blob/main/docs/viewer/index.html"

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Variant metadata
# ---------------------------------------------------------------------------

VARIANT_DISPLAY = {
    "baseline":            ("Baseline (Sonnet 4.6)",    "—"),
    "tight_tolerance":     ("Tight Tolerance (OR Logic)", "Policy"),
    "cfo_persona":         ("CFO Persona",              "Role"),
    "haiku_ap_persona":    ("AP Clerk Control (Haiku)", "Role + Model"),
    "prompt_injection":    ("Prompt Injection Test",    "Security"),
    "goal_only_playbook":  ("Goal-Only Playbook",       "Playbook"),
    "no_duplicate_tool":   ("No Duplicate Tool",        "Skills/Tools"),
}


def _display_name(variant: str) -> str:
    if variant in VARIANT_DISPLAY:
        return VARIANT_DISPLAY[variant][0]
    return variant.replace("_", " ").title()


def _rpst_axis(variant: str) -> str:
    if variant in VARIANT_DISPLAY:
        return VARIANT_DISPLAY[variant][1]
    return "—"


# ---------------------------------------------------------------------------
# Accuracy colour helpers
# ---------------------------------------------------------------------------

def _acc_bg(pct: float) -> str:
    """Background colour based on accuracy thresholds."""
    if pct >= 95:
        return "#dcfce7"  # green
    if pct >= 80:
        return "#fef9c3"  # yellow
    return "#fee2e2"      # red


def _acc_text(pct: float) -> str:
    if pct >= 95:
        return "#166534"
    if pct >= 80:
        return "#713f12"
    return "#991b1b"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _load_summary(variant_dir: Path) -> dict | None:
    p = variant_dir / "summary.json"
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_runs(variant_dir: Path) -> list[dict]:
    p = variant_dir / "runs.jsonl"
    if not p.exists():
        return []
    rows: list[dict] = []
    try:
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception:
        pass
    return rows


def _discover_variants() -> list[str]:
    """Canonical variant dirs only (no _seed sub-runs)."""
    return sorted(
        d.name for d in EXPERIMENTS.iterdir()
        if d.is_dir()
        and (d / "summary.json").exists()
        and "_seed" not in d.name
        and d.name not in ("configs",)
    )


def _discover_configs() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


def _strip_emoji(text: str) -> str:
    """Remove emoji characters for safe HTML display (optional — browser handles them fine)."""
    return text


def _short_model(model: str) -> str:
    return (model
            .replace("claude-haiku-4-5-20251001", "Haiku 4.5")
            .replace("claude-sonnet-4-6", "Sonnet 4.6")
            .replace("claude-opus-4-6", "Opus 4.6"))

# ---------------------------------------------------------------------------
# Design system CSS  (shared across all pages)
# ---------------------------------------------------------------------------

DESIGN_CSS = """
/* ── Reset ──────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

/* ── Tokens ─────────────────────────────────────────────────────── */
:root {
  --accent:       #2563eb;
  --accent-hover: #1d4ed8;
  --text:         #111827;
  --muted:        #6b7280;
  --subtle:       #9ca3af;
  --border:       #e5e7eb;
  --bg:           #ffffff;
  --bg-alt:       #f9fafb;
  --shadow-sm:    0 1px 3px rgba(0,0,0,.08);
  --shadow-md:    0 4px 12px rgba(0,0,0,.10);
  --radius:       8px;
  --radius-sm:    4px;
}

/* ── Base ────────────────────────────────────────────────────────── */
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--text);
  background: var(--bg-alt);
  line-height: 1.6;
  font-size: 15px;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  font-family: "SF Mono", "Fira Code", Consolas, monospace;
  font-size: 0.85em;
  background: #f3f4f6;
  padding: 1px 5px;
  border-radius: 3px;
}

/* ── Layout ──────────────────────────────────────────────────────── */
.page-wrap {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 1.25rem;
  width: 100%;
}
main { flex: 1; padding: 2rem 0 3rem; }

/* ── Nav ─────────────────────────────────────────────────────────── */
.nav {
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
  position: sticky;
  top: 0;
  z-index: 200;
}
.nav-inner {
  display: flex;
  align-items: center;
  gap: 0;
  height: 54px;
}
.nav-brand {
  font-weight: 700;
  font-size: 0.95rem;
  color: var(--text);
  margin-right: auto;
  letter-spacing: -0.01em;
}
.nav-brand span { color: var(--accent); }
.nav-links { display: flex; gap: 0.25rem; }
.nav-link {
  padding: 0.4rem 0.8rem;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--muted);
  transition: background 0.15s, color 0.15s;
}
.nav-link:hover { background: var(--bg-alt); color: var(--text); text-decoration: none; }
.nav-link.active { background: #eff6ff; color: var(--accent); }
.nav-external::after { content: " ↗"; font-size: 0.75rem; }

/* ── Page header ─────────────────────────────────────────────────── */
.page-header {
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: 1.75rem 0 1.5rem;
  margin-bottom: 2rem;
}
.page-header h1 {
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.25;
}
.page-header .subtitle {
  font-size: 0.9rem;
  color: var(--muted);
  margin-top: 0.3rem;
}

/* ── Cards ───────────────────────────────────────────────────────── */
.card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1.25rem 1.5rem;
}

/* ── Stat card row ───────────────────────────────────────────────── */
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}
.stat-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1.25rem 1.5rem;
}
.stat-card .stat-value {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--text);
  line-height: 1;
}
.stat-card .stat-label {
  font-size: 0.8rem;
  color: var(--muted);
  margin-top: 0.35rem;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* ── Section ─────────────────────────────────────────────────────── */
.section { margin-bottom: 2.5rem; }
.section-head {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  margin-bottom: 0.9rem;
}
.section-head h2 {
  font-size: 1rem;
  font-weight: 700;
  color: var(--text);
}
.section-head .section-sub {
  font-size: 0.8rem;
  color: var(--muted);
}

/* ── Tables ──────────────────────────────────────────────────────── */
.table-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.86rem; }
thead th {
  background: var(--bg-alt);
  border-bottom: 1px solid var(--border);
  padding: 0.55rem 0.85rem;
  text-align: left;
  font-weight: 600;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  white-space: nowrap;
}
tbody tr { transition: background 0.1s; }
tbody tr:hover td { background: #f0f6ff !important; }
tbody td {
  padding: 0.55rem 0.85rem;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
tbody tr:last-child td { border-bottom: none; }

/* ── Accuracy chip ───────────────────────────────────────────────── */
.acc-chip {
  display: inline-block;
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  font-weight: 700;
  font-size: 0.82rem;
  white-space: nowrap;
}
.acc-cell {
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  font-weight: 700;
  font-size: 0.82rem;
  display: inline-block;
  white-space: nowrap;
}

/* ── Badges / pills ──────────────────────────────────────────────── */
.badge {
  display: inline-block;
  border-radius: 99px;
  padding: 2px 10px;
  font-size: 0.75rem;
  font-weight: 700;
  white-space: nowrap;
}
.badge-pass   { background: #dcfce7; color: #166534; }
.badge-fail   { background: #fee2e2; color: #991b1b; }
.badge-muted  { background: #f3f4f6; color: var(--muted); }
.pill-scenario {
  display: inline-block;
  background: #dbeafe;
  color: #1e40af;
  border-radius: 99px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 500;
}
.pill-axis {
  display: inline-block;
  background: #f3e8ff;
  color: #6d28d9;
  border-radius: 99px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 500;
}
.pill-axis-dash {
  display: inline-block;
  background: #f3f4f6;
  color: var(--muted);
  border-radius: 99px;
  padding: 1px 8px;
  font-size: 0.75rem;
  font-weight: 500;
}
.decision-approve { color: #166534; font-weight: 600; }
.decision-route   { color: #713f12; font-weight: 600; }
.decision-block   { color: #991b1b; font-weight: 600; }

/* ── Invoice run cards ───────────────────────────────────────────── */
.run-cards { display: flex; flex-direction: column; gap: 0.75rem; }
.run-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.run-card.run-fail { border-left: 3px solid #dc2626; }
.run-card.run-pass { border-left: 3px solid #16a34a; }
.run-card-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.7rem 1rem;
  cursor: pointer;
  user-select: none;
  list-style: none;
}
.run-card-header::-webkit-details-marker { display: none; }
.run-card-header:hover { background: #fafafa; }
.run-meta { display: flex; align-items: center; gap: 0.6rem; flex: 1; flex-wrap: wrap; }
.run-invoice { font-weight: 600; font-size: 0.875rem; color: var(--text); }
.run-stats   { font-size: 0.78rem; color: var(--muted); margin-left: auto; white-space: nowrap; }
.run-decision { font-size: 0.82rem; }
.run-detail {
  padding: 0.75rem 1rem 1rem;
  border-top: 1px solid var(--border);
  background: var(--bg-alt);
}
.run-detail-label {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 0.35rem;
}
.run-rationale {
  font-size: 0.86rem;
  line-height: 1.5;
  color: var(--text);
}
.run-summary-md {
  font-size: 0.82rem;
  line-height: 1.55;
  color: #374151;
  white-space: pre-wrap;
  word-break: break-word;
  margin-top: 0.5rem;
  max-height: 280px;
  overflow-y: auto;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.6rem 0.75rem;
}

/* ── Forms ───────────────────────────────────────────────────────── */
.form-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 2rem;
  max-width: 520px;
}
.form-group { margin-bottom: 1.25rem; }
label {
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 0.4rem;
  color: var(--text);
}
select, input[type="number"], input[type="text"] {
  width: 100%;
  padding: 0.5rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  background: var(--bg);
  color: var(--text);
  transition: border-color 0.15s, box-shadow 0.15s;
}
select:focus, input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
}
.help-text { font-size: 0.78rem; color: var(--muted); margin-top: 0.3rem; }

/* ── Buttons ─────────────────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 1.25rem;
  border-radius: var(--radius-sm);
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  border: none;
  text-decoration: none;
  transition: background 0.15s, box-shadow 0.15s;
}
.btn-primary {
  background: var(--accent);
  color: #fff;
  box-shadow: 0 1px 2px rgba(0,0,0,.12);
}
.btn-primary:hover { background: var(--accent-hover); text-decoration: none; color: #fff; }
.btn-secondary {
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
}
.btn-secondary:hover { background: var(--bg-alt); text-decoration: none; }

/* ── Alerts ──────────────────────────────────────────────────────── */
.alert {
  display: flex;
  gap: 0.75rem;
  padding: 0.85rem 1rem;
  border-radius: var(--radius);
  font-size: 0.875rem;
  margin-bottom: 1.25rem;
  border: 1px solid transparent;
}
.alert-icon { font-size: 1.1rem; flex-shrink: 0; line-height: 1.6; }
.alert-warn  { background: #fefce8; border-color: #fde68a; color: #713f12; }
.alert-error { background: #fef2f2; border-color: #fca5a5; color: #991b1b; }
.alert-info  { background: #eff6ff; border-color: #bfdbfe; color: #1e40af; }

/* ── Progress / streaming ────────────────────────────────────────── */
@keyframes spin { to { transform: rotate(360deg); } }
.spinner {
  width: 20px; height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  display: inline-block;
  vertical-align: middle;
}
.stream-card {
  background: #0f172a;
  border-radius: var(--radius);
  padding: 1.25rem;
  min-height: 200px;
  max-height: 520px;
  overflow-y: auto;
}
.stream-line {
  font-family: "SF Mono", "Fira Code", Consolas, monospace;
  font-size: 0.78rem;
  color: #a7f3d0;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ── Footer ──────────────────────────────────────────────────────── */
.footer {
  background: var(--bg);
  border-top: 1px solid var(--border);
  padding: 1.25rem 0;
}
.footer-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.8rem;
  color: var(--muted);
  gap: 1rem;
  flex-wrap: wrap;
}
.footer a { color: var(--muted); }
.footer a:hover { color: var(--text); }

/* ── Scenario matrix empty cell ──────────────────────────────────── */
.sc-empty { color: var(--subtle); font-size: 0.78rem; }

/* ── Back breadcrumb ─────────────────────────────────────────────── */
.breadcrumb { font-size: 0.82rem; color: var(--muted); margin-bottom: 0.5rem; }
.breadcrumb a { color: var(--muted); }
.breadcrumb a:hover { color: var(--text); }

/* ── Responsive ──────────────────────────────────────────────────── */
@media (max-width: 640px) {
  .page-header h1 { font-size: 1.3rem; }
  .stat-card .stat-value { font-size: 1.5rem; }
  .run-stats { display: none; }
  .footer-inner { flex-direction: column; gap: 0.5rem; }
}
"""

# ---------------------------------------------------------------------------
# Base template (nav + footer wrappers)
# ---------------------------------------------------------------------------

def _base(title: str, body: str, active: str = "") -> str:
    nav_links = [
        ("Dashboard",    "/",             "dashboard"),
        ("Run Experiment", "/run",        "run"),
        ("Scorecard ↗",  GITHUB_PAGES_VIEWER, "scorecard"),
    ]
    links_html = ""
    for label, href, key in nav_links:
        cls = "nav-link"
        if key == active:
            cls += " active"
        if "↗" in label:
            cls += " nav-external"
            links_html += f'<a class="{cls}" href="{href}" target="_blank">{label.replace(" ↗","")}</a>'
        else:
            links_html += f'<a class="{cls}" href="{href}">{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — AP Agent Lab</title>
<style>{DESIGN_CSS}</style>
</head>
<body>
<div class="page-wrap">
  <nav class="nav">
    <div class="container nav-inner">
      <span class="nav-brand">AP <span>Agent</span> Lab</span>
      <div class="nav-links">{links_html}</div>
    </div>
  </nav>
  {body}
  <footer class="footer">
    <div class="container footer-inner">
      <span>Built by <a href="https://linkedin.com/in/briancaputo" target="_blank">Brian Caputo</a>
        &middot; <a href="{GITHUB_REPO}" target="_blank">Source on GitHub</a></span>
      <span>Powered by Claude, Odoo 17, and labeled ground truth</span>
    </div>
  </footer>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _sort_variants(variants: list[dict]) -> list[dict]:
    """baseline first, then by accuracy descending."""
    baseline = [v for v in variants if v["name"] == "baseline"]
    rest = sorted(
        [v for v in variants if v["name"] != "baseline"],
        key=lambda x: x["acc_raw"],
        reverse=True,
    )
    return baseline + rest


@app.route("/")
def dashboard():
    variant_names = _discover_variants()
    variants: list[dict] = []
    summaries: dict[str, dict] = {}
    all_scenarios: set[str] = set()

    for name in variant_names:
        s = _load_summary(EXPERIMENTS / name)
        if not s:
            continue
        summaries[name] = s
        totals  = s.get("totals", {})
        avgs    = s.get("averages", {})
        tc      = s.get("totals_cost", {})
        acc_raw = (totals.get("accuracy") or 0.0) * 100
        model   = _short_model(s.get("model") or "?")
        cost    = tc.get("cost_usd", 0.0)
        lat     = (avgs.get("latency_ms") or 0.0) / 1000.0
        variants.append({
            "name":    name,
            "display": _display_name(name),
            "axis":    _rpst_axis(name),
            "model":   model,
            "acc_raw": acc_raw,
            "acc_bg":  _acc_bg(acc_raw),
            "acc_fg":  _acc_text(acc_raw),
            "acc_pct": f"{acc_raw:.1f}%",
            "cost":    f"${cost:.2f}",
            "turns":   f"{(avgs.get('turns') or 0.0):.1f}",
            "tools":   f"{(avgs.get('tool_calls') or 0.0):.1f}",
            "latency": f"{lat:.1f}s",
        })
        for sc in s.get("by_scenario", {}).keys():
            all_scenarios.add(sc)

    variants = _sort_variants(variants)
    total_bills = sum(summaries[n].get("totals", {}).get("bills_attempted", 0) for n in summaries)
    total_cost  = sum(summaries[n].get("totals_cost", {}).get("cost_usd", 0.0) for n in summaries)

    # ── Stat cards ──
    stat_cards_html = f"""
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-value">{len(variants)}</div>
        <div class="stat-label">Variants</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{total_bills:,}</div>
        <div class="stat-label">Invoices Evaluated</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">${total_cost:.2f}</div>
        <div class="stat-label">Total API Spend</div>
      </div>
    </div>"""

    # ── Variants table ──
    rows_html = ""
    for v in variants:
        axis_pill = (
            f'<span class="pill-axis">{v["axis"]}</span>'
            if v["axis"] != "—"
            else '<span class="pill-axis-dash">—</span>'
        )
        rows_html += f"""
        <tr>
          <td><a href="/experiment/{v['name']}">{v['display']}</a></td>
          <td>{axis_pill}</td>
          <td><code style="font-size:0.8rem">{v['model']}</code></td>
          <td>
            <span class="acc-chip"
                  style="background:{v['acc_bg']};color:{v['acc_fg']}">
              {v['acc_pct']}
            </span>
          </td>
          <td style="color:var(--muted)">{v['cost']}</td>
          <td style="color:var(--muted)">{v['turns']}</td>
          <td style="color:var(--muted)">{v['tools']}</td>
          <td style="color:var(--muted)">{v['latency']}</td>
        </tr>"""

    variants_table_html = f"""
    <div class="section">
      <div class="section-head"><h2>Variants</h2></div>
      <div class="table-card">
        <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Variant</th>
              <th>RPST Axis</th>
              <th>Model</th>
              <th>Accuracy</th>
              <th>Cost</th>
              <th>Avg Turns</th>
              <th>Avg Tools</th>
              <th>Latency</th>
            </tr>
          </thead>
          <tbody>{rows_html}</tbody>
        </table>
        </div>
      </div>
    </div>"""

    # ── Scenario matrix ──
    scenario_matrix_html = ""
    if all_scenarios:
        # Header row uses short variant names
        th_cells = "".join(
            f'<th style="max-width:120px;overflow:hidden">{v["display"]}</th>'
            for v in variants
        )
        sc_rows = ""
        for sc in sorted(all_scenarios):
            cells = ""
            for v in variants:
                sc_data = summaries.get(v["name"], {}).get("by_scenario", {}).get(sc)
                if sc_data is None:
                    cells += '<td><span class="sc-empty">—</span></td>'
                else:
                    acc_frac = sc_data.get("accuracy")
                    pct = (acc_frac * 100) if acc_frac is not None else 0.0
                    cells += (
                        f'<td><span class="acc-cell" '
                        f'style="background:{_acc_bg(pct)};color:{_acc_text(pct)}">'
                        f'{pct:.0f}%</span></td>'
                    )
            sc_rows += f"<tr><td><span class='pill-scenario'>{sc}</span></td>{cells}</tr>"

        scenario_matrix_html = f"""
        <div class="section">
          <div class="section-head">
            <h2>Scenario Breakdown</h2>
            <span class="section-sub">Accuracy % by scenario type across all variants</span>
          </div>
          <div class="table-card">
            <div class="table-wrap">
            <table>
              <thead><tr><th>Scenario</th>{th_cells}</tr></thead>
              <tbody>{sc_rows}</tbody>
            </table>
            </div>
          </div>
        </div>"""

    body = f"""
  <div style="background:var(--bg);border-bottom:1px solid var(--border);padding:1.75rem 0 1.5rem;margin-bottom:2rem;">
    <div class="container">
      <h1 style="font-size:1.6rem;font-weight:700;letter-spacing:-0.02em">ERP Agent Experimentation Lab</h1>
      <p style="color:var(--muted);font-size:0.9rem;margin-top:0.3rem">
        Three-way match agent evaluated against a live Odoo 17 ERP
      </p>
    </div>
  </div>
  <main>
    <div class="container">
      {stat_cards_html}
      {variants_table_html}
      {scenario_matrix_html}
    </div>
  </main>"""

    return _base("Dashboard", body, active="dashboard")


# ---------------------------------------------------------------------------
# Experiment detail
# ---------------------------------------------------------------------------

def _decision_html(decision: str) -> str:
    d = (decision or "").lower()
    if "approve" in d:
        return f'<span class="decision-approve">{decision}</span>'
    if "route" in d:
        return f'<span class="decision-route">{decision}</span>'
    if "block" in d:
        return f'<span class="decision-block">{decision}</span>'
    return f'<span>{decision}</span>'


@app.route("/experiment/<name>")
def experiment_detail(name: str):
    variant_dir = EXPERIMENTS / name
    s = _load_summary(variant_dir)
    if s is None:
        abort(404)

    totals  = s.get("totals", {})
    avgs    = s.get("averages", {})
    tc      = s.get("totals_cost", {})
    acc_raw = (totals.get("accuracy") or 0.0) * 100
    model   = _short_model(s.get("model") or "?")
    display = _display_name(name)
    axis    = _rpst_axis(name)
    cost    = tc.get("cost_usd", 0.0)

    # ── Summary stat cards ──
    stat_items = [
        ("Accuracy",       f'<span class="acc-chip" style="background:{_acc_bg(acc_raw)};color:{_acc_text(acc_raw)}">{acc_raw:.1f}%</span>'),
        ("Cost",           f"${cost:.3f}"),
        ("Avg Turns",      f"{(avgs.get('turns') or 0.0):.1f}"),
        ("Avg Tool Calls", f"{(avgs.get('tool_calls') or 0.0):.1f}"),
        ("Avg Latency",    f"{(avgs.get('latency_ms') or 0.0)/1000:.1f}s"),
        ("Bills",          f"{totals.get('bills_attempted',0)} attempted / {totals.get('bills_completed',0)} completed"),
    ]
    stat_cards_html = '<div class="stat-row">' + "".join(
        f'<div class="stat-card"><div class="stat-value" style="font-size:1.35rem">{val}</div>'
        f'<div class="stat-label">{label}</div></div>'
        for label, val in stat_items
    ) + "</div>"

    # ── Scenario breakdown ──
    by_sc = s.get("by_scenario") or {}
    sc_rows = ""
    for sc_name, sc_data in sorted(by_sc.items()):
        acc_frac = sc_data.get("accuracy")
        n        = sc_data.get("n", sc_data.get("total", 0))
        correct  = sc_data.get("correct", 0)
        pct      = (acc_frac * 100) if acc_frac is not None else ((correct / n * 100) if n else 0.0)
        sc_rows += (
            f"<tr>"
            f"<td><span class='pill-scenario'>{sc_name}</span></td>"
            f"<td><span class='acc-chip' style='background:{_acc_bg(pct)};color:{_acc_text(pct)}'>"
            f"{pct:.1f}%</span></td>"
            f"<td>{n}</td>"
            f"<td>{correct}</td>"
            f"</tr>"
        )
    sc_table_html = ""
    if sc_rows:
        sc_table_html = f"""
        <div class="section">
          <div class="section-head"><h2>By Scenario</h2></div>
          <div class="table-card">
            <div class="table-wrap">
            <table>
              <thead><tr><th>Scenario</th><th>Accuracy</th><th>N</th><th>Correct</th></tr></thead>
              <tbody>{sc_rows}</tbody>
            </table>
            </div>
          </div>
        </div>"""

    # ── Invoice run cards ──
    raw_runs = _load_runs(variant_dir)
    run_cards_html = ""
    if raw_runs:
        cards = ""
        for i, r in enumerate(raw_runs):
            invoice    = r.get("bill_name") or r.get("invoice_number") or r.get("invoice", "?")
            scenario   = r.get("scenario_type") or r.get("scenario", "?")
            expected   = r.get("expected_outcome") or r.get("expected_action") or r.get("expected", "?")
            got        = r.get("decision") or r.get("recommended_action") or r.get("got", "?")
            correct    = r.get("decision_match") if "decision_match" in r else r.get("correct", False)
            turns      = r.get("turns", "?")
            tools      = r.get("tool_calls", "?")
            lat        = r.get("latency_ms", 0)
            err        = r.get("error") or ""
            rationale  = r.get("rationale") or ""
            summary_md = r.get("summary") or ""

            pass_fail  = "PASS" if correct else "FAIL"
            card_cls   = "run-pass" if correct else "run-fail"
            badge_cls  = "badge-pass" if correct else "badge-fail"

            lat_str = f"{lat/1000:.1f}s" if isinstance(lat, (int, float)) and lat else "?"

            detail_html = ""
            if rationale:
                detail_html += f'<div class="run-detail-label">Rationale</div><div class="run-rationale">{rationale}</div>'
            if err:
                detail_html += f'<div class="run-detail-label" style="margin-top:.5rem;color:#991b1b">Error</div><div style="font-size:.82rem;color:#991b1b">{err}</div>'
            if summary_md:
                # Strip markdown for safe display (keep it readable, no render)
                safe_summary = summary_md[:1200] + ("…" if len(summary_md) > 1200 else "")
                detail_html += f'<div class="run-detail-label" style="margin-top:.6rem">Agent Summary</div><pre class="run-summary-md">{safe_summary}</pre>'

            detail_block = ""
            if detail_html:
                detail_block = f'<div class="run-detail">{detail_html}</div>'

            cards += f"""
            <details class="run-card {card_cls}">
              <summary class="run-card-header">
                <div class="run-meta">
                  <span class="run-invoice">{invoice}</span>
                  <span class="pill-scenario">{scenario}</span>
                  <span class="run-decision">
                    Expected {_decision_html(expected)} &rarr; Got {_decision_html(got)}
                  </span>
                </div>
                <span class="badge {badge_cls}">{pass_fail}</span>
                <span class="run-stats">{turns} turns &middot; {tools} tools &middot; {lat_str}</span>
              </summary>
              {detail_block}
            </details>"""

        run_cards_html = f"""
        <div class="section">
          <div class="section-head">
            <h2>Individual Runs</h2>
            <span class="section-sub">{len(raw_runs)} invoices &middot; click a row to expand</span>
          </div>
          <div class="run-cards">{cards}</div>
        </div>"""

    axis_badge = (
        f'<span class="pill-axis">{axis}</span>'
        if axis != "—"
        else '<span class="pill-axis-dash">—</span>'
    )

    body = f"""
  <div style="background:var(--bg);border-bottom:1px solid var(--border);padding:1.75rem 0 1.5rem;margin-bottom:2rem;">
    <div class="container">
      <div class="breadcrumb"><a href="/">Dashboard</a> / {display}</div>
      <h1 style="font-size:1.5rem;font-weight:700;letter-spacing:-0.02em;margin-top:.25rem">{display}</h1>
      <p style="color:var(--muted);font-size:0.875rem;margin-top:0.35rem;display:flex;align-items:center;gap:.6rem">
        <code style="background:transparent;padding:0">{model}</code>
        <span>&middot;</span> RPST axis: {axis_badge}
      </p>
    </div>
  </div>
  <main>
    <div class="container">
      {stat_cards_html}
      {sc_table_html}
      {run_cards_html}
    </div>
  </main>"""

    return _base(display, body, active="dashboard")


# ---------------------------------------------------------------------------
# Run experiment
# ---------------------------------------------------------------------------

def _check_api_limit() -> str | None:
    import os
    return os.getenv("ANTHROPIC_API_LIMIT_NOTE")


def _config_display(cfg: str) -> str:
    return _display_name(cfg)


@app.route("/run", methods=["GET"])
def run_form():
    configs = _discover_configs()
    api_limit = _check_api_limit()

    alert_html = ""
    if api_limit:
        alert_html = f"""
        <div class="alert alert-error">
          <span class="alert-icon">&#9888;</span>
          <div>
            <strong>API spending limit active</strong> &mdash; {api_limit}<br>
            Experiments will fail until the limit resets. Browse existing results on the
            <a href="/">Dashboard</a> in the meantime, or raise your limit at
            <a href="https://console.anthropic.com" target="_blank">console.anthropic.com</a>.
          </div>
        </div>"""
    else:
        alert_html = """
        <div class="alert alert-warn">
          <span class="alert-icon">&#9888;</span>
          <div>
            Running a Haiku variant costs ~$0.05&ndash;$0.15. Sonnet costs ~$0.50&ndash;$1.50.
            Check your <a href="https://console.anthropic.com" target="_blank">Anthropic console</a>
            before running Sonnet variants.
          </div>
        </div>"""

    options_html = '<option value="">-- select a config --</option>' + "".join(
        f'<option value="{c}">{_config_display(c)} ({c})</option>'
        for c in configs
    )

    form_html = f"""
    {alert_html}
    <div class="form-card">
      <h2 style="font-size:1.05rem;font-weight:700;margin-bottom:1.25rem">Experiment settings</h2>
      <form method="post" action="/run">
        <div class="form-group">
          <label for="config">Config</label>
          <select name="config" id="config" required>
            {options_html}
          </select>
          <p class="help-text">Each config maps to <code>experiments/configs/&lt;name&gt;.yaml</code></p>
        </div>
        <div class="form-group">
          <label for="seed">Random seed <span style="font-weight:400;color:var(--muted)">(optional)</span></label>
          <input type="number" name="seed" id="seed" placeholder="42" style="max-width:160px">
          <p class="help-text">Leave blank to use the config default. Change the seed to test stability.</p>
        </div>
        <button type="submit" class="btn btn-primary">Start Experiment &#8594;</button>
      </form>
    </div>"""

    body = f"""
  <div style="background:var(--bg);border-bottom:1px solid var(--border);padding:1.75rem 0 1.5rem;margin-bottom:2rem;">
    <div class="container">
      <h1 style="font-size:1.6rem;font-weight:700;letter-spacing:-0.02em">Run Experiment</h1>
      <p style="color:var(--muted);font-size:0.9rem;margin-top:0.3rem">
        Executes <code>scripts/run_experiment.py</code> and streams output live.
        Results are written to <code>experiments/&lt;variant&gt;/</code>.
      </p>
    </div>
  </div>
  <main>
    <div class="container">{form_html}</div>
  </main>"""

    return _base("Run Experiment", body, active="run")


@app.route("/run", methods=["POST"])
def run_submit():
    config = request.form.get("config", "").strip()
    seed   = request.form.get("seed", "").strip()
    if not config or not (CONFIGS_DIR / f"{config}.yaml").exists():
        return redirect(url_for("run_form"))

    display = _config_display(config)
    seed_param = f"&seed={seed}" if seed else ""

    # JS-driven streaming page
    stream_url = f"/run/stream?config={config}{seed_param}"

    spinner_html = '<span class="spinner"></span>'

    body = f"""
  <div style="background:var(--bg);border-bottom:1px solid var(--border);padding:1.75rem 0 1.5rem;margin-bottom:2rem;">
    <div class="container">
      <h1 style="font-size:1.5rem;font-weight:700;letter-spacing:-0.02em">
        {spinner_html}
        &nbsp;Running: {display}
      </h1>
      <p id="status-text" style="color:var(--muted);font-size:0.875rem;margin-top:0.4rem">
        In progress &mdash; do not close this tab.
      </p>
    </div>
  </div>
  <main>
    <div class="container">
      <div class="section">
        <div class="stream-card" id="output-box"></div>
        <div style="margin-top:1rem;display:flex;gap:.75rem;align-items:center">
          <a id="back-btn" class="btn btn-secondary" href="/" style="display:none">&larr; Back to Dashboard</a>
          <a id="detail-btn" class="btn btn-primary" href="/experiment/{config}" style="display:none">View Results &#8594;</a>
        </div>
      </div>
    </div>
  </main>
  <script>
  (function() {{
    var box   = document.getElementById('output-box');
    var stat  = document.getElementById('status-text');
    var back  = document.getElementById('back-btn');
    var detail = document.getElementById('detail-btn');
    var src   = new EventSource('{stream_url}');

    src.onmessage = function(e) {{
      var line = document.createElement('div');
      line.className = 'stream-line';
      line.textContent = e.data;
      box.appendChild(line);
      box.scrollTop = box.scrollHeight;
    }};

    src.addEventListener('done', function() {{
      src.close();
      stat.textContent = 'Run complete.';
      back.style.display   = 'inline-flex';
      detail.style.display = 'inline-flex';
      // stop spinner by hiding it
      document.querySelector('.spinner') && (document.querySelector('.spinner').style.display = 'none');
    }});

    src.onerror = function() {{
      src.close();
      stat.textContent = 'Connection closed.';
      back.style.display = 'inline-flex';
    }};
  }})();
  </script>"""

    return _base(f"Running {display}", body, active="run")


@app.route("/run/stream")
def run_stream():
    """SSE: streams run_experiment.py output line by line."""
    config = request.args.get("config", "").strip()
    seed   = request.args.get("seed", "").strip()
    config_path = CONFIGS_DIR / f"{config}.yaml"

    if not config_path.exists():
        def _err() -> Iterator[str]:
            yield "data: Config not found.\n\nevent: done\ndata: \n\n"
        return Response(_err(), mimetype="text/event-stream")

    cmd = [sys.executable, "-m", "scripts.run_experiment", str(config_path)]
    if seed:
        try:
            int(seed)
            cmd += ["--seed", seed]
        except ValueError:
            pass

    def _generate() -> Iterator[str]:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n").replace("\n", " ")
                # Escape backslash and SSE special chars minimally
                yield f"data: {line}\n\n"
            proc.wait()
            yield f"data: \ndata: --- process exited (rc={proc.returncode}) ---\n\n"
        except Exception as exc:
            yield f"data: ERROR: {exc}\n\n"
        yield "event: done\ndata: \n\n"

    return Response(_generate(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AP Agent Lab web UI")
    parser.add_argument("--host",  default="127.0.0.1")
    parser.add_argument("--port",  type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"AP Agent Lab  ->  http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    app.run(host=args.host, port=args.port, debug=args.debug)
