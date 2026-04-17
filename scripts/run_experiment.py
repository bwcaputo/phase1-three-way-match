"""
Experiment runner for RPST variants of the three-way-match agent.

Reads a YAML/JSON config that defines a single variant (which playbook,
which toolset, which model), runs the agent over a sample of bills from the
playground manifest, and writes both per-run and aggregate results to disk.

    python -m scripts.run_experiment experiments/configs/baseline.yaml
    python -m scripts.run_experiment experiments/configs/baseline.yaml --dry-run
    python -m scripts.run_experiment experiments/configs/baseline.yaml --limit 5

Per-bill results stream to ``experiments/<name>/runs.jsonl`` as the run
progresses, so a crash or Ctrl-C does not lose work. The aggregate
``summary.json`` is written at the end and includes accuracy vs. ground
truth, average turns, total cost, and a per-scenario breakdown.

Design notes:
- The config schema deliberately supports overrides (system_prompt, tools)
  that the baseline does not exercise. Future variants plug in here.
- Cost is computed per run from per-turn token counts and a configurable
  per-model pricing table. Pricing lives in the config (or falls back to a
  default table) so it stays auditable.
- Ground-truth comparison is exact-match on the recommended_action against
  ``expected_outcome`` from the manifest. Approve/route/block only — no
  partial credit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Make `src` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from src.agent import AgentResult, run_agent
from src.odoo_client import OdooClient


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "playground_manifest.json"
EXPERIMENTS_ROOT = REPO_ROOT / "experiments"

# Fallback pricing table (USD per million tokens). The config can override.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-opus-4-6": {"input_per_mtok": 15.00, "output_per_mtok": 75.00},
    "claude-haiku-4-5-20251001": {"input_per_mtok": 1.00, "output_per_mtok": 5.00},
}

# Per-run cost ceilings from the project's cost-control rules. If a single
# bill exceeds this for its model, the runner prints a loud warning.
PER_RUN_COST_CEILINGS_USD: dict[str, float] = {
    "claude-sonnet-4-6": 0.15,
    "claude-haiku-4-5-20251001": 0.06,
}

# The manifest uses short labels; the agent's Action enum uses canonical names.
# Normalize before comparing so the runner doesn't false-flag correct calls.
EXPECTED_OUTCOME_ALIASES: dict[str, str] = {
    "route": "route_for_review",
}


def _canonicalize_expected(label: str) -> str:
    return EXPECTED_OUTCOME_ALIASES.get(label, label)

console = Console()


# --- Config dataclasses ---


@dataclass
class SampleConfig:
    strategy: str = "stratified"  # all | first_n | random_n | stratified
    n: int = 30
    per_scenario: Optional[int] = None  # if set with strategy=stratified, take this many from EACH scenario type (flat allocation)
    seed: int = 42
    scenarios: Optional[list[str]] = None  # filter to these scenario_types


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-6"
    max_turns: int = 12
    system_prompt: Optional[str] = None
    tools: Optional[list[dict]] = None


@dataclass
class ExperimentConfig:
    name: str
    description: str
    agent: AgentConfig
    sample: SampleConfig
    pricing: dict[str, dict[str, float]] = field(default_factory=dict)
    env_overrides: dict[str, str] = field(default_factory=dict)  # injected before each run
    raw: dict[str, Any] = field(default_factory=dict)  # original YAML for the record

    @classmethod
    def load(cls, path: Path) -> "ExperimentConfig":
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        agent_raw = data.get("agent") or {}
        sample_raw = data.get("sample") or {}
        per_scenario_raw = sample_raw.get("per_scenario")
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            agent=AgentConfig(
                model=agent_raw.get("model", "claude-sonnet-4-6"),
                max_turns=int(agent_raw.get("max_turns", 12)),
                system_prompt=agent_raw.get("system_prompt"),
                tools=agent_raw.get("tools"),
            ),
            sample=SampleConfig(
                strategy=sample_raw.get("strategy", "stratified"),
                n=int(sample_raw.get("n", 30)),
                per_scenario=int(per_scenario_raw) if per_scenario_raw is not None else None,
                seed=int(sample_raw.get("seed", 42)),
                scenarios=sample_raw.get("scenarios"),
            ),
            pricing=data.get("pricing") or {},
            env_overrides={str(k): str(v) for k, v in (data.get("env_overrides") or {}).items()},
            raw=data,
        )


# --- Sampling ---


def select_bills(manifest: list[dict], cfg: SampleConfig) -> list[dict]:
    """Apply scenario filter and sampling strategy to the manifest."""
    pool = manifest
    if cfg.scenarios:
        wanted = set(cfg.scenarios)
        pool = [b for b in pool if b["scenario_type"] in wanted]

    if cfg.strategy == "all":
        return list(pool)
    if cfg.strategy == "first_n":
        return list(pool[: cfg.n])
    if cfg.strategy == "random_n":
        rng = random.Random(cfg.seed)
        return rng.sample(pool, k=min(cfg.n, len(pool)))
    if cfg.strategy == "stratified":
        if cfg.per_scenario is not None:
            return _stratified_flat(pool, cfg.per_scenario, cfg.seed)
        return _stratified(pool, cfg.n, cfg.seed)
    raise ValueError(f"Unknown sample strategy: {cfg.strategy}")


def _stratified_flat(pool: list[dict], per_scenario: int, seed: int) -> list[dict]:
    """Flat allocation: take ``per_scenario`` bills from EACH scenario type.

    Equal weight per category — what the project's cost-control rules require
    for the default 30-bill experiment (5 per scenario × 6 scenarios = 30).
    """
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = {}
    for bill in pool:
        buckets.setdefault(bill["scenario_type"], []).append(bill)
    chosen: list[dict] = []
    for scenario, bucket in buckets.items():
        take = min(per_scenario, len(bucket))
        chosen.extend(rng.sample(bucket, k=take))
    rng.shuffle(chosen)
    return chosen


def _stratified(pool: list[dict], n: int, seed: int) -> list[dict]:
    """Allocate the budget proportionally across scenario_type, then sample.

    Always picks at least one bill per non-empty scenario so every category
    is represented. The remainder is allocated by the size of each bucket.
    """
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = {}
    for bill in pool:
        buckets.setdefault(bill["scenario_type"], []).append(bill)

    total = len(pool)
    if total == 0 or n == 0:
        return []

    # Floor allocation by proportion + at-least-one for every bucket.
    raw_quota = {k: max(1, round(n * len(v) / total)) for k, v in buckets.items()}
    # If the rounding pushed us over n, trim from the largest buckets first.
    while sum(raw_quota.values()) > n:
        biggest = max(raw_quota, key=lambda k: raw_quota[k])
        if raw_quota[biggest] <= 1:
            break
        raw_quota[biggest] -= 1

    chosen: list[dict] = []
    for scenario, quota in raw_quota.items():
        bucket = buckets[scenario]
        take = min(quota, len(bucket))
        chosen.extend(rng.sample(bucket, k=take))
    rng.shuffle(chosen)
    return chosen


# --- Cost ---


def compute_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, dict[str, float]],
) -> float:
    rate = pricing.get(model) or DEFAULT_PRICING.get(model)
    if rate is None:
        return 0.0
    return round(
        (input_tokens / 1_000_000) * rate["input_per_mtok"]
        + (output_tokens / 1_000_000) * rate["output_per_mtok"],
        6,
    )


# --- Run loop ---


def run_one_bill(
    bill: dict,
    cfg: ExperimentConfig,
    client: Optional[OdooClient],
) -> dict:
    """Run the agent on a single bill and return a flat dict for the JSONL log."""
    invoice_number = bill["bill_name"]
    expected = _canonicalize_expected(bill["expected_outcome"])
    scenario = bill["scenario_type"]

    started = time.perf_counter()
    try:
        result: AgentResult = run_agent(
            invoice_number=invoice_number,
            client=client,
            model=cfg.agent.model,
            max_turns=cfg.agent.max_turns,
            system_prompt=cfg.agent.system_prompt,
            tools=cfg.agent.tools,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "bill_name": invoice_number,
            "scenario_type": scenario,
            "expected_outcome": expected,
            "decision": None,
            "decision_match": False,
            "rationale": None,
            "discrepancy_codes": [],
            "turns": 0,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_ms": elapsed_ms,
            "cost_usd": 0.0,
            "stop_reason": None,
            "error": f"{type(exc).__name__}: {exc}",
            "summary": "",
        }

    decision = result.match_result.recommended_action if result.match_result else None
    discrepancy_codes = (
        [d.code for d in result.match_result.discrepancies]
        if result.match_result
        else []
    )
    rationale = result.match_result.rationale if result.match_result else None
    cost_usd = compute_cost_usd(
        cfg.agent.model, result.input_tokens, result.output_tokens, cfg.pricing
    )

    return {
        "bill_name": invoice_number,
        "scenario_type": scenario,
        "expected_outcome": expected,
        "decision": decision,
        "decision_match": decision == expected,
        "rationale": rationale,
        "discrepancy_codes": discrepancy_codes,
        "turns": result.turns,
        "tool_calls": result.tool_calls,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.input_tokens + result.output_tokens,
        "latency_ms": result.latency_ms,
        "cost_usd": cost_usd,
        "stop_reason": result.stop_reason,
        "error": result.error,
        "summary": result.summary,
    }


# --- Aggregation ---


def aggregate(runs: list[dict], cfg: ExperimentConfig) -> dict:
    """Build the summary.json payload from a list of per-bill run records."""
    n = len(runs)
    completed = [r for r in runs if r["error"] is None and r["decision"] is not None]
    correct = [r for r in completed if r["decision_match"]]

    by_scenario: dict[str, dict[str, Any]] = {}
    for r in runs:
        s = r["scenario_type"]
        bucket = by_scenario.setdefault(
            s,
            {
                "n": 0,
                "completed": 0,
                "correct": 0,
                "errors": 0,
                "decisions": {"approve": 0, "route_for_review": 0, "block": 0, "none": 0},
            },
        )
        bucket["n"] += 1
        if r["error"] is not None:
            bucket["errors"] += 1
        if r["decision"] is None:
            bucket["decisions"]["none"] += 1
        else:
            bucket["completed"] += 1
            bucket["decisions"][r["decision"]] = bucket["decisions"].get(r["decision"], 0) + 1
            if r["decision_match"]:
                bucket["correct"] += 1
    for bucket in by_scenario.values():
        denom = bucket["completed"]
        bucket["accuracy"] = round(bucket["correct"] / denom, 4) if denom else None

    def _mean(seq: list[float]) -> Optional[float]:
        return round(sum(seq) / len(seq), 2) if seq else None

    return {
        "experiment": cfg.name,
        "description": cfg.description,
        "model": cfg.agent.model,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "config": cfg.raw,
        "totals": {
            "bills_attempted": n,
            "bills_completed": len(completed),
            "bills_errored": n - len(completed),
            "decisions_correct": len(correct),
            "accuracy": round(len(correct) / len(completed), 4) if completed else None,
        },
        "averages": {
            "turns": _mean([r["turns"] for r in completed]),
            "tool_calls": _mean([r["tool_calls"] for r in completed]),
            "latency_ms": _mean([r["latency_ms"] for r in completed]),
            "input_tokens": _mean([r["input_tokens"] for r in completed]),
            "output_tokens": _mean([r["output_tokens"] for r in completed]),
            "cost_usd": _mean([r["cost_usd"] for r in completed]),
        },
        "totals_cost": {
            "input_tokens": sum(r["input_tokens"] for r in completed),
            "output_tokens": sum(r["output_tokens"] for r in completed),
            "cost_usd": round(sum(r["cost_usd"] for r in completed), 4),
        },
        "by_scenario": by_scenario,
    }


def render_summary(summary: dict) -> None:
    t = summary["totals"]
    a = summary["averages"]
    c = summary["totals_cost"]
    console.print()
    console.print(
        f"[bold]{summary['experiment']}[/bold] — {summary['model']} — "
        f"{t['bills_completed']}/{t['bills_attempted']} completed"
    )
    acc = t["accuracy"]
    acc_str = f"{acc:.1%}" if acc is not None else "n/a"
    console.print(f"  Accuracy: [bold]{acc_str}[/bold]  ({t['decisions_correct']} correct)")
    console.print(
        f"  Avg turns: {a['turns']}  •  Avg tool calls: {a['tool_calls']}  •  "
        f"Avg latency: {a['latency_ms']} ms"
    )
    console.print(
        f"  Total cost: [bold]${c['cost_usd']:.4f}[/bold]  "
        f"({c['input_tokens']} in / {c['output_tokens']} out tokens)"
    )

    tbl = Table(title="By scenario", show_lines=False)
    tbl.add_column("Scenario")
    tbl.add_column("N", justify="right")
    tbl.add_column("Correct", justify="right")
    tbl.add_column("Accuracy", justify="right")
    tbl.add_column("Errors", justify="right")
    for scenario, bucket in sorted(summary["by_scenario"].items()):
        acc = bucket["accuracy"]
        acc_str = f"{acc:.1%}" if acc is not None else "n/a"
        tbl.add_row(
            scenario,
            str(bucket["n"]),
            str(bucket["correct"]),
            acc_str,
            str(bucket["errors"]),
        )
    console.print(tbl)


# --- CLI ---


def main() -> int:
    load_dotenv(override=True)
    parser = argparse.ArgumentParser(description="Run an RPST experiment over the playground.")
    parser.add_argument("config", help="Path to a YAML experiment config")
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="Path to playground_manifest.json",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Override the output directory (default: experiments/<name>/)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the sample to this many bills (for quick smoke tests)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve sampling and write the plan only — do not call the agent",
    )
    parser.add_argument(
        "--reaggregate",
        action="store_true",
        help="Re-read existing runs.jsonl and rewrite summary.json (no API calls)",
    )
    parser.add_argument(
        "--rebuild-viewer",
        action="store_true",
        help="Rebuild docs/viewer/index.html after the experiment completes",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        console.print(f"[red]Config not found:[/red] {config_path}")
        return 2

    cfg = ExperimentConfig.load(config_path)

    # Apply any env overrides declared in the config (e.g. PRICE_VARIANCE_LOGIC=or).
    # These mutate the process environment so they affect the deterministic matcher.
    for k, v in cfg.env_overrides.items():
        os.environ[k] = v
    if cfg.env_overrides:
        console.print(f"[dim]env_overrides applied: {cfg.env_overrides}[/dim]")

    out_dir_for_reagg = Path(args.out_dir) if args.out_dir else EXPERIMENTS_ROOT / cfg.name
    if args.reaggregate:
        runs_path = out_dir_for_reagg / "runs.jsonl"
        summary_path = out_dir_for_reagg / "summary.json"
        if not runs_path.exists():
            console.print(f"[red]No existing runs.jsonl at[/red] {runs_path}")
            return 2
        runs: list[dict] = []
        with runs_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rec["expected_outcome"] = _canonicalize_expected(rec["expected_outcome"])
                rec["decision_match"] = (
                    rec["decision"] is not None
                    and rec["decision"] == rec["expected_outcome"]
                )
                runs.append(rec)
        summary = aggregate(runs, cfg)
        with summary_path.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        render_summary(summary)
        console.print(f"\nReaggregated from {runs_path}\nSummary: {summary_path}\n")
        return 0

    manifest_path = Path(args.manifest)
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    bills = select_bills(manifest, cfg.sample)
    if args.limit is not None:
        bills = bills[: args.limit]

    out_dir = Path(args.out_dir) if args.out_dir else EXPERIMENTS_ROOT / cfg.name
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out_dir / "runs.jsonl"
    summary_path = out_dir / "summary.json"
    plan_path = out_dir / "plan.json"

    plan = {
        "experiment": cfg.name,
        "model": cfg.agent.model,
        "sample_strategy": cfg.sample.strategy,
        "sample_n_requested": cfg.sample.n,
        "sample_n_actual": len(bills),
        "bills": [
            {"bill_name": b["bill_name"], "scenario_type": b["scenario_type"]}
            for b in bills
        ],
    }
    with plan_path.open("w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)
    console.print(
        f"[cyan]{cfg.name}[/cyan]: {len(bills)} bills selected "
        f"({cfg.sample.strategy}). Plan -> {plan_path}"
    )

    if args.dry_run:
        # Print scenario distribution so the user can see the stratification.
        dist: dict[str, int] = {}
        for b in bills:
            dist[b["scenario_type"]] = dist.get(b["scenario_type"], 0) + 1
        tbl = Table(title="Sample distribution (dry run)")
        tbl.add_column("Scenario")
        tbl.add_column("Count", justify="right")
        for k, v in sorted(dist.items()):
            tbl.add_row(k, str(v))
        console.print(tbl)
        console.print("[dim]Dry run — no agent calls made.[/dim]")
        return 0

    # Single shared OdooClient across the run — avoids per-bill XML-RPC handshake.
    client = OdooClient()

    runs: list[dict] = []
    with runs_path.open("w", encoding="utf-8") as out_f, Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Running {cfg.name}", total=len(bills))
        for bill in bills:
            record = run_one_bill(bill, cfg, client)
            runs.append(record)
            out_f.write(json.dumps(record, default=str) + "\n")
            out_f.flush()
            tag = (
                "[green]PASS[/green]" if record["decision_match"]
                else "[red]FAIL[/red]" if record["error"] is None
                else "[yellow]ERR[/yellow]"
            )
            progress.console.print(
                f"  {tag} {record['bill_name']:25s} {record['scenario_type']:22s} "
                f"-> {record['decision'] or 'ERROR'}  "
                f"({record['turns']}t, ${record['cost_usd']:.4f})"
            )
            ceiling = PER_RUN_COST_CEILINGS_USD.get(cfg.agent.model)
            if ceiling is not None and record["cost_usd"] > ceiling:
                progress.console.print(
                    f"    [bold red]⚠ COST ALERT[/bold red] "
                    f"${record['cost_usd']:.4f} exceeds per-run ceiling "
                    f"${ceiling:.2f} for {cfg.agent.model}. Investigate context bloat."
                )
            progress.advance(task)

    summary = aggregate(runs, cfg)
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    render_summary(summary)
    console.print(f"\nResults: {runs_path}\nSummary: {summary_path}\n")

    if args.rebuild_viewer:
        import subprocess as _sp
        viewer_script = REPO_ROOT / "scripts" / "build_viewer.py"
        console.print("[bold]Rebuilding viewer...[/bold]")
        try:
            _sp.run([sys.executable, str(viewer_script)], check=True, cwd=str(REPO_ROOT))
            console.print(
                "[green]Viewer rebuilt.[/green] "
                "Open [cyan]docs/viewer/index.html[/cyan] to see results."
            )
        except _sp.CalledProcessError as exc:
            console.print(f"[yellow]Viewer rebuild failed (exit {exc.returncode}).[/yellow]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
