"""
CLI entry point.

    python -m scripts.run_agent <INVOICE_NUMBER>
    python -m scripts.run_agent BILL/2026/0007 --verbose
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `src` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.agent import run_agent


def _render(result, console: Console) -> None:
    mr = result.match_result
    console.print(Panel.fit(result.summary or "(no narration)", title="Agent summary", border_style="cyan"))

    if not mr:
        console.print("[red]No match result returned.[/red]")
        return

    badge = {
        "approve": "[green]APPROVE[/green]",
        "route_for_review": "[yellow]ROUTE FOR REVIEW[/yellow]",
        "block": "[red]BLOCK[/red]",
    }[mr.recommended_action]
    console.print(f"\nRecommended action: {badge}\n{mr.rationale}\n")

    if mr.discrepancies:
        tbl = Table(title="Discrepancies", show_lines=True)
        tbl.add_column("Code")
        tbl.add_column("Severity")
        tbl.add_column("SKU")
        tbl.add_column("Detail")
        for d in mr.discrepancies:
            tbl.add_row(d.code, d.severity, d.product_code or "-", d.description)
        console.print(tbl)
    else:
        console.print("[green]No discrepancies.[/green]")

    console.print(Panel("\n".join(mr.audit_trail), title="Audit trail", border_style="grey50"))
    console.print(f"\n[dim]Tool calls: {result.tool_calls}[/dim]")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run the three-way match agent on a vendor invoice.")
    parser.add_argument("invoice_number", help="Odoo invoice number, e.g. BILL/2026/0007")
    parser.add_argument("--verbose", action="store_true", help="Print each tool call")
    args = parser.parse_args()

    console = Console()
    console.print(f"[cyan]Running three-way match on {args.invoice_number}...[/cyan]\n")
    try:
        result = run_agent(args.invoice_number, verbose=args.verbose)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Agent failed:[/red] {exc}")
        return 1
    _render(result, console)
    return 0 if result.match_result else 1


if __name__ == "__main__":
    sys.exit(main())
