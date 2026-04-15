"""
Seed Odoo with a set of test scenarios for the agent to run against.

Creates:
  * One clean PO → receipt → invoice triple (should APPROVE)
  * One price-variance scenario (should ROUTE_FOR_REVIEW)
  * One over-invoiced-quantity scenario (should BLOCK)
  * One missing-goods-receipt scenario (should BLOCK)
  * One duplicate-invoice scenario (should BLOCK)

Usage:
    python scripts/seed_odoo.py

Requires Odoo to be running (docker compose up) and a .env with credentials.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Make `src` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.odoo_client import OdooClient


def _ensure_vendor(client: OdooClient, name: str) -> int:
    ids = client._call("res.partner", "search", [["name", "=", name], ["supplier_rank", ">", 0]], limit=1)
    if ids:
        return ids[0]
    return client._call("res.partner", "create", {"name": name, "supplier_rank": 1})


def _ensure_product(client: OdooClient, name: str, default_code: str, list_price: float) -> int:
    ids = client._call("product.product", "search", [["default_code", "=", default_code]], limit=1)
    if ids:
        return ids[0]
    return client._call("product.product", "create", {
        "name": name, "default_code": default_code,
        "list_price": list_price, "standard_price": list_price,
        "type": "product", "purchase_ok": True, "sale_ok": False,
    })


def _create_po(client: OdooClient, vendor_id: int, lines: list[dict]) -> int:
    po_id = client._call("purchase.order", "create", {
        "partner_id": vendor_id,
        "order_line": [(0, 0, ln) for ln in lines],
    })
    client._call("purchase.order", "button_confirm", [po_id])
    return po_id


def _receive(client: OdooClient, po_id: int, qty_overrides: dict[int, float] | None = None) -> None:
    """Validate the incoming picking for a PO. qty_overrides lets us receive less than ordered."""
    po = client._call("purchase.order", "read", [po_id], fields=["picking_ids"])[0]
    for picking_id in po["picking_ids"]:
        if qty_overrides:
            moves = client._call("stock.move", "search_read",
                                 [["picking_id", "=", picking_id]],
                                 fields=["id", "product_id", "product_uom_qty"])
            for mv in moves:
                if mv["product_id"][0] in qty_overrides:
                    client._call("stock.move", "write",
                                 [mv["id"]], {"quantity": qty_overrides[mv["product_id"][0]]})
                else:
                    client._call("stock.move", "write",
                                 [mv["id"]], {"quantity": mv["product_uom_qty"]})
        else:
            moves = client._call("stock.move", "search_read",
                                 [["picking_id", "=", picking_id]],
                                 fields=["id", "product_uom_qty"])
            for mv in moves:
                client._call("stock.move", "write",
                             [mv["id"]], {"quantity": mv["product_uom_qty"]})
        client._call("stock.picking", "button_validate", [picking_id])


def _create_vendor_bill(
    client: OdooClient, vendor_id: int, po_name: str,
    lines: list[dict], post: bool = True,
) -> int:
    inv_id = client._call("account.move", "create", {
        "move_type": "in_invoice",
        "partner_id": vendor_id,
        "invoice_date": date.today().isoformat(),
        "invoice_origin": po_name,
        "invoice_line_ids": [(0, 0, ln) for ln in lines],
    })
    if post:
        client._call("account.move", "action_post", [inv_id])
    return inv_id


def main() -> int:
    load_dotenv()
    c = OdooClient()
    print(f"Connected to Odoo as uid={c.uid}")

    vendor = _ensure_vendor(c, "Acme Industrial Supply")
    p_a = _ensure_product(c, "Widget A", "WIDGET-A", 100.00)
    p_b = _ensure_product(c, "Widget B", "WIDGET-B", 100.00)

    # --- Scenario 1: clean ---
    po1 = _create_po(c, vendor, [
        {"product_id": p_a, "product_qty": 10, "price_unit": 100.00},
        {"product_id": p_b, "product_qty": 5,  "price_unit": 100.00},
    ])
    po1_name = c._call("purchase.order", "read", [po1], fields=["name"])[0]["name"]
    _receive(c, po1)
    _create_vendor_bill(c, vendor, po1_name, [
        {"product_id": p_a, "quantity": 10, "price_unit": 100.00},
        {"product_id": p_b, "quantity": 5,  "price_unit": 100.00},
    ])
    print(f"  scenario 1 (clean) -> PO {po1_name}")

    # --- Scenario 2: price variance ---
    po2 = _create_po(c, vendor, [{"product_id": p_a, "product_qty": 10, "price_unit": 100.00}])
    po2_name = c._call("purchase.order", "read", [po2], fields=["name"])[0]["name"]
    _receive(c, po2)
    _create_vendor_bill(c, vendor, po2_name, [
        {"product_id": p_a, "quantity": 10, "price_unit": 115.00},  # 15% over
    ])
    print(f"  scenario 2 (price variance) -> PO {po2_name}")

    # --- Scenario 3: over-invoiced qty ---
    po3 = _create_po(c, vendor, [{"product_id": p_a, "product_qty": 10, "price_unit": 100.00}])
    po3_name = c._call("purchase.order", "read", [po3], fields=["name"])[0]["name"]
    _receive(c, po3)
    _create_vendor_bill(c, vendor, po3_name, [
        {"product_id": p_a, "quantity": 12, "price_unit": 100.00},  # billed 12, received 10
    ])
    print(f"  scenario 3 (over-invoiced) -> PO {po3_name}")

    # --- Scenario 4: missing goods receipt ---
    po4 = _create_po(c, vendor, [{"product_id": p_a, "product_qty": 10, "price_unit": 100.00}])
    po4_name = c._call("purchase.order", "read", [po4], fields=["name"])[0]["name"]
    # deliberately do NOT receive
    _create_vendor_bill(c, vendor, po4_name, [
        {"product_id": p_a, "quantity": 10, "price_unit": 100.00},
    ])
    print(f"  scenario 4 (missing GR) -> PO {po4_name}")

    # --- Scenario 5: duplicate invoice ---
    po5 = _create_po(c, vendor, [{"product_id": p_a, "product_qty": 10, "price_unit": 100.00}])
    po5_name = c._call("purchase.order", "read", [po5], fields=["name"])[0]["name"]
    _receive(c, po5)
    _create_vendor_bill(c, vendor, po5_name, [
        {"product_id": p_a, "quantity": 10, "price_unit": 100.00},
    ])
    # deliberately post a second identical bill
    _create_vendor_bill(c, vendor, po5_name, [
        {"product_id": p_a, "quantity": 10, "price_unit": 100.00},
    ])
    print(f"  scenario 5 (duplicate invoice) -> PO {po5_name}")

    print("\nDone. Run: python -m scripts.run_agent <INVOICE_NUMBER>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
