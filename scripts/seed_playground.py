"""
Seed the Odoo sandbox with realistic volume and scenario mix.

Creates a populated ERP environment that resembles a mid-market AP department
mid-month, not a handcrafted fixture. Writes a JSON manifest mapping every
created bill to the scenario type that produced it, so the agent can be
evaluated against ground truth.

Defaults:
  50 vendors, 30 products, 300 POs spread across the last 90 days, and a
  matching mix of vendor bills distributed as:
    70%  clean                    -> should APPROVE
    5%   price variance in tol.   -> should APPROVE
    10%  price variance beyond    -> should ROUTE
    5%   qty over-invoiced        -> should BLOCK
    5%   missing goods receipt    -> should BLOCK
    5%   duplicate invoice        -> should BLOCK

Usage:
    python scripts/seed_playground.py
    python scripts/seed_playground.py --invoices 100
    python scripts/seed_playground.py --seed 7     # different random seed

To reset the sandbox entirely, use docker:
    docker compose down -v && docker compose up -d

Requires Odoo to be running and a .env with credentials.
"""
from __future__ import annotations

import argparse
import json
import sys
import random
from dataclasses import dataclass, asdict, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# Make `src` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from src.odoo_client import OdooClient


# ---------------------------------------------------------------------------
# Scenario mix. Must sum to 1.0.
# ---------------------------------------------------------------------------
SCENARIO_MIX: dict[str, float] = {
    "clean":                0.70,
    "price_variance_ok":    0.05,
    "price_variance_bad":   0.10,
    "qty_over_invoiced":    0.05,
    "missing_gr":           0.05,
    "duplicate":            0.05,
}

EXPECTED_OUTCOME: dict[str, str] = {
    "clean":                "approve",
    "price_variance_ok":    "approve",
    "price_variance_bad":   "route",
    "qty_over_invoiced":    "block",
    "missing_gr":           "block",
    "duplicate":            "block",
}


# ---------------------------------------------------------------------------
# Data pools. Realistic-sounding but fictional. Script samples from these.
# ---------------------------------------------------------------------------
VENDOR_NAMES: list[str] = [
    "Acme Industrial Supply", "Blackrock Machining Co.", "Cascade Fastener Group",
    "Delta Valve & Fitting", "Evergreen Packaging Partners", "Fortress Steel Works",
    "Granite Logistics Holdings", "Harborline Electric", "Ironside Bearing Co.",
    "Juniper Chemical Distributors", "Keystone Pneumatics", "Lakeshore Cutting Tools",
    "Meridian Hydraulics", "Northwind Industrial Parts", "Olympia Precision Works",
    "Pacific Rim Abrasives", "Quantum Motor Supply", "Redline Conveyors Inc.",
    "Summit Gasket & Seal", "Tidewater Pump & Motor", "Unity Weld Products",
    "Vanguard Bearings LLC", "Westport Lubricants", "Xenon Industrial Lighting",
    "Yellowstone Valve Group", "Zenith Chain & Sprocket", "Allied Coatings Supply",
    "Boreal Steel Fabricators", "Cedar Creek MRO", "Diamond Cutting Solutions",
    "Eastern Seaboard Hardware", "Flagstaff Bolt & Fastener", "Goldleaf Electrical",
    "Highland Pneumatic Tools", "Independence Hydraulic", "Jefferson Ball Bearing",
    "Kilroy Industrial Rubber", "Liberty Motor Controls", "Monarch Filtration",
    "Nordic Welding Supply", "Osprey Machine Parts", "Pioneer Pump & Compressor",
    "Redwood Power Transmission", "Silverline Tool & Die", "Trident Bearing Works",
    "Uniform Gasket Manufacturing", "Valiant Fastener Corp", "Wolfpack Industrial",
    "Xpress Packaging Co.", "Yorktown Steel Supply", "Zephyr Air Systems",
    "Apex Sealing Technologies", "Brightwater Pipe Fitting", "Copperfield Wire & Cable",
    "Dustline Filtration Systems", "Emerald Valley Chemical", "Fairfax Electrical Parts",
    "Goldstone Hardware Supply", "Huntington Industrial Glass", "Ivanhoe Precision Tools",
]

# (name, sku_root, base_price)
PRODUCT_CATALOG: list[tuple[str, str, float]] = [
    ("Ball Bearing 6205 2RS",         "BRG-6205",   24.50),
    ("Ball Bearing 6310 Open",        "BRG-6310",   62.00),
    ("Taper Roller Bearing 30205",    "BRG-30205",  88.75),
    ("Hex Bolt M10x50 Gr8",           "FST-HX1050",  0.85),
    ("Hex Bolt M16x90 Gr8",           "FST-HX1690",  2.40),
    ("Socket Cap Screw M8x30",        "FST-SC0830",  0.55),
    ("Threaded Rod 3/8-16x3ft",       "FST-TR3816",  4.10),
    ("V-Belt A-68",                   "BEL-A68",    11.25),
    ("Timing Belt XL-200",            "BEL-XL200",  18.60),
    ("Industrial Chain #60 10ft",     "CHN-60-10",  72.00),
    ("Cutting Oil 55gal Drum",        "LUB-CO55",  410.00),
    ("Hydraulic Fluid ISO 46 5gal",   "LUB-HY46",   68.50),
    ("Synthetic Grease 14oz Tube",    "LUB-GR14",    9.75),
    ("PLC Module Siemens S7-1200",    "CTL-S71200", 1250.00),
    ("Motor Contactor 40A 120V",      "CTL-CT40",   84.00),
    ("Pressure Gauge 0-300psi 2.5in", "GAU-PR300",  32.50),
    ("Temperature Sensor K-type 6in", "SEN-TK6",    27.80),
    ("Flow Meter Inline 1in NPT",     "SEN-FL1NPT", 215.00),
    ("Solenoid Valve 24VDC 1/4in",    "VLV-SOL14",  46.00),
    ("Ball Valve 1in Brass",          "VLV-BB1",    18.25),
    ("Gate Valve 2in Cast Iron",      "VLV-GT2",    74.00),
    ("O-Ring Kit 382pc Viton",        "SEL-OR382",  38.50),
    ("Gasket Sheet 1/16in 36x36",     "SEL-GS16",   42.00),
    ("Stainless Tubing 1/2in 20ft",   "TUB-SS12",   58.75),
    ("Copper Pipe 3/4in Type L 10ft", "TUB-CU34",   44.00),
    ("Safety Glasses ANSI Z87",       "PPE-SG87",    6.50),
    ("Leather Work Gloves XL",        "PPE-GL-XL",  12.40),
    ("Ear Protection Muffs 27dB",     "PPE-EM27",   18.90),
    ("Welding Rod E7018 5lb",         "WLD-E7018",  32.00),
    ("Cutting Disc 4.5in 10pk",       "WLD-CD45",   14.75),
]


# ---------------------------------------------------------------------------
# Records written to the manifest.
# ---------------------------------------------------------------------------
@dataclass
class ScenarioRecord:
    scenario_type: str
    expected_outcome: str           # approve | route | block
    vendor_id: int
    vendor_name: str
    po_id: int
    po_name: str
    bill_id: int
    bill_name: str
    bill_total: float
    order_date: str
    bill_date: str
    notes: str = ""
    related_bill_id: Optional[int] = None  # used for duplicate scenarios


# ---------------------------------------------------------------------------
# Entity builders.
# ---------------------------------------------------------------------------
def build_vendors(client: OdooClient, rng: random.Random, n: int) -> list[dict]:
    """Create n vendors tagged with comment='PLAYGROUND' for later identification."""
    if n > len(VENDOR_NAMES):
        raise ValueError(f"Requested {n} vendors but only {len(VENDOR_NAMES)} names in pool")
    chosen = rng.sample(VENDOR_NAMES, n)
    out = []
    for name in chosen:
        vid = client._call("res.partner", "create", {
            "name": name,
            "supplier_rank": 1,
            "comment": "PLAYGROUND",
        })
        out.append({"id": vid, "name": name})
    return out


def build_products(client: OdooClient, rng: random.Random, n: int) -> list[dict]:
    """Create n products with SKUs prefixed 'PG-' for playground identification."""
    catalog = rng.sample(PRODUCT_CATALOG, min(n, len(PRODUCT_CATALOG)))
    out = []
    for name, sku_root, price in catalog:
        pid = client._call("product.product", "create", {
            "name": name,
            "default_code": f"PG-{sku_root}",
            "list_price": price,
            "standard_price": round(price * 0.7, 2),
            "type": "product",
            "purchase_ok": True,
            "sale_ok": False,
        })
        out.append({"id": pid, "name": name, "sku": sku_root, "price": price})
    return out


# ---------------------------------------------------------------------------
# Scenario primitives.
# ---------------------------------------------------------------------------
def _pick_scenario(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for scenario, weight in SCENARIO_MIX.items():
        cum += weight
        if r < cum:
            return scenario
    return "clean"


def _generate_po_lines(rng: random.Random, products: list[dict]) -> list[dict]:
    n_lines = rng.randint(1, 5)
    chosen = rng.sample(products, min(n_lines, len(products)))
    return [
        {
            "product_id": p["id"],
            "product_qty": rng.randint(1, 50),
            "price_unit": p["price"],
        }
        for p in chosen
    ]


def _create_po(client: OdooClient, vendor: dict, lines: list[dict], order_date: date) -> tuple[int, str]:
    po_id = client._call("purchase.order", "create", {
        "partner_id": vendor["id"],
        "date_order": order_date.isoformat(),
        "order_line": [(0, 0, ln) for ln in lines],
    })
    client._call("purchase.order", "button_confirm", [po_id])
    po_name = client._call("purchase.order", "read", [po_id], fields=["name"])[0]["name"]
    return po_id, po_name


def _receive_full(client: OdooClient, po_id: int) -> None:
    po = client._call("purchase.order", "read", [po_id], fields=["picking_ids"])[0]
    for picking_id in po["picking_ids"]:
        moves = client._call(
            "stock.move", "search_read",
            [["picking_id", "=", picking_id]],
            fields=["id", "product_uom_qty"],
        )
        for mv in moves:
            client._call("stock.move", "write", [mv["id"]], {"quantity": mv["product_uom_qty"]})
        client._call("stock.picking", "button_validate", [picking_id])


def _create_bill(
    client: OdooClient, vendor: dict, po_name: str,
    bill_lines: list[dict], bill_date: date, post: bool = True,
) -> tuple[int, str, float]:
    inv_id = client._call("account.move", "create", {
        "move_type": "in_invoice",
        "partner_id": vendor["id"],
        "invoice_date": bill_date.isoformat(),
        "invoice_origin": po_name,
        "invoice_line_ids": [(0, 0, ln) for ln in bill_lines],
    })
    if post:
        client._call("account.move", "action_post", [inv_id])
    bill = client._call("account.move", "read", [inv_id], fields=["name", "amount_total"])[0]
    return inv_id, bill["name"], bill["amount_total"]


# ---------------------------------------------------------------------------
# Scenario execution. Returns the ScenarioRecord for the manifest.
# ---------------------------------------------------------------------------
def execute_scenario(
    client: OdooClient, scenario_type: str, vendor: dict,
    products: list[dict], rng: random.Random,
) -> ScenarioRecord:
    order_date = date.today() - timedelta(days=rng.randint(0, 90))
    bill_date = order_date + timedelta(days=rng.randint(3, 14))
    po_lines = _generate_po_lines(rng, products)

    po_id, po_name = _create_po(client, vendor, po_lines, order_date)
    related_bill_id: Optional[int] = None
    notes = ""

    # Default bill lines mirror PO exactly.
    bill_lines = [
        {"product_id": ln["product_id"], "quantity": ln["product_qty"], "price_unit": ln["price_unit"]}
        for ln in po_lines
    ]

    if scenario_type == "clean":
        _receive_full(client, po_id)
        notes = "PO, receipt, and invoice all match"

    elif scenario_type == "price_variance_ok":
        _receive_full(client, po_id)
        bump = rng.uniform(1.01, 1.03)
        bill_lines = [
            {"product_id": ln["product_id"], "quantity": ln["product_qty"],
             "price_unit": round(ln["price_unit"] * bump, 2)}
            for ln in po_lines
        ]
        notes = f"Price +{(bump-1)*100:.1f}% (within tolerance)"

    elif scenario_type == "price_variance_bad":
        _receive_full(client, po_id)
        bump = rng.uniform(1.10, 1.25)
        bill_lines = [
            {"product_id": ln["product_id"], "quantity": ln["product_qty"],
             "price_unit": round(ln["price_unit"] * bump, 2)}
            for ln in po_lines
        ]
        notes = f"Price +{(bump-1)*100:.1f}% (beyond tolerance)"

    elif scenario_type == "qty_over_invoiced":
        _receive_full(client, po_id)
        bill_lines = [
            {"product_id": ln["product_id"],
             "quantity": ln["product_qty"] + rng.randint(1, 5),
             "price_unit": ln["price_unit"]}
            for ln in po_lines
        ]
        notes = "Billed quantity exceeds received quantity"

    elif scenario_type == "missing_gr":
        # Deliberately skip receipt
        notes = "No goods receipt recorded"

    elif scenario_type == "duplicate":
        _receive_full(client, po_id)
        # Create the first (legitimate) bill. Manifest tracks the second as the duplicate.
        first_id, _, _ = _create_bill(client, vendor, po_name, bill_lines, bill_date)
        related_bill_id = first_id
        notes = f"Duplicate of bill_id={first_id}"

    else:
        raise ValueError(f"Unknown scenario type: {scenario_type}")

    bill_id, bill_name, bill_total = _create_bill(client, vendor, po_name, bill_lines, bill_date)

    return ScenarioRecord(
        scenario_type=scenario_type,
        expected_outcome=EXPECTED_OUTCOME[scenario_type],
        vendor_id=vendor["id"],
        vendor_name=vendor["name"],
        po_id=po_id,
        po_name=po_name,
        bill_id=bill_id,
        bill_name=bill_name,
        bill_total=bill_total,
        order_date=order_date.isoformat(),
        bill_date=bill_date.isoformat(),
        notes=notes,
        related_bill_id=related_bill_id,
    )


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Odoo sandbox with realistic scenario volume.")
    parser.add_argument("--vendors",  type=int, default=50,  help="Number of vendors to create")
    parser.add_argument("--products", type=int, default=30,  help="Number of products to create")
    parser.add_argument("--invoices", type=int, default=300, help="Number of invoice scenarios to create")
    parser.add_argument("--seed",     type=int, default=42,  help="Random seed for reproducibility")
    parser.add_argument("--manifest", type=str, default="playground_manifest.json",
                        help="Output path for the scenario manifest")
    args = parser.parse_args()

    console = Console()
    load_dotenv()
    rng = random.Random(args.seed)
    client = OdooClient()

    console.print(f"[bold green]Connected to Odoo as uid={client.uid}[/bold green]\n")

    # Sanity check for prior playground data.
    existing = client._call("res.partner", "search_count", [["comment", "=", "PLAYGROUND"]])
    if existing:
        console.print(
            f"[yellow]Note: {existing} existing PLAYGROUND vendors detected. "
            f"This run will stack on top. To start fresh, run: "
            f"docker compose down -v && docker compose up -d[/yellow]\n"
        )

    # Phase 1: entities.
    console.print(f"[bold]Creating {args.vendors} vendors and {args.products} products...[/bold]")
    vendors = build_vendors(client, rng, args.vendors)
    products = build_products(client, rng, args.products)
    console.print(f"  {len(vendors)} vendors, {len(products)} products ready.\n")

    # Phase 2: scenarios.
    console.print(f"[bold]Generating {args.invoices} invoice scenarios...[/bold]")
    scenarios: list[ScenarioRecord] = []
    counts: dict[str, int] = {k: 0 for k in SCENARIO_MIX}

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("{task.completed}/{task.total}"),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Seeding", total=args.invoices)
        for _ in range(args.invoices):
            stype = _pick_scenario(rng)
            counts[stype] += 1
            vendor = rng.choice(vendors)
            try:
                record = execute_scenario(client, stype, vendor, products, rng)
                scenarios.append(record)
            except Exception as e:
                console.print(f"\n[red]Error on scenario '{stype}': {e}[/red]")
                raise
            progress.update(task, advance=1)

    # Phase 3: manifest.
    manifest_path = Path(args.manifest)
    manifest_path.write_text(
        json.dumps([asdict(s) for s in scenarios], indent=2, default=str)
    )

    # Summary table.
    console.print(f"\n[bold green]Done.[/bold green] Manifest: [cyan]{manifest_path}[/cyan]\n")
    table = Table(title="Scenario distribution", show_header=True, header_style="bold")
    table.add_column("Scenario")
    table.add_column("Expected", style="dim")
    table.add_column("Count", justify="right")
    table.add_column("Share", justify="right")
    for stype, count in counts.items():
        pct = 100.0 * count / max(args.invoices, 1)
        table.add_row(stype, EXPECTED_OUTCOME[stype], str(count), f"{pct:.1f}%")
    console.print(table)

    console.print(
        f"\nRun the agent against any bill from the manifest:\n"
        f"  [cyan]python -m scripts.run_agent <BILL_NAME>[/cyan]\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
