"""
compare_variants.py -- side-by-side comparison of all experiment variants.

Usage:
    python scripts/compare_variants.py
    python scripts/compare_variants.py --no-color
    python scripts/compare_variants.py --json
    python scripts/compare_variants.py --csv
    python scripts/compare_variants.py --json > results.json
    python scripts/compare_variants.py --csv  > results.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

REPO_ROOT       = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
CONFIGS_DIR     = EXPERIMENTS_DIR / "configs"

# ANSI colour codes
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

# ---------------------------------------------------------------------------
# Variant display metadata (mirrors app.py)
# ---------------------------------------------------------------------------
VARIANT_DISPLAY: dict[str, tuple[str, str]] = {
    "baseline":           ("Baseline (Sonnet 4.6)",    "--"),
    "tight_tolerance":    ("Tight Tolerance (OR Logic)", "Policy"),
    "cfo_persona":        ("CFO Persona",              "Role"),
    "haiku_ap_persona":   ("AP Clerk Control (Haiku)", "Role + Model"),
    "prompt_injection":   ("Prompt Injection Test",    "Security"),
    "goal_only_playbook": ("Goal-Only Playbook",       "Playbook"),
    "no_duplicate_tool":  ("No Duplicate Tool",        "Skills/Tools"),
}


def _display_name(variant: str) -> str:
    if variant in VARIANT_DISPLAY:
        return VARIANT_DISPLAY[variant][0]
    return variant.replace("_", " ").title()


def _rpst_axis(variant: str) -> str:
    if variant in VARIANT_DISPLAY:
        return VARIANT_DISPLAY[variant][1]
    return "--"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def colour(text: str, code: str, use_colour: bool) -> str:
    if not use_colour:
        return text
    return f"{code}{text}{RESET}"


def acc_colour(pct: float, use_colour: bool) -> str:
    val = f"{pct:.1f}%"
    if pct >= 95:
        return colour(val, GREEN, use_colour)
    if pct >= 80:
        return colour(val, YELLOW, use_colour)
    return colour(val, RED, use_colour)


def strip_ansi(s: str) -> str:
    import re
    return re.sub(r'\033\[[0-9;]*m', '', s)


def pad(s: str, width: int, align: str = "<") -> str:
    visible = len(strip_ansi(s))
    padding = max(0, width - visible)
    if align == ">":
        return " " * padding + s
    return s + " " * padding


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_summary(variant_dir: Path) -> dict | None:
    p = variant_dir / "summary.json"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_rpst_from_config(variant_name: str) -> str:
    """Parse the RPST axis from config YAML description, falling back to metadata table."""
    # Use the metadata table first (authoritative)
    axis = _rpst_axis(variant_name)
    if axis != "—":
        return axis
    # Try to parse from config
    config_path = CONFIGS_DIR / f"{variant_name}.yaml"
    if not config_path.exists():
        return "—"
    try:
        text = config_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            low = line.strip().lower()
            if "rpst axis" in low:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip().split("(")[0].strip()
    except Exception:
        pass
    return "—"


def discover_variants() -> list[str]:
    """Return canonical variant names (no _seed sub-runs)."""
    dirs = sorted(
        d.name for d in EXPERIMENTS_DIR.iterdir()
        if d.is_dir()
        and (d / "summary.json").exists()
        and "_seed" not in d.name
    )
    return dirs


def _short_model(model: str) -> str:
    return (model
            .replace("claude-haiku-4-5-20251001", "haiku-4.5")
            .replace("claude-sonnet-4-6",         "sonnet-4.6")
            .replace("claude-opus-4-6",            "opus-4.6"))


def _build_rows(variants: list[str], summaries: dict[str, dict]) -> list[dict]:
    """Build a list of row dicts for the main table."""
    rows = []
    for v in variants:
        s       = summaries[v]
        totals  = s.get("totals", {})
        avgs    = s.get("averages", {})
        tc      = s.get("totals_cost", {})
        acc_raw = (totals.get("accuracy") or 0.0) * 100
        model   = _short_model(s.get("model") or "?")
        cost    = tc.get("cost_usd", 0.0)
        turns   = avgs.get("turns") or 0.0
        tools   = avgs.get("tool_calls") or 0.0
        lat     = (avgs.get("latency_ms") or 0.0) / 1000.0
        rows.append({
            "variant":  v,
            "display":  _display_name(v),
            "rpst":     load_rpst_from_config(v),
            "model":    model,
            "acc":      acc_raw,
            "cost":     cost,
            "turns":    turns,
            "tools":    tools,
            "lat":      lat,
            "bills":    totals.get("bills_attempted", 0),
            "correct":  totals.get("decisions_correct", totals.get("correct", 0)),
        })
    return rows


# ---------------------------------------------------------------------------
# Text table output
# ---------------------------------------------------------------------------

def build_main_table(variants: list[str], summaries: dict[str, dict], use_colour: bool) -> str:
    rows = _build_rows(variants, summaries)

    cols   = ["Variant (display name)", "Config name", "RPST Axis", "Model",
              "Accuracy", "Cost", "Turns", "Tools", "Latency(s)"]
    col_w  = [28, 24, 14, 14, 10, 9, 7, 7, 10]

    # Widen first two columns to fit actual data
    col_w[0] = max(col_w[0], max(len(r["display"]) for r in rows))
    col_w[1] = max(col_w[1], max(len(r["variant"]) for r in rows))

    sep = "+" + "+".join("-" * (w + 2) for w in col_w) + "+"
    header_cells = [pad(colour(c, BOLD, use_colour), col_w[i]) for i, c in enumerate(cols)]
    header = "| " + " | ".join(header_cells) + " |"

    lines = [sep, header, sep]
    for r in rows:
        cells = [
            pad(r["display"][:col_w[0]], col_w[0]),
            pad(r["variant"][:col_w[1]], col_w[1]),
            pad(r["rpst"][:col_w[2]],   col_w[2]),
            pad(r["model"][:col_w[3]],  col_w[3]),
            pad(acc_colour(r["acc"], use_colour), col_w[4], ">"),
            pad(f"${r['cost']:.3f}",    col_w[5], ">"),
            pad(f"{r['turns']:.1f}",    col_w[6], ">"),
            pad(f"{r['tools']:.1f}",    col_w[7], ">"),
            pad(f"{r['lat']:.1f}s",     col_w[8], ">"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(sep)
    return "\n".join(lines)


def build_scenario_matrix(variants: list[str], summaries: dict[str, dict], use_colour: bool) -> str:
    all_scenarios: set[str] = set()
    for s in summaries.values():
        for sc in s.get("by_scenario", {}).keys():
            all_scenarios.add(sc)
    scenarios = sorted(all_scenarios)

    if not scenarios:
        return "(no per-scenario data available)"

    scen_w = max(len(sc) for sc in scenarios) + 2
    # Use short display names in column headers to keep table readable
    short_names = [_display_name(v)[:22] for v in variants]
    var_w = max(max(len(n) for n in short_names), 7) + 2

    header_cells = [pad(colour("Scenario", BOLD, use_colour), scen_w)]
    for n in short_names:
        header_cells.append(pad(colour(n, BOLD, use_colour), var_w))
    sep    = "+" + "+".join("-" * (w + 2) for w in [scen_w] + [var_w] * len(variants)) + "+"
    header = "| " + " | ".join(header_cells) + " |"

    lines = [sep, header, sep]
    for sc in scenarios:
        cells = [pad(sc, scen_w)]
        for v in variants:
            sc_data = summaries[v].get("by_scenario", {}).get(sc)
            if sc_data is None:
                cells.append(pad(colour("  --  ", DIM, use_colour), var_w))
            else:
                acc_frac = sc_data.get("accuracy")
                if acc_frac is not None:
                    pct = acc_frac * 100
                else:
                    correct = sc_data.get("correct", 0)
                    total   = sc_data.get("n", sc_data.get("total", 0))
                    pct     = (correct / total * 100) if total else 0.0
                cells.append(pad(acc_colour(pct, use_colour), var_w))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(sep)
    return "\n".join(lines)


def build_summary_footer(variants: list[str], summaries: dict[str, dict], use_colour: bool) -> str:
    rows = _build_rows(variants, summaries)
    if not rows:
        return ""

    total_bills = sum(r["bills"] for r in rows)
    total_cost  = sum(r["cost"]  for r in rows)
    best        = max(rows, key=lambda r: r["acc"])
    worst       = min(rows, key=lambda r: r["acc"])

    lines = [
        colour("-" * 60, DIM, use_colour),
        colour("SUMMARY", BOLD, use_colour),
        f"  Variants       : {len(rows)}",
        f"  Total bills    : {total_bills}",
        f"  Total spend    : ${total_cost:.3f}",
        f"  Highest acc.   : {best['display']} ({acc_colour(best['acc'], use_colour)})",
        f"  Lowest acc.    : {worst['display']} ({acc_colour(worst['acc'], use_colour)})",
        colour("-" * 60, DIM, use_colour),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

def build_json_output(variants: list[str], summaries: dict[str, dict]) -> str:
    rows = _build_rows(variants, summaries)

    all_scenarios: set[str] = set()
    for s in summaries.values():
        all_scenarios.update(s.get("by_scenario", {}).keys())

    output = {
        "variants": [],
        "scenario_matrix": {},
        "totals": {
            "variants":    len(rows),
            "bills":       sum(r["bills"] for r in rows),
            "cost_usd":    round(sum(r["cost"] for r in rows), 4),
        },
    }

    for r in rows:
        entry: dict = {
            "variant":      r["variant"],
            "display_name": r["display"],
            "rpst_axis":    r["rpst"],
            "model":        r["model"],
            "accuracy":     round(r["acc"] / 100, 4),
            "accuracy_pct": round(r["acc"], 2),
            "cost_usd":     round(r["cost"], 4),
            "avg_turns":    round(r["turns"], 2),
            "avg_tools":    round(r["tools"], 2),
            "avg_latency_s": round(r["lat"], 2),
            "bills_attempted": r["bills"],
            "decisions_correct": r["correct"],
            "by_scenario": {},
        }
        s = summaries[r["variant"]]
        for sc, sc_data in s.get("by_scenario", {}).items():
            acc_frac = sc_data.get("accuracy")
            if acc_frac is None:
                n = sc_data.get("n", sc_data.get("total", 0))
                c = sc_data.get("correct", 0)
                acc_frac = (c / n) if n else 0.0
            entry["by_scenario"][sc] = {
                "accuracy": round(acc_frac, 4),
                "n":        sc_data.get("n", sc_data.get("total", 0)),
                "correct":  sc_data.get("correct", 0),
            }
        output["variants"].append(entry)

    # Scenario matrix: scenario -> variant -> accuracy
    for sc in sorted(all_scenarios):
        output["scenario_matrix"][sc] = {}
        for r in rows:
            s = summaries[r["variant"]]
            sc_data = s.get("by_scenario", {}).get(sc)
            if sc_data is None:
                output["scenario_matrix"][sc][r["variant"]] = None
            else:
                acc_frac = sc_data.get("accuracy")
                if acc_frac is None:
                    n = sc_data.get("n", sc_data.get("total", 0))
                    c = sc_data.get("correct", 0)
                    acc_frac = (c / n) if n else 0.0
                output["scenario_matrix"][sc][r["variant"]] = round(acc_frac, 4)

    rows_sorted = output["variants"]
    if rows_sorted:
        output["totals"]["highest_accuracy"] = {
            "variant": max(rows_sorted, key=lambda x: x["accuracy"])["variant"],
            "accuracy": max(r["accuracy"] for r in rows_sorted),
        }
        output["totals"]["lowest_accuracy"] = {
            "variant": min(rows_sorted, key=lambda x: x["accuracy"])["variant"],
            "accuracy": min(r["accuracy"] for r in rows_sorted),
        }

    return json.dumps(output, indent=2)


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def build_csv_output(variants: list[str], summaries: dict[str, dict]) -> str:
    rows = _build_rows(variants, summaries)
    buf  = io.StringIO()

    # Collect all scenario types for extra columns
    all_scenarios: set[str] = set()
    for s in summaries.values():
        all_scenarios.update(s.get("by_scenario", {}).keys())
    sc_cols = sorted(all_scenarios)

    fieldnames = [
        "variant", "display_name", "rpst_axis", "model",
        "accuracy_pct", "cost_usd", "avg_turns", "avg_tools", "avg_latency_s",
        "bills_attempted", "decisions_correct",
    ] + [f"sc_{sc}" for sc in sc_cols]

    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()

    for r in rows:
        s = summaries[r["variant"]]
        row: dict = {
            "variant":           r["variant"],
            "display_name":      r["display"],
            "rpst_axis":         r["rpst"],
            "model":             r["model"],
            "accuracy_pct":      f"{r['acc']:.2f}",
            "cost_usd":          f"{r['cost']:.4f}",
            "avg_turns":         f"{r['turns']:.2f}",
            "avg_tools":         f"{r['tools']:.2f}",
            "avg_latency_s":     f"{r['lat']:.2f}",
            "bills_attempted":   r["bills"],
            "decisions_correct": r["correct"],
        }
        for sc in sc_cols:
            sc_data  = s.get("by_scenario", {}).get(sc)
            if sc_data is None:
                row[f"sc_{sc}"] = ""
            else:
                acc_frac = sc_data.get("accuracy")
                if acc_frac is None:
                    n = sc_data.get("n", sc_data.get("total", 0))
                    c = sc_data.get("correct", 0)
                    acc_frac = (c / n) if n else 0.0
                row[f"sc_{sc}"] = f"{acc_frac * 100:.1f}"
        writer.writerow(row)

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Compare all experiment variants side by side.")
    parser.add_argument("--no-color", "--no-colour", action="store_true",
                        help="Disable ANSI colour output.")
    parser.add_argument("--json", action="store_true",
                        help="Output comparison as JSON (disables colour/text tables).")
    parser.add_argument("--csv", action="store_true",
                        help="Output comparison as CSV (disables colour/text tables).")
    args = parser.parse_args()

    # Structured output modes skip colour entirely
    machine_output = args.json or args.csv
    use_colour = not args.no_color and not machine_output and sys.stdout.isatty()

    variants = discover_variants()
    if not variants:
        print("No experiment directories with summary.json found.", file=sys.stderr)
        return 1

    summaries: dict[str, dict] = {}
    for v in variants:
        s = load_summary(EXPERIMENTS_DIR / v)
        if s:
            summaries[v] = s

    if not summaries:
        print("No valid summary.json files found.", file=sys.stderr)
        return 1

    if args.json:
        print(build_json_output(list(summaries.keys()), summaries))
        return 0

    if args.csv:
        print(build_csv_output(list(summaries.keys()), summaries), end="")
        return 0

    # ── Default: colour text tables ──────────────────────────────────────────
    title = colour("ERP Agent -- Variant Comparison", BOLD, use_colour)
    print(f"\n{title}")
    print(colour(f"  {len(summaries)} variants  |  experiments/ directory\n", DIM, use_colour))

    print(colour("MAIN STATS", BOLD, use_colour))
    print(build_main_table(list(summaries.keys()), summaries, use_colour))

    print()
    print(colour("SCENARIO BREAKDOWN  (accuracy % per scenario type)", BOLD, use_colour))
    print(build_scenario_matrix(list(summaries.keys()), summaries, use_colour))

    print()
    print(build_summary_footer(list(summaries.keys()), summaries, use_colour))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
