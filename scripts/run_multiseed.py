"""
run_multiseed.py - Run an experiment across multiple seeds and report stability.

Each seed gets its own output directory so results don't overwrite each other.
If a seed matches the config's default seed and results already exist, those
results are reused (no API call). All other seeds run fresh.

Usage:
    python scripts/run_multiseed.py experiments/configs/haiku_ap_persona.yaml --seeds 42,99,7
    python scripts/run_multiseed.py experiments/configs/goal_only_playbook.yaml --seeds 42,99,7 --no-color
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_ROOT = REPO_ROOT / "experiments"

# ANSI colours
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def c(text: str, code: str, use_colour: bool) -> str:
    return f"{code}{text}{RESET}" if use_colour else text


def acc_str(pct: float | None, use_colour: bool) -> str:
    if pct is None:
        return "n/a"
    val = f"{pct:.1f}%"
    if pct >= 90:
        return c(val, GREEN, use_colour)
    if pct >= 70:
        return c(val, YELLOW, use_colour)
    return c(val, RED, use_colour)


def _out_dir(variant_name: str, seed: int, default_seed: int) -> Path:
    """Return the output directory for a given seed.

    If seed matches the config's default seed, use the canonical name so the
    seed-42 results are in the same place whether run directly or via multiseed.
    """
    if seed == default_seed:
        return EXPERIMENTS_ROOT / variant_name
    return EXPERIMENTS_ROOT / f"{variant_name}_seed{seed}"


def _load_summary(out_dir: Path) -> dict | None:
    p = out_dir / "summary.json"
    if p.exists():
        try:
            with p.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _run_one_seed(
    config_path: Path,
    seed: int,
    out_dir: Path,
    use_colour: bool,
) -> dict | None:
    """Invoke run_experiment.py for one seed. Returns the summary dict or None on failure."""
    cmd = [
        sys.executable, "-m", "scripts.run_experiment",
        str(config_path),
        "--seed", str(seed),
        "--out-dir", str(out_dir),
    ]
    print(f"\n  {'Seed':>6}: {seed}  ->  {out_dir.name}")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        print(c(f"  [FAILED] seed {seed} exit {result.returncode}", RED, use_colour))
        return None
    return _load_summary(out_dir)


def _mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(variance)


def _stability_report(
    variant_name: str,
    seeds: list[int],
    summaries: dict[int, dict],
    use_colour: bool,
) -> None:
    print(f"\n{c('-' * 60, DIM, use_colour)}")
    print(c(f"STABILITY REPORT -- {variant_name}", BOLD, use_colour))
    print(c('-' * 60, DIM, use_colour))

    # --- Main stats table ---
    header = f"  {'Seed':>6}  {'Accuracy':>9}  {'Cost':>8}  {'Turns':>6}  {'Tools':>6}"
    print(c(header, BOLD, use_colour))
    print(f"  {'':->6}  {'':->9}  {'':->8}  {'':->6}  {'':->6}")

    acc_vals: list[float] = []
    for seed in seeds:
        s = summaries.get(seed)
        if s is None:
            print(f"  {seed:>6}  {'MISSING':>9}")
            continue
        totals = s.get("totals", {})
        avgs   = s.get("averages", {})
        tc     = s.get("totals_cost", {})
        acc    = (totals.get("accuracy") or 0.0) * 100
        acc_vals.append(acc)
        cost   = tc.get("cost_usd", 0.0)
        turns  = avgs.get("turns") or 0.0
        tools  = avgs.get("tool_calls") or 0.0
        bills_completed = totals.get("bills_completed", 0)
        note = f" ({bills_completed}/{totals.get('bills_attempted',0)} completed)" if bills_completed == 0 else ""
        print(
            f"  {seed:>6}  {acc_str(acc, use_colour):>9}  "
            f"${cost:.3f}    {turns:>5.1f}  {tools:>5.1f}{note}"
        )

    # --- Mean / std ---
    mean, std = _mean_std(acc_vals)
    print(f"\n  Mean accuracy : {acc_str(mean, use_colour)}")
    std_str = f"{std:.1f}pp"
    std_coloured = c(std_str, GREEN if std < 5 else (YELLOW if std < 10 else RED), use_colour)
    print(f"  Std deviation : {std_coloured}")

    # --- Per-scenario variance table ---
    all_scenarios: set[str] = set()
    for s in summaries.values():
        if s:
            all_scenarios.update(s.get("by_scenario", {}).keys())

    if all_scenarios:
        print(f"\n  {c('Scenario breakdown (accuracy %):', BOLD, use_colour)}")
        scen_w = max(len(sc) for sc in all_scenarios) + 2
        seeds_present = [sd for sd in seeds if summaries.get(sd)]

        header2 = f"  {'Scenario':<{scen_w}}" + "".join(f"  {'seed'+str(sd):>8}" for sd in seeds_present) + "   delta"
        print(c(header2, DIM, use_colour))
        print(f"  {'-'*scen_w}" + "  ---------" * len(seeds_present) + "  ------")

        flagged: list[str] = []
        for sc in sorted(all_scenarios):
            row_vals: list[float | None] = []
            cells = [f"  {sc:<{scen_w}}"]
            for sd in seeds_present:
                s = summaries.get(sd, {})
                sc_data = (s or {}).get("by_scenario", {}).get(sc)
                if sc_data is None:
                    cells.append(f"  {'--':>8}")
                    row_vals.append(None)
                else:
                    acc_frac = sc_data.get("accuracy")
                    pct = (acc_frac * 100) if acc_frac is not None else 0.0
                    row_vals.append(pct)
                    cells.append(f"  {acc_str(pct, use_colour):>8}")

            present = [v for v in row_vals if v is not None]
            if len(present) >= 2:
                delta = max(present) - min(present)
                delta_str = f"{delta:>4.0f}pp"
                if delta >= 20:
                    delta_str = c(delta_str, RED, use_colour)
                    flagged.append(sc)
                elif delta >= 10:
                    delta_str = c(delta_str, YELLOW, use_colour)
            else:
                delta_str = "   n/a"
            print("".join(cells) + f"  {delta_str}")

        if flagged:
            print(f"\n  {c('[!] High variance (>=20pp):', YELLOW, use_colour)} {', '.join(flagged)}")

    # --- Verdict ---
    print()
    if len(acc_vals) < 2:
        verdict = c("INSUFFICIENT DATA -- only one seed completed", YELLOW, use_colour)
    elif std < 5.0:
        verdict = c("[OK] STABLE  -- accuracy std dev < 5pp", GREEN, use_colour)
    else:
        verdict = c("[!!] UNSTABLE -- investigate seed-sensitive scenarios", RED, use_colour)
    print(f"  Verdict: {verdict}")
    print(c('-' * 60, DIM, use_colour))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run an experiment config across multiple seeds and report stability."
    )
    parser.add_argument("config", help="Path to a YAML experiment config")
    parser.add_argument(
        "--seeds",
        required=True,
        help="Comma-separated list of seeds, e.g. 42,99,7",
    )
    parser.add_argument(
        "--no-color", "--no-colour",
        action="store_true",
        help="Disable ANSI colour output",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if results already exist for a seed (including the default seed)",
    )
    args = parser.parse_args()
    use_colour = not args.no_color and sys.stdout.isatty()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 2

    # Parse seeds
    try:
        seeds = [int(s.strip()) for s in args.seeds.split(",")]
    except ValueError as exc:
        print(f"Bad --seeds value: {exc}")
        return 2

    # Load the YAML minimally to get the variant name and default seed
    import yaml
    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    variant_name: str = raw["name"]
    default_seed: int = int((raw.get("sample") or {}).get("seed", 42))

    print(c(f"\nMulti-seed run: {variant_name}", BOLD, use_colour))
    print(c(f"  Config : {config_path}", DIM, use_colour))
    print(c(f"  Seeds  : {seeds}", DIM, use_colour))
    print(c(f"  Default: {default_seed}", DIM, use_colour))

    summaries: dict[int, dict] = {}

    for seed in seeds:
        out_dir = _out_dir(variant_name, seed, default_seed)
        existing = _load_summary(out_dir)

        if existing and not args.force:
            print(c(f"\n  Seed {seed}: reusing existing results in {out_dir.name}/", DIM, use_colour))
            summaries[seed] = existing
            acc = (existing.get("totals", {}).get("accuracy") or 0.0) * 100
            print(f"    -> {acc_str(acc, use_colour)} accuracy")
            continue

        summary = _run_one_seed(config_path, seed, out_dir, use_colour)
        summaries[seed] = summary  # may be None if the run failed

    _stability_report(variant_name, seeds, summaries, use_colour)
    return 0


if __name__ == "__main__":
    sys.exit(main())
