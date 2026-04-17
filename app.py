"""
app.py -- Lightweight Flask web UI for the Three-Way Match lab.

Exposes three pages:
  GET  /                          Dashboard: all experiments, summary stats
  GET  /experiment/<name>         Detail view: runs table, per-scenario breakdown
  GET  /run                       Run form: pick a config, launch an experiment
  POST /run                       Execute the run via subprocess, stream output

Usage:
  python app.py
  python app.py --port 5001
  python app.py --host 0.0.0.0 --port 8080

Requirements:
  pip install flask

The app uses the same CSS variables as docs/viewer/index.html so it feels
like the same tool family. No database, no ORM -- reads from the filesystem.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterator

from flask import Flask, Response, abort, redirect, render_template_string, request, url_for

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT     = Path(__file__).resolve().parent
EXPERIMENTS   = REPO_ROOT / "experiments"
CONFIGS_DIR   = EXPERIMENTS / "configs"

app = Flask(__name__)


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
    rows = []
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
    """Canonical variant names only -- excludes seed sub-runs."""
    return sorted(
        d.name for d in EXPERIMENTS.iterdir()
        if d.is_dir()
        and (d / "summary.json").exists()
        and "_seed" not in d.name
        and d.name not in ("configs",)
    )


def _discover_configs() -> list[str]:
    """Return config YAML names (without .yaml) sorted alphabetically."""
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


def _acc_class(pct: float) -> str:
    if pct >= 90:
        return "acc-green"
    if pct >= 70:
        return "acc-amber"
    return "acc-red"


# ---------------------------------------------------------------------------
# Shared CSS  (same variables as the static viewer)
# ---------------------------------------------------------------------------

BASE_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --accent:  #2563eb;
  --text:    #111827;
  --muted:   #6b7280;
  --border:  #e5e7eb;
  --bg:      #ffffff;
  --bg-alt:  #f9fafb;
  --danger:  #dc2626;
  --success: #166534;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--text);
  background: var(--bg);
  line-height: 1.55;
}
.container { max-width: 1100px; margin: 0 auto; padding: 0 1rem; }
nav {
  position: sticky; top: 0; z-index: 100;
  background: var(--bg); border-bottom: 1px solid var(--border); padding: 0.6rem 0;
}
nav .container { display: flex; gap: 1.5rem; align-items: center; }
nav a { color: var(--accent); text-decoration: none; font-size: 0.9rem; font-weight: 500; }
nav a:hover { text-decoration: underline; }
nav .brand { font-weight: 700; color: var(--text); font-size: 0.95rem; }
header { padding: 2.5rem 0 1.5rem; border-bottom: 1px solid var(--border); margin-bottom: 2rem; }
header h1 { font-size: 1.75rem; font-weight: 700; }
header .subtitle { font-size: 1rem; color: var(--muted); margin-top: 0.25rem; }
section { margin-bottom: 3rem; }
section h2 { font-size: 1.15rem; font-weight: 700; margin-bottom: 1rem;
             padding-bottom: 0.4rem; border-bottom: 2px solid var(--border); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
thead th {
  position: sticky; top: 42px;
  background: var(--bg-alt); border-bottom: 2px solid var(--border);
  padding: 0.55rem 0.75rem; text-align: left;
  font-weight: 600; white-space: nowrap;
}
tbody tr:nth-child(even) { background: var(--bg-alt); }
tbody tr:nth-child(odd)  { background: var(--bg); }
tbody td { padding: 0.45rem 0.75rem; border-bottom: 1px solid var(--border); vertical-align: top; }
tbody tr:hover { background: #eff6ff; }
.acc-green { background:#dcfce7; color:#166534; border-radius:4px; padding:2px 6px; font-weight:600; white-space:nowrap; }
.acc-amber { background:#fef9c3; color:#713f12; border-radius:4px; padding:2px 6px; font-weight:600; white-space:nowrap; }
.acc-red   { background:#fee2e2; color:#991b1b; border-radius:4px; padding:2px 6px; font-weight:600; white-space:nowrap; }
.badge-pass { color: var(--success); font-weight: 700; }
.badge-fail { color: var(--danger);  font-weight: 700; }
.pill {
  display: inline-block; border-radius: 4px; padding: 2px 8px;
  font-size: 0.78rem; font-weight: 600; white-space: nowrap;
}
.pill-blue   { background:#dbeafe; color:#1d4ed8; }
.pill-green  { background:#dcfce7; color:#166534; }
.pill-amber  { background:#fef9c3; color:#713f12; }
.pill-red    { background:#fee2e2; color:#991b1b; }
a.row-link   { color: var(--accent); text-decoration: none; font-weight: 500; }
a.row-link:hover { text-decoration: underline; }
.btn {
  display: inline-block; padding: 0.5rem 1.25rem; border-radius: 6px;
  font-size: 0.9rem; font-weight: 600; cursor: pointer; border: none;
  text-decoration: none;
}
.btn-primary  { background: var(--accent); color: #fff; }
.btn-primary:hover { background: #1d4ed8; }
.btn-secondary { background: var(--bg-alt); color: var(--text); border: 1px solid var(--border); }
.btn-secondary:hover { background: var(--border); }
.form-group { margin-bottom: 1.25rem; }
label { display: block; font-size: 0.875rem; font-weight: 600; margin-bottom: 0.35rem; }
select, input[type=text] {
  width: 100%; max-width: 480px; padding: 0.45rem 0.6rem;
  border: 1px solid var(--border); border-radius: 6px;
  font-size: 0.9rem; background: var(--bg);
}
select:focus, input[type=text]:focus { outline: 2px solid var(--accent); }
.help-text { font-size: 0.8rem; color: var(--muted); margin-top: 0.25rem; }
.alert { padding: 0.75rem 1rem; border-radius: 6px; margin-bottom: 1.25rem; font-size: 0.9rem; }
.alert-warn  { background: #fef9c3; color: #713f12; border: 1px solid #fde68a; }
.alert-error { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.alert-info  { background: #dbeafe; color: #1d4ed8; border: 1px solid #bfdbfe; }
pre.stream-output {
  background: #111827; color: #d1fae5; font-size: 0.8rem;
  padding: 1rem; border-radius: 8px; overflow-x: auto;
  white-space: pre-wrap; word-break: break-all;
  max-height: 520px; overflow-y: auto;
}
.empty-state { color: var(--muted); font-size: 0.9rem; padding: 2rem 0; }
"""

NAV_HTML = """
<nav>
  <div class="container">
    <span class="brand">AP Agent Lab</span>
    <a href="/">Dashboard</a>
    <a href="/run">Run Experiment</a>
    <a href="/docs/viewer/index.html" target="_blank">Scorecard</a>
  </div>
</nav>
"""

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# ── Dashboard ────────────────────────────────────────────────────────────────

DASHBOARD_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AP Agent Lab — Dashboard</title>
<style>{{ css }}</style>
</head>
<body>
{{ nav }}
<div class="container">
  <header>
    <h1>ERP Agent Experimentation Lab</h1>
    <p class="subtitle">{{ variant_count }} variants &middot; {{ total_bills }} bills evaluated &middot; ${{ total_cost }} API spend</p>
  </header>

  <section>
    <h2>Variants</h2>
    {% if variants %}
    <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Variant</th>
          <th>Model</th>
          <th>Accuracy</th>
          <th>Cost (USD)</th>
          <th>Avg turns</th>
          <th>Avg tools</th>
          <th>Latency (s)</th>
        </tr>
      </thead>
      <tbody>
        {% for v in variants %}
        <tr>
          <td><a class="row-link" href="/experiment/{{ v.name }}">{{ v.name }}</a></td>
          <td><code>{{ v.model }}</code></td>
          <td><span class="{{ v.acc_class }}">{{ v.acc_pct }}</span></td>
          <td>${{ v.cost }}</td>
          <td>{{ v.turns }}</td>
          <td>{{ v.tools }}</td>
          <td>{{ v.latency }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
    {% else %}
    <p class="empty-state">No experiments found under <code>experiments/</code>. Run one first.</p>
    {% endif %}
  </section>

  {% if scenarios %}
  <section>
    <h2>Scenario Breakdown</h2>
    <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Scenario</th>
          {% for v in variants %}<th>{{ v.name }}</th>{% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for sc, row in scenarios %}
        <tr>
          <td>{{ sc }}</td>
          {% for cell in row %}
          <td>{% if cell is not none %}<span class="{{ cell.cls }}">{{ cell.label }}</span>{% else %}&mdash;{% endif %}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
  </section>
  {% endif %}
</div>
</body>
</html>"""


@app.route("/")
def dashboard():
    variant_names = _discover_variants()
    variants = []
    all_scenarios: set[str] = set()
    summaries: dict[str, dict] = {}

    for name in variant_names:
        s = _load_summary(EXPERIMENTS / name)
        if not s:
            continue
        summaries[name] = s
        totals   = s.get("totals", {})
        avgs     = s.get("averages", {})
        tc       = s.get("totals_cost", {})
        acc_raw  = (totals.get("accuracy") or 0.0) * 100
        cost_raw = tc.get("cost_usd", 0.0)
        lat_raw  = (avgs.get("latency_ms") or 0.0) / 1000.0
        model    = (s.get("model") or "?").replace("claude-haiku-4-5-20251001", "haiku-4.5").replace("claude-sonnet-4-6", "sonnet-4.6")
        variants.append({
            "name":      name,
            "model":     model,
            "acc_class": _acc_class(acc_raw),
            "acc_pct":   f"{acc_raw:.1f}%",
            "cost":      f"{cost_raw:.3f}",
            "turns":     f"{(avgs.get('turns') or 0.0):.1f}",
            "tools":     f"{(avgs.get('tool_calls') or 0.0):.1f}",
            "latency":   f"{lat_raw:.1f}s",
        })
        for sc in s.get("by_scenario", {}).keys():
            all_scenarios.add(sc)

    total_bills = sum(summaries[n].get("totals", {}).get("bills_attempted", 0) for n in summaries)
    total_cost  = sum(summaries[n].get("totals_cost", {}).get("cost_usd", 0.0) for n in summaries)

    # Build scenario matrix
    scenario_rows = []
    for sc in sorted(all_scenarios):
        row = []
        for v in variants:
            sc_data = summaries.get(v["name"], {}).get("by_scenario", {}).get(sc)
            if sc_data is None:
                row.append(None)
            else:
                acc_frac = sc_data.get("accuracy")
                pct = (acc_frac * 100) if acc_frac is not None else 0.0
                row.append({"cls": _acc_class(pct), "label": f"{pct:.0f}%"})
        scenario_rows.append((sc, row))

    return render_template_string(
        DASHBOARD_TMPL,
        css=BASE_CSS,
        nav=NAV_HTML,
        variant_count=len(variants),
        total_bills=total_bills,
        total_cost=f"{total_cost:.3f}",
        variants=variants,
        scenarios=scenario_rows,
    )


# ── Experiment detail ─────────────────────────────────────────────────────────

DETAIL_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ name }} — AP Agent Lab</title>
<style>{{ css }}</style>
</head>
<body>
{{ nav }}
<div class="container">
  <header>
    <h1>{{ name }}</h1>
    <p class="subtitle">{{ model }} &middot; <span class="{{ acc_class }}">{{ acc_pct }}</span> overall accuracy &middot; {{ bills_attempted }} bills &middot; ${{ cost }} API spend</p>
  </header>

  <section>
    <h2>Summary Stats</h2>
    <div class="table-wrap">
    <table style="max-width:520px">
      <tbody>
        <tr><td><strong>Accuracy</strong></td><td><span class="{{ acc_class }}">{{ acc_pct }}</span></td></tr>
        <tr><td><strong>Bills attempted</strong></td><td>{{ bills_attempted }}</td></tr>
        <tr><td><strong>Bills completed</strong></td><td>{{ bills_completed }}</td></tr>
        <tr><td><strong>Correct</strong></td><td>{{ correct }}</td></tr>
        <tr><td><strong>Avg turns</strong></td><td>{{ avg_turns }}</td></tr>
        <tr><td><strong>Avg tool calls</strong></td><td>{{ avg_tools }}</td></tr>
        <tr><td><strong>Avg latency</strong></td><td>{{ avg_latency }}</td></tr>
        <tr><td><strong>Total cost</strong></td><td>${{ cost }}</td></tr>
      </tbody>
    </table>
    </div>
  </section>

  {% if by_scenario %}
  <section>
    <h2>By Scenario</h2>
    <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Scenario</th><th>Accuracy</th><th>N</th><th>Correct</th></tr>
      </thead>
      <tbody>
        {% for sc in by_scenario %}
        <tr>
          <td>{{ sc.name }}</td>
          <td><span class="{{ sc.acc_class }}">{{ sc.acc_pct }}</span></td>
          <td>{{ sc.n }}</td>
          <td>{{ sc.correct }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
  </section>
  {% endif %}

  {% if runs %}
  <section>
    <h2>Individual Runs ({{ runs|length }})</h2>
    <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Invoice</th>
          <th>Scenario</th>
          <th>Expected</th>
          <th>Got</th>
          <th>Result</th>
          <th>Turns</th>
          <th>Tools</th>
          <th>Latency (ms)</th>
          <th>Error</th>
        </tr>
      </thead>
      <tbody>
        {% for r in runs %}
        <tr class="{% if not r.correct %}fail-row{% endif %}">
          <td>{{ loop.index }}</td>
          <td><code>{{ r.invoice }}</code></td>
          <td><span class="pill pill-blue">{{ r.scenario }}</span></td>
          <td>{{ r.expected }}</td>
          <td>{{ r.got }}</td>
          <td>{% if r.correct %}<span class="badge-pass">PASS</span>{% else %}<span class="badge-fail">FAIL</span>{% endif %}</td>
          <td>{{ r.turns }}</td>
          <td>{{ r.tools }}</td>
          <td>{{ r.latency_ms }}</td>
          <td style="font-size:0.78rem;color:var(--danger)">{{ r.error or '' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
  </section>
  {% endif %}

  <div style="padding-bottom:3rem">
    <a class="btn btn-secondary" href="/">&larr; Dashboard</a>
  </div>
</div>
</body>
</html>"""


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
    model   = (s.get("model") or "?").replace("claude-haiku-4-5-20251001", "haiku-4.5").replace("claude-sonnet-4-6", "sonnet-4.6")

    by_scenario = []
    for sc_name, sc_data in sorted((s.get("by_scenario") or {}).items()):
        acc_frac = sc_data.get("accuracy")
        n        = sc_data.get("n", sc_data.get("total", 0))
        correct  = sc_data.get("correct", 0)
        if acc_frac is None:
            pct = (correct / n * 100) if n else 0.0
        else:
            pct = acc_frac * 100
        by_scenario.append({
            "name":      sc_name,
            "acc_class": _acc_class(pct),
            "acc_pct":   f"{pct:.1f}%",
            "n":         n,
            "correct":   correct,
        })

    raw_runs = _load_runs(variant_dir)
    runs = []
    for r in raw_runs:
        runs.append({
            "invoice":    r.get("invoice_number", r.get("invoice", "?")),
            "scenario":   r.get("scenario_type", r.get("scenario", "?")),
            "expected":   r.get("expected_action", r.get("expected", "?")),
            "got":        r.get("recommended_action", r.get("got", "?")),
            "correct":    r.get("correct", False),
            "turns":      r.get("turns", "?"),
            "tools":      r.get("tool_calls", "?"),
            "latency_ms": r.get("latency_ms", "?"),
            "error":      r.get("error"),
        })

    return render_template_string(
        DETAIL_TMPL,
        css=BASE_CSS,
        nav=NAV_HTML,
        name=name,
        model=model,
        acc_class=_acc_class(acc_raw),
        acc_pct=f"{acc_raw:.1f}%",
        bills_attempted=totals.get("bills_attempted", 0),
        bills_completed=totals.get("bills_completed", 0),
        correct=totals.get("correct", 0),
        avg_turns=f"{(avgs.get('turns') or 0.0):.1f}",
        avg_tools=f"{(avgs.get('tool_calls') or 0.0):.1f}",
        avg_latency=f"{(avgs.get('latency_ms') or 0.0) / 1000:.1f}s",
        cost=f"{tc.get('cost_usd', 0.0):.3f}",
        by_scenario=by_scenario,
        runs=runs,
    )


# ── Run experiment ─────────────────────────────────────────────────────────────

RUN_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Run Experiment — AP Agent Lab</title>
<style>{{ css }}</style>
</head>
<body>
{{ nav }}
<div class="container">
  <header>
    <h1>Run Experiment</h1>
    <p class="subtitle">Executes <code>scripts/run_experiment.py</code> against the selected config. Results are written to <code>experiments/&lt;variant&gt;/</code>.</p>
  </header>

  {% if api_limit_warning %}
  <div class="alert alert-error">
    <strong>API limit active</strong> &mdash; {{ api_limit_warning }}
    Runs will fail until the limit resets. You can still browse existing results on the
    <a href="/">Dashboard</a>.
  </div>
  {% endif %}

  <div class="alert alert-warn">
    <strong>Warning:</strong> Running a variant against the full 30-bill sample costs roughly $0.05&ndash;$0.15 (Haiku)
    or $0.50&ndash;$1.50 (Sonnet). Check the
    <a href="https://console.anthropic.com" target="_blank">Anthropic console</a>
    before running Sonnet variants.
  </div>

  <section>
    <h2>Select config</h2>
    <form method="post" action="/run" id="run-form">
      <div class="form-group">
        <label for="config">Config</label>
        <select name="config" id="config" required>
          <option value="">-- choose --</option>
          {% for cfg in configs %}
          <option value="{{ cfg }}">{{ cfg }}</option>
          {% endfor %}
        </select>
        <p class="help-text">Each config maps to <code>experiments/configs/&lt;name&gt;.yaml</code>.</p>
      </div>
      <div class="form-group">
        <label for="seed">Seed (optional)</label>
        <input type="text" name="seed" id="seed" placeholder="42" style="max-width:120px">
        <p class="help-text">Override the YAML seed for this run only. Leave blank to use the config default.</p>
      </div>
      <button type="submit" class="btn btn-primary">Run &rarr;</button>
    </form>
  </section>
</div>
</body>
</html>"""

RUN_STREAMING_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Running {{ config }} — AP Agent Lab</title>
<style>{{ css }}</style>
<script>
// Auto-scroll the output box as new lines arrive
window.addEventListener('DOMContentLoaded', function() {
  var pre = document.getElementById('output');
  var src = new EventSource('/run/stream?config={{ config }}&seed={{ seed }}');
  src.onmessage = function(e) {
    pre.textContent += e.data + '\\n';
    pre.scrollTop = pre.scrollHeight;
  };
  src.addEventListener('done', function(e) {
    src.close();
    document.getElementById('status').textContent = 'Run complete.';
    document.getElementById('back-btn').style.display = 'inline-block';
  });
  src.onerror = function() {
    src.close();
    document.getElementById('status').textContent = 'Connection closed.';
    document.getElementById('back-btn').style.display = 'inline-block';
  };
});
</script>
</head>
<body>
{{ nav }}
<div class="container">
  <header>
    <h1>Running: {{ config }}</h1>
    <p class="subtitle" id="status">In progress &mdash; do not close this tab.</p>
  </header>

  <section>
    <pre class="stream-output" id="output"></pre>
    <div style="margin-top:1rem">
      <a id="back-btn" class="btn btn-secondary" href="/" style="display:none">&larr; Back to Dashboard</a>
    </div>
  </section>
</div>
</body>
</html>"""


def _check_api_limit() -> str | None:
    """Return a warning string if the API limit env var is set, else None."""
    # Users can set ANTHROPIC_API_LIMIT_NOTE=<date> in .env to show a reminder.
    import os
    note = os.getenv("ANTHROPIC_API_LIMIT_NOTE")
    if note:
        return f"Spending limit active until {note}."
    return None


@app.route("/run", methods=["GET"])
def run_form():
    return render_template_string(
        RUN_TMPL,
        css=BASE_CSS,
        nav=NAV_HTML,
        configs=_discover_configs(),
        api_limit_warning=_check_api_limit(),
    )


@app.route("/run", methods=["POST"])
def run_submit():
    config = request.form.get("config", "").strip()
    seed   = request.form.get("seed", "").strip()
    if not config:
        return redirect(url_for("run_form"))
    # Validate config exists
    config_path = CONFIGS_DIR / f"{config}.yaml"
    if not config_path.exists():
        return redirect(url_for("run_form"))
    # Redirect to streaming page
    params = f"config={config}"
    if seed:
        params += f"&seed={seed}"
    return render_template_string(
        RUN_STREAMING_TMPL,
        css=BASE_CSS,
        nav=NAV_HTML,
        config=config,
        seed=seed or "",
    )


@app.route("/run/stream")
def run_stream():
    """SSE endpoint — streams subprocess output line by line."""
    config = request.args.get("config", "").strip()
    seed   = request.args.get("seed", "").strip()

    config_path = CONFIGS_DIR / f"{config}.yaml"
    if not config_path.exists():
        def err() -> Iterator[str]:
            yield "data: Config not found.\n\nevent: done\ndata: \n\n"
        return Response(err(), mimetype="text/event-stream")

    cmd = [sys.executable, "-m", "scripts.run_experiment", str(config_path)]
    if seed:
        try:
            int(seed)  # validate
            cmd += ["--seed", seed]
        except ValueError:
            pass

    def generate() -> Iterator[str]:
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
            for line in proc.stdout:
                line = line.rstrip("\n")
                # Escape for SSE
                line = line.replace("\n", " ")
                yield f"data: {line}\n\n"
            proc.wait()
            rc = proc.returncode
            yield f"data: \ndata: --- process exited (rc={rc}) ---\n\n"
        except Exception as exc:
            yield f"data: ERROR: {exc}\n\n"
        yield "event: done\ndata: \n\n"

    return Response(generate(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AP Agent Lab web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Bind port (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    print(f"AP Agent Lab running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.")
    app.run(host=args.host, port=args.port, debug=args.debug)
