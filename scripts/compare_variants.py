"""
compare_variants.py — side-by-side comparison of all experiment variants.

Usage:
    python scripts/compare_variants.py
    python scripts/compare_variants.py --no-color
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
CONFIGS_DIR = EXPERIMENTS_DIR / "configs"

# ANSI colour codes
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def colour(text: str, code: str, use_colour: bool) -> str:
    if not use_colour:
        return text
    return f"{code}{text}{RESET}"


def acc_colour(pct: float, use_colour: bool) -> str:
    val = f"{pct:.1f}%"
    if pct >= 90:
        return colour(val, GREEN, use_colour)
    if pct >= 70:
        return colour(val, YELLOW, use_colour)
    return colour(val, RED, use_colour)


def strip_ansi(s: str) -> str:
    """Return plain text length (ignoring ANSI escape sequences)."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', s)


def pad(s: str, width: int, align: str = "<") -> str:
    """Pad a (possibly ANSI-coloured) string to visible width."""
    visible = len(strip_ansi(s))
    padding = max(0, width - visible)
    if align == ">":
        return " " * padding + s
    return s + " " * padding


def load_summary(variant_dir: Path) -> dict | None:
    p = variant_dir / "summary.json"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def load_rpst(variant_name: str) -> str:
    """Try to parse the RPST axis from the config YAML description."""
    config_path = CONFIGS_DIR / f"{variant_name}.yaml"
    if not config_path.exists():
        return "—"
    try:
        text = config_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            low = line.strip().lower()
            if "rpst axis" in low:
                # e.g. "RPST axis varied: Skills/Tools"
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip().split("(")[0].strip()
    except Exception:
        pass
    return "—"


def discover_variants() -> list[str]:
    """Return canonical variant names, excluding multi-seed subdirectories.

    Seed runs live in directories like haiku_ap_persona_seed99/ — they're
    sub-runs of a variant, not independent variants. Exclude them here so
    compare_variants shows the main table cleanly. Use run_multiseed.py to
    inspect seed-level stability.
    """
    dirs = sorted(
        d.name for d in EXPERIMENTS_DIR.iterdir()
        if d.is_dir()
        and (d / "summary.json").exists()
        and "_seed" not in d.name
    )
    return dirs


def build_main_table(variants: list[str], summaries: dict[str, dict], use_colour: bool) -> str:
    cols = ["Variant", "RPST Axis", "Model", "Accuracy", "Cost", "Turns", "Tools", "Latency(s)"]
    col_w = [max(len(c), 24) for c in cols]
    col_w[0] = max(col_w[0], max(len(v) for v in variants))
    col_w[1] = 22
    col_w[2] = 28
    col_w[3] = 10
    col_w[4] = 9
    col_w[5] = 7
    col_w[6] = 7
    col_w[7] = 10

    rows = []
    for v in variants:
        s = summaries[v]
        totals  = s.get("totals", {})
        avgs    = s.get("averages", {})
        tc      = s.get("totals_cost", {})
        acc_raw = totals.get("accuracy", 0.0) * 100
        model   = s.get("model", "?")
        # shorten model name
        model = model.replace("claude-haiku-4-5-20251001", "haiku-4.5").replace("claude-sonnet-4-6", "sonnet-4.6")
        cost    = tc.get("cost_usd", 0.0)
        turns   = avgs.get("turns", 0.0)
        tools   = avgs.get("tool_calls", 0.0)
        lat     = avgs.get("latency_ms", 0.0) / 1000.0
        rpst    = load_rpst(v)
        rows.append({
            "variant": v,
            "rpst":    rpst,
            "model":   model,
            "acc":     acc_raw,
            "cost":    cost,
            "turns":   turns,
            "tools":   tools,
            "lat":     lat,
        })

    sep = "+" + "+".join("-" * (w + 2) for w in col_w) + "+"
    header_cells = [pad(colour(c, BOLD, use_colour), col_w[i]) for i, c in enumerate(cols)]
    header = "| " + " | ".join(header_cells) + " |"

    lines = [sep, header, sep]
    for r in rows:
        cells = [
            pad(r["variant"], col_w[0]),
            pad(r["rpst"][:col_w[1]], col_w[1]),
            pad(r["model"][:col_w[2]], col_w[2]),
            pad(acc_colour(r["acc"], use_colour), col_w[3], ">"),
            pad(f"${r['cost']:.3f}", col_w[4], ">"),
            pad(f"{r['turns']:.1f}", col_w[5], ">"),
            pad(f"{r['tools']:.1f}", col_w[6], ">"),
            pad(f"{r['lat']:.1f}s", col_w[7], ">"),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(sep)
    return "\n".join(lines)


def build_scenario_matrix(variants: list[str], summaries: dict[str, dict], use_colour: bool) -> str:
    # Collect all scenario types across all variants
    all_scenarios: set[str] = set()
    for s in summaries.values():
        for sc in s.get("by_scenario", {}).keys():
            all_scenarios.add(sc)
    scenarios = sorted(all_scenarios)

    if not scenarios:
        return "(no per-scenario data available)"

    scen_w = max(len(sc) for sc in scenarios) + 2
    var_w  = max(max(len(v) for v in variants), 7) + 2

    # Header row
    header_cells = [pad(colour("Scenario", BOLD, use_colour), scen_w)]
    for v in variants:
        header_cells.append(pad(colour(v[:var_w-1], BOLD, use_colour), var_w))
    sep = "+" + "+".join("-" * (w + 2) for w in [scen_w] + [var_w] * len(variants)) + "+"
    header = "| " + " | ".join(header_cells) + " |"

    lines = [sep, header, sep]
    for sc in scenarios:
        cells = [pad(sc, scen_w)]
        for v in variants:
            sc_data = summaries[v].get("by_scenario", {}).get(sc)
            if sc_data is None:
                cells.append(pad(colour("  —  ", DIM, use_colour), var_w))
            else:
                # by_scenario uses accuracy (0–1 float) and n
                acc_frac = sc_data.get("accuracy", None)
                if acc_frac is not None:
                    pct = acc_frac * 100
                else:
                    correct = sc_data.get("correct", 0)
                    total   = sc_data.get("n", sc_data.get("total", 0))
                    pct     = (correct / total * 100) if total else 0.0
                cell    = acc_colour(pct, use_colour)
                cells.append(pad(cell, var_w))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(sep)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare all experiment variants side by side.")
    parser.add_argument("--no-color", "--no-colour", action="store_true",
                        help="Disable ANSI colour output (useful for piping to files).")
    args = parser.parse_args()
    use_colour = not args.no_color and sys.stdout.isatty()

    variants = discover_variants()
    if not variants:
        print("No experiment directories with summary.json found.")
        return 1

    summaries: dict[str, dict] = {}
    for v in variants:
        s = load_summary(EXPERIMENTS_DIR / v)
        if s:
            summaries[v] = s

    if not summaries:
        print("No valid summary.json files found.")
        return 1

    title = colour("ERP Agent — Variant Comparison", BOLD, use_colour)
    print(f"\n{title}")
    print(colour(f"  {len(summaries)} variants discovered under experiments/\n", DIM, use_colour))

    print(colour("MAIN STATS", BOLD, use_colour))
    print(build_main_table(list(summaries.keys()), summaries, use_colour))

    print()
    print(colour("SCENARIO BREAKDOWN  (accuracy % per scenario type)", BOLD, use_colour))
    print(build_scenario_matrix(list(summaries.keys()), summaries, use_colour))

    # Totals line
    total_bills = sum(s.get("totals", {}).get("bills_attempted", 0) for s in summaries.values())
    total_cost  = sum(s.get("totals_cost", {}).get("cost_usd", 0.0) for s in summaries.values())
    print()
    print(colour(f"  Total across all variants: {total_bills} bills  |  ${total_cost:.3f} API spend", DIM, use_colour))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
