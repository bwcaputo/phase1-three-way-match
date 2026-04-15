"""List all vendor bills in Odoo so we know what to run the agent against."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.odoo_client import OdooClient


def main() -> int:
    load_dotenv()
    c = OdooClient()
    bills = c._call(
        "account.move", "search_read",
        [["move_type", "=", "in_invoice"]],
        fields=["name", "partner_id", "invoice_origin", "amount_total", "state"],
    )
    if not bills:
        print("No vendor bills found.")
        return 1
    print(f"\nFound {len(bills)} vendor bill(s):\n")
    for b in bills:
        vendor = b["partner_id"][1] if b.get("partner_id") else "(none)"
        origin = b.get("invoice_origin") or "(none)"
        print(f"  {b['name']:<30} vendor={vendor:<25} PO={origin:<10} "
              f"total=${b['amount_total']:>8.2f} state={b['state']}")
    print("\nRun: python -m scripts.run_agent <NAME>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
