"""
Guided experiment wizard for the three-way match agent lab.

Walks through an interactive CLI to configure a new RPST variant, previews
the generated config, saves it to experiments/configs/<name>.yaml, runs the
experiment, and rebuilds the scorecard viewer — without any manual YAML editing.

Usage:
    python scripts/new_experiment.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

# Make `src` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "experiments" / "configs"
BASELINE_SUMMARY = REPO_ROOT / "experiments" / "baseline" / "summary.json"

console = Console()

# ---------------------------------------------------------------------------
# Pricing (USD per million tokens).
# ---------------------------------------------------------------------------
KNOWN_MODELS: dict[str, dict] = {
    "claude-haiku-4-5-20251001": {
        "label": "claude-haiku-4-5-20251001  ($1/$5 per Mtok)  — fast, cheap",
        "input_per_mtok": 1.00,
        "output_per_mtok": 5.00,
    },
    "claude-sonnet-4-6": {
        "label": "claude-sonnet-4-6          ($3/$15 per Mtok) — baseline default",
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
    },
}

# Preset role prompts.
CFO_SYSTEM_PROMPT = """\
You are a financial risk assistant supporting a CFO reviewing vendor invoices
before payment is released.

Your job for every invoice:
1. Call fetch_vendor_invoice to load the invoice.
2. From the invoice, read the PO reference. Call fetch_purchase_order on that PO.
3. Call fetch_goods_receipt for the same PO. No receipt is a payment-stop finding.
4. Call check_for_duplicate_invoices using the vendor_id and the invoice total.
5. Call run_three_way_match. Its recommended_action is the authoritative decision.
6. Report to the CFO: the dollar exposure, the recommended action, and the
   single most important reason for that action. Be direct — one short paragraph.

Ground rules:
- Never compute totals, quantities, or variances yourself. run_three_way_match
  is the only source of the decision and the dollar figures. Do not override it.
- Surface missing documents as payment-stop findings.
- Lead with the dollar amount and the action. The CFO does not need procedural
  detail unless there is a discrepancy worth escalating.\
"""


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

def _load_baseline_averages() -> dict:
    """Load token/cost averages from the baseline summary, for cost estimates."""
    if not BASELINE_SUMMARY.exists():
        return {}
    import json
    with BASELINE_SUMMARY.open(encoding="utf-8") as f:
        data = json.load(f)
    return data.get("averages", {})


def _estimate_cost(model: str, bills: int, per_bill_input: float, per_bill_output: float) -> str:
    """Return a human-readable cost estimate string."""
    if model in KNOWN_MODELS:
        p = KNOWN_MODELS[model]
        cost = bills * (
            per_bill_input / 1_000_000 * p["input_per_mtok"]
            + per_bill_output / 1_000_000 * p["output_per_mtok"]
        )
        return f"~${cost:.2f}"
    return "unknown (custom model)"


def _validate_name(name: str) -> Optional[str]:
    """Return an error string, or None if valid."""
    if not name:
        return "Name cannot be empty."
    if name != name.lower():
        return "Name must be lowercase."
    if " " in name:
        return "Name cannot contain spaces (use underscores)."
    config_path = CONFIGS_DIR / f"{name}.yaml"
    if config_path.exists():
        return f"Config already exists: {config_path}"
    return None


def _ask_name() -> str:
    """Prompt for a valid experiment name, looping until valid or user overrides."""
    while True:
        name = Prompt.ask("Name this experiment [dim](lowercase, no spaces, e.g. haiku_test)[/dim]")
        err = _validate_name(name)
        if err is None:
            return name
        if "already exists" in err:
            console.print(f"  [yellow]{err}[/yellow]")
            if Confirm.ask("  Overwrite?", default=False):
                return name
        else:
            console.print(f"  [red]{err}[/red]")


def _ask_matcher() -> Optional[str]:
    """Return 'or' if OR logic requested, None for AND (default)."""
    choice = Prompt.ask(
        "Matcher logic [dim][[/dim]AND[dim]/[/dim]OR[dim]] (default: AND)[/dim]",
        default="AND",
    ).strip().upper()
    return "or" if choice == "OR" else None


def _ask_sample_size() -> int:
    """Return bills per scenario (default 5 → 30 total)."""
    change = Confirm.ask(
        "Sample: 5 per scenario × 6 scenarios = 30 bills (default). Change?",
        default=False,
    )
    if not change:
        return 5
    raw = Prompt.ask("Bills per scenario", default="5")
    try:
        n = int(raw)
        if n < 1:
            raise ValueError
        return n
    except ValueError:
        console.print("  [yellow]Invalid number, using 5.[/yellow]")
        return 5


def _ask_model() -> str:
    """Prompt for a model choice and return the model string."""
    console.print("  [1] " + KNOWN_MODELS["claude-haiku-4-5-20251001"]["label"])
    console.print("  [2] " + KNOWN_MODELS["claude-sonnet-4-6"]["label"])
    console.print("  [3] Other (enter model string)")
    choice = Prompt.ask("Which model?", choices=["1", "2", "3"], default="1")
    if choice == "1":
        return "claude-haiku-4-5-20251001"
    if choice == "2":
        return "claude-sonnet-4-6"
    return Prompt.ask("Enter model string").strip()


def _ask_multiline_prompt(label: str = "system prompt") -> str:
    """Read a multiline string from stdin. Empty line terminates input."""
    console.print(f"Paste the {label}. Enter an empty line when done:")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _build_config(
    name: str,
    description: str,
    model: str,
    system_prompt: Optional[str],
    matcher_logic: Optional[str],
    per_scenario: int,
) -> dict:
    """Build the config dict matching the YAML structure used by run_experiment.py."""
    pricing: dict = {}
    for m, p in KNOWN_MODELS.items():
        pricing[m] = {
            "input_per_mtok": p["input_per_mtok"],
            "output_per_mtok": p["output_per_mtok"],
        }

    cfg: dict = {
        "name": name,
        "description": description,
        "agent": {
            "model": model,
            "max_turns": 12,
            "system_prompt": system_prompt,
            "tools": None,
        },
        "sample": {
            "strategy": "stratified",
            "per_scenario": per_scenario,
            "seed": 42,
            "scenarios": None,
        },
        "pricing": pricing,
    }
    if matcher_logic == "or":
        cfg["env_overrides"] = {"PRICE_VARIANCE_LOGIC": "or"}

    return cfg


def _render_preview(
    name: str,
    description: str,
    model: str,
    role_label: str,
    matcher_logic: Optional[str],
    per_scenario: int,
    avgs: dict,
) -> None:
    bills = per_scenario * 6
    est_cost = _estimate_cost(
        model, bills,
        avgs.get("input_tokens", 9540.6),
        avgs.get("output_tokens", 881.73),
    )
    matcher_str = "OR" if matcher_logic == "or" else "AND"

    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("key", style="dim")
    tbl.add_column("val")
    tbl.add_row("name",        name)
    tbl.add_row("description", description)
    tbl.add_row("model",       model)
    tbl.add_row("role",        role_label)
    tbl.add_row("matcher",     matcher_str)
    tbl.add_row("sample",      f"{bills} bills (stratified, {per_scenario}/scenario)")
    tbl.add_row("est. cost",   est_cost)

    console.print(Panel(tbl, title="--- Config Preview ---", border_style="cyan"))


def _write_config(name: str, cfg: dict) -> Path:
    config_path = CONFIGS_DIR / f"{name}.yaml"
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return config_path


def _run_experiment(config_path: Path) -> int:
    """Run the experiment and rebuild the viewer. Returns subprocess exit code."""
    console.print(f"\n[bold]Running experiment...[/bold]")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.run_experiment",
             str(config_path), "--rebuild-viewer"],
            cwd=str(REPO_ROOT),
        )
        return result.returncode
    except FileNotFoundError:
        console.print("[red]Python interpreter not found.[/red]")
        return 1
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Unexpected error:[/red] {exc}")
        return 1


# ---------------------------------------------------------------------------
# The four experiment paths.
# ---------------------------------------------------------------------------

def path_model(avgs: dict) -> None:
    console.print(Rule("Model swap"))
    model = _ask_model()
    name = _ask_name()
    description = Prompt.ask("One-line description")
    matcher_logic = _ask_matcher()
    per_scenario = _ask_sample_size()

    cfg = _build_config(name, description, model, None, matcher_logic, per_scenario)
    _render_preview(name, description, model, "AP Clerk (default)", matcher_logic, per_scenario, avgs)

    if not Confirm.ask("Save and run?", default=True):
        console.print("[dim]Aborted.[/dim]")
        return

    config_path = _write_config(name, cfg)
    console.print(f"Saved config to [cyan]{config_path}[/cyan]")
    rc = _run_experiment(config_path)
    if rc != 0:
        console.print(
            "\n[yellow]Experiment exited with an error.[/yellow]\n"
            "If Odoo is not running, start it with: [cyan]docker compose up -d[/cyan]"
        )


def path_role(avgs: dict) -> None:
    console.print(Rule("Role swap"))
    console.print("Which role?")
    console.print("  [1] AP Clerk (default — null system prompt)")
    console.print("  [2] CFO persona")
    console.print("  [3] Custom (paste your own system prompt)")
    role_choice = Prompt.ask("Role", choices=["1", "2", "3"], default="1")

    if role_choice == "1":
        system_prompt = None
        role_label = "AP Clerk (default)"
    elif role_choice == "2":
        system_prompt = CFO_SYSTEM_PROMPT
        role_label = "CFO persona"
    else:
        system_prompt = _ask_multiline_prompt("system prompt")
        if not system_prompt.strip():
            console.print("[yellow]Empty prompt — using null (AP Clerk default).[/yellow]")
            system_prompt = None
            role_label = "AP Clerk (default)"
        else:
            role_label = "Custom"

    model = Prompt.ask(
        "Model [dim](default: claude-haiku-4-5-20251001)[/dim]",
        default="claude-haiku-4-5-20251001",
    ).strip()
    name = _ask_name()
    description = Prompt.ask("One-line description")
    matcher_logic = _ask_matcher()
    per_scenario = _ask_sample_size()

    cfg = _build_config(name, description, model, system_prompt, matcher_logic, per_scenario)
    _render_preview(name, description, model, role_label, matcher_logic, per_scenario, avgs)

    if not Confirm.ask("Save and run?", default=True):
        console.print("[dim]Aborted.[/dim]")
        return

    config_path = _write_config(name, cfg)
    console.print(f"Saved config to [cyan]{config_path}[/cyan]")
    rc = _run_experiment(config_path)
    if rc != 0:
        console.print(
            "\n[yellow]Experiment exited with an error.[/yellow]\n"
            "If Odoo is not running, start it with: [cyan]docker compose up -d[/cyan]"
        )


def path_policy(avgs: dict) -> None:
    console.print(Rule("Policy swap"))
    matcher_raw = Prompt.ask(
        "Matcher logic [dim][[/dim]AND[dim]/[/dim]OR[dim]][/dim]",
        choices=["AND", "OR", "and", "or"],
        default="OR",
    ).strip().upper()
    matcher_logic: Optional[str] = "or" if matcher_raw == "OR" else None

    model = Prompt.ask(
        "Model [dim](default: claude-haiku-4-5-20251001)[/dim]",
        default="claude-haiku-4-5-20251001",
    ).strip()
    name = _ask_name()
    description = Prompt.ask("One-line description")
    per_scenario = _ask_sample_size()

    cfg = _build_config(name, description, model, None, matcher_logic, per_scenario)
    _render_preview(name, description, model, "AP Clerk (default)", matcher_logic, per_scenario, avgs)

    if not Confirm.ask("Save and run?", default=True):
        console.print("[dim]Aborted.[/dim]")
        return

    config_path = _write_config(name, cfg)
    console.print(f"Saved config to [cyan]{config_path}[/cyan]")
    rc = _run_experiment(config_path)
    if rc != 0:
        console.print(
            "\n[yellow]Experiment exited with an error.[/yellow]\n"
            "If Odoo is not running, start it with: [cyan]docker compose up -d[/cyan]"
        )


def path_custom(avgs: dict) -> None:
    console.print(Rule("Custom experiment"))
    model = _ask_model()

    console.print("\nRole / system prompt:")
    console.print("  [1] AP Clerk (default — null)")
    console.print("  [2] CFO persona")
    console.print("  [3] Custom (paste)")
    role_choice = Prompt.ask("Role", choices=["1", "2", "3"], default="1")
    if role_choice == "1":
        system_prompt = None
        role_label = "AP Clerk (default)"
    elif role_choice == "2":
        system_prompt = CFO_SYSTEM_PROMPT
        role_label = "CFO persona"
    else:
        system_prompt = _ask_multiline_prompt("system prompt")
        role_label = "Custom" if system_prompt.strip() else "AP Clerk (default)"
        if not system_prompt.strip():
            system_prompt = None

    matcher_logic = _ask_matcher()

    console.print("\nScenario filter (leave blank for all six):")
    scenarios_raw = Prompt.ask(
        "Scenarios [dim](comma-separated, e.g. clean,duplicate — or blank for all)[/dim]",
        default="",
    ).strip()
    scenarios = [s.strip() for s in scenarios_raw.split(",") if s.strip()] or None

    name = _ask_name()
    description = Prompt.ask("One-line description")
    per_scenario = _ask_sample_size()

    cfg = _build_config(name, description, model, system_prompt, matcher_logic, per_scenario)
    if scenarios:
        cfg["sample"]["scenarios"] = scenarios

    _render_preview(name, description, model, role_label, matcher_logic, per_scenario, avgs)

    if not Confirm.ask("Save and run?", default=True):
        console.print("[dim]Aborted.[/dim]")
        return

    config_path = _write_config(name, cfg)
    console.print(f"Saved config to [cyan]{config_path}[/cyan]")
    rc = _run_experiment(config_path)
    if rc != 0:
        console.print(
            "\n[yellow]Experiment exited with an error.[/yellow]\n"
            "If Odoo is not running, start it with: [cyan]docker compose up -d[/cyan]"
        )


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        console.print(Rule("[bold]ERP Agent Experiment Wizard[/bold]"))
        console.print()

        avgs = _load_baseline_averages()

        console.print("What do you want to test?")
        console.print("  [1] Model   — swap the AI model (e.g., Haiku vs Sonnet)")
        console.print("  [2] Role    — change the agent's persona/system prompt")
        console.print("  [3] Policy  — change the matcher logic (AND vs OR)")
        console.print("  [4] Custom  — configure every setting from scratch")
        console.print()

        path = Prompt.ask("Pick one", choices=["1", "2", "3", "4"])

        console.print()
        if path == "1":
            path_model(avgs)
        elif path == "2":
            path_role(avgs)
        elif path == "3":
            path_policy(avgs)
        else:
            path_custom(avgs)

    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Cancelled.[/dim]")
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
