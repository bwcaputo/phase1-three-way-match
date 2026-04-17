"""
Seed the Odoo sandbox with realistic volume and scenario mix.

Creates a populated ERP environment that resembles a mid-market AP department
mid-month, not a handcrafted fixture. Writes a JSON manifest mapping every
created bill to the scenario type that produced it, so the agent can be
evaluated against ground truth.

Defaults (no profile):
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
    python scripts/seed_playground.py --profile profiles/profile_manufacturer.yaml
    python scripts/seed_playground.py --profile profiles/profile_distributor.yaml --dry-run

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
    "clean":                0.60,   # reduced from 0.70 to make room for two new types
    "price_variance_ok":    0.05,
    "price_variance_bad":   0.10,
    "qty_over_invoiced":    0.05,
    "missing_gr":           0.05,
    "duplicate":            0.05,
    # New scenario types added 2026-04-16.
    # partial_shipment: GR receives a subset of PO qty; invoice matches GR qty.
    #   The matcher compares invoice vs received (not ordered), so this approves
    #   correctly. Tests whether the agent handles the common "goods received in
    #   two lots" pattern without false-flagging a quantity mismatch.
    "partial_shipment":     0.05,
    # blanket_po: Large standing PO ($50K); each invoice draws down a fraction.
    #   Simplified for current architecture: PO line qty is large, GR receives
    #   a fraction, invoice bills for that fraction — clean three-way match.
    #   TODO Phase 2: track cumulative invoiced-vs-PO-total to detect over-draw.
    "blanket_po":           0.05,
}

EXPECTED_OUTCOME: dict[str, str] = {
    "clean":                "approve",
    "price_variance_ok":    "approve",
    "price_variance_bad":   "route",
    "qty_over_invoiced":    "block",
    "missing_gr":           "block",
    "duplicate":            "block",
    "partial_shipment":     "approve",
    "blanket_po":           "approve",
}

# All valid scenario keys — used for profile validation.
ALL_SCENARIOS = set(SCENARIO_MIX.keys())


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
# Business profile dataclass and loader.
# ---------------------------------------------------------------------------
@dataclass
class PlaygroundProfile:
    name: str
    description: str
    vendors: int
    products: int
    invoices: int
    seed: int
    date_range_days: int
    scenario_mix: dict[str, float]
    vendor_names: list[str]
    # Stored as (name, sku_prefix, base_price) tuples — same format as PRODUCT_CATALOG.
    product_catalog: list[tuple[str, str, float]]


def load_profile(path: str) -> PlaygroundProfile:
    """
    Load and validate a business profile YAML.

    Raises ValueError with a descriptive message if validation fails.
    """
    import yaml  # deferred — only needed when --profile is used

    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    # --- required top-level keys ---
    required = ["name", "description", "vendors", "products", "invoices",
                "seed", "date_range_days", "scenario_mix", "vendor_names",
                "product_catalog"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Profile is missing required fields: {missing}")

    name: str = data["name"]
    description: str = data["description"]
    vendors: int = int(data["vendors"])
    products: int = int(data["products"])
    invoices: int = int(data["invoices"])
    seed: int = int(data["seed"])
    date_range_days: int = int(data["date_range_days"])

    # --- scenario_mix validation ---
    mix_raw: dict = data["scenario_mix"]
    unknown = set(mix_raw.keys()) - ALL_SCENARIOS
    if unknown:
        raise ValueError(f"Unknown scenario keys in scenario_mix: {unknown}")
    # Missing keys default to 0.0 so existing profiles don't need updating when
    # new scenario types are added.
    scenario_mix = {k: 0.0 for k in ALL_SCENARIOS}
    scenario_mix.update({k: float(v) for k, v in mix_raw.items()})
    total = sum(scenario_mix.values())
    if abs(total - 1.0) > 0.001:
        raise ValueError(
            f"scenario_mix values must sum to 1.0 (got {total:.6f})"
        )

    # --- vendor_names validation ---
    vendor_names: list[str] = [str(v) for v in data["vendor_names"]]
    if vendors > len(vendor_names):
        raise ValueError(
            f"Profile requests {vendors} vendors but vendor_names pool only has "
            f"{len(vendor_names)} entries"
        )

    # --- product_catalog validation and conversion ---
    # YAML format: {name, sku, base_price}  ->  tuple (name, sku_prefix, base_price)
    raw_catalog: list[dict] = data["product_catalog"]
    product_catalog: list[tuple[str, str, float]] = []
    for i, entry in enumerate(raw_catalog):
        for field_name in ("name", "sku", "base_price"):
            if field_name not in entry:
                raise ValueError(
                    f"product_catalog[{i}] is missing field '{field_name}'"
                )
        price = float(entry["base_price"])
        if price <= 0:
            raise ValueError(
                f"product_catalog[{i}] '{entry['name']}': base_price must be > 0 (got {price})"
            )
        product_catalog.append((str(entry["name"]), str(entry["sku"]), price))

    if products > len(product_catalog):
        raise ValueError(
            f"Profile requests {products} products but product_catalog only has "
            f"{len(product_catalog)} entries"
        )

    return PlaygroundProfile(
        name=name,
        description=description,
        vendors=vendors,
        products=products,
        invoices=invoices,
        seed=seed,
        date_range_days=date_range_days,
        scenario_mix=scenario_mix,
        vendor_names=vendor_names,
        product_catalog=product_catalog,
    )


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
def build_vendors(
    client: OdooClient,
    rng: random.Random,
    n: int,
    vendor_pool: list[str],
) -> list[dict]:
    """Create n vendors tagged with comment='PLAYGROUND' for later identification."""
    if n > len(vendor_pool):
        raise ValueError(f"Requested {n} vendors but only {len(vendor_pool)} names in pool")
    chosen = rng.sample(vendor_pool, n)
    out = []
    for name in chosen:
        vid = client._call("res.partner", "create", {
            "name": name,
            "supplier_rank": 1,
            "comment": "PLAYGROUND",
        })
        out.append({"id": vid, "name": name})
    return out


def build_products(
    client: OdooClient,
    rng: random.Random,
    n: int,
    product_pool: list[tuple[str, str, float]],
) -> list[dict]:
    """Create n products with SKUs prefixed 'PG-' for playground identification."""
    catalog = rng.sample(product_pool, min(n, len(product_pool)))
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
def _pick_scenario(rng: random.Random, scenario_mix: dict[str, float]) -> str:
    r = rng.random()
    cum = 0.0
    for scenario, weight in scenario_mix.items():
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
    date_range_days: int = 90,
) -> ScenarioRecord:
    order_date = date.today() - timedelta(days=rng.randint(0, date_range_days))
    bill_date = order_date + timedelta(days=rng.randint(3, 14))
    po_lines = _generate_po_lines(rng, products)

    # blanket_po uses large standing quantities; override po_lines before PO is created.
    if scenario_type == "blanket_po":
        po_lines = [
            {
                "product_id": ln["product_id"],
                "product_qty": rng.randint(100, 200),
                "price_unit": ln["price_unit"],
            }
            for ln in po_lines
        ]

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

    elif scenario_type == "partial_shipment":
        # GR receives 50–80% of each PO line; invoice bills for exactly the received qty.
        # The matcher compares invoice qty vs GR qty (not PO qty), so this is a clean match
        # and should approve. This tests the "goods received in two lots" pattern.
        partial_fraction = rng.uniform(0.50, 0.80)
        partial_lines = []
        for ln in po_lines:
            received_qty = max(1, round(ln["product_qty"] * partial_fraction))
            partial_lines.append({
                "product_id": ln["product_id"],
                "product_qty": ln["product_qty"],
                "_partial_received": received_qty,
            })
        # Receive only the partial quantity via stock moves.
        po = client._call("purchase.order", "read", [po_id], fields=["picking_ids"])[0]
        for picking_id in po["picking_ids"]:
            moves = client._call(
                "stock.move", "search_read",
                [["picking_id", "=", picking_id]],
                fields=["id", "product_id", "product_uom_qty"],
            )
            for mv, ln in zip(moves, partial_lines):
                client._call("stock.move", "write", [mv["id"]], {"quantity": ln["_partial_received"]})
            client._call("stock.picking", "button_validate", [picking_id])
        # Bill lines: invoice for received qty at PO price.
        bill_lines = [
            {"product_id": ln["product_id"],
             "quantity": ln["_partial_received"],
             "price_unit": next(
                 orig["price_unit"] for orig in po_lines if orig["product_id"] == ln["product_id"]
             )}
            for ln in partial_lines
        ]
        pct = int(partial_fraction * 100)
        notes = f"Partial shipment: {pct}% of PO qty received and invoiced"

    elif scenario_type == "blanket_po":
        # Blanket PO: large standing order (100–200 units/line); one partial invoice.
        # GR and invoice each cover 10–30% of ordered qty. All three documents agree,
        # so the matcher approves. po_lines was already set to large quantities above.
        # TODO Phase 2: track cumulative invoiced-vs-PO-total to detect over-draw.
        draw_fraction = rng.uniform(0.10, 0.30)
        po_data = client._call("purchase.order", "read", [po_id], fields=["picking_ids"])[0]
        draw_qty_map: dict[int, int] = {}
        for picking_id in po_data["picking_ids"]:
            moves = client._call(
                "stock.move", "search_read",
                [["picking_id", "=", picking_id]],
                fields=["id", "product_id", "product_uom_qty"],
            )
            for mv in moves:
                draw_qty = max(1, round(mv["product_uom_qty"] * draw_fraction))
                draw_qty_map[mv["product_id"][0]] = draw_qty
                client._call("stock.move", "write", [mv["id"]], {"quantity": draw_qty})
            client._call("stock.picking", "button_validate", [picking_id])
        bill_lines = [
            {"product_id": ln["product_id"],
             "quantity": draw_qty_map.get(ln["product_id"], max(1, round(ln["product_qty"] * draw_fraction))),
             "price_unit": ln["price_unit"]}
            for ln in po_lines
        ]
        pct = int(draw_fraction * 100)
        notes = f"Blanket PO: {pct}% drawdown invoiced against large standing order"

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
    parser.add_argument("--vendors",  type=int, default=None,
                        help="Number of vendors to create (default: 50, or from profile)")
    parser.add_argument("--products", type=int, default=None,
                        help="Number of products to create (default: 30, or from profile)")
    parser.add_argument("--invoices", type=int, default=None,
                        help="Number of invoice scenarios to create (default: 300, or from profile)")
    parser.add_argument("--seed",     type=int, default=None,
                        help="Random seed for reproducibility (default: 42, or from profile)")
    parser.add_argument("--manifest", type=str, default="playground_manifest.json",
                        help="Output path for the scenario manifest")
    parser.add_argument("--profile",  type=str, default=None,
                        help="Path to a business profile YAML. See profiles/ for examples.")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Load and validate the profile, print config summary, "
                             "but do not connect to Odoo or create any records.")
    args = parser.parse_args()

    console = Console()

    # --- Load profile (if provided) and resolve final config values ---
    profile: Optional[PlaygroundProfile] = None
    if args.profile:
        try:
            profile = load_profile(args.profile)
        except Exception as e:
            console.print(f"[bold red]Profile error:[/bold red] {e}")
            return 1
        console.print(f"[bold cyan]Profile:[/bold cyan] {profile.name}")
        console.print(f"  {profile.description}\n")

    # Resolve final values: CLI flag > profile > hardcoded default
    active_vendors      = args.vendors  if args.vendors  is not None else (profile.vendors        if profile else 50)
    active_products     = args.products if args.products is not None else (profile.products       if profile else 30)
    active_invoices     = args.invoices if args.invoices is not None else (profile.invoices       if profile else 300)
    active_seed         = args.seed     if args.seed     is not None else (profile.seed           if profile else 42)
    active_date_range   = profile.date_range_days if profile else 90
    active_scenario_mix = profile.scenario_mix    if profile else SCENARIO_MIX
    active_vendor_pool  = profile.vendor_names    if profile else VENDOR_NAMES
    active_product_pool = profile.product_catalog if profile else PRODUCT_CATALOG

    # --- Dry-run: print summary and exit without touching Odoo ---
    if args.dry_run:
        table = Table(title="Profile config summary (dry run)", show_header=True, header_style="bold")
        table.add_column("Setting")
        table.add_column("Value", justify="right")
        table.add_row("Vendors",      str(active_vendors))
        table.add_row("Products",     str(active_products))
        table.add_row("Invoices",     str(active_invoices))
        table.add_row("Seed",         str(active_seed))
        table.add_row("Date range",   f"{active_date_range} days")
        table.add_row("Vendor pool",  str(len(active_vendor_pool)))
        table.add_row("Product pool", str(len(active_product_pool)))
        console.print(table)

        mix_table = Table(title="Scenario mix", show_header=True, header_style="bold")
        mix_table.add_column("Scenario")
        mix_table.add_column("Weight", justify="right")
        mix_table.add_column("Expected", style="dim")
        mix_table.add_column("~Invoices", justify="right")
        for stype, weight in active_scenario_mix.items():
            mix_table.add_row(
                stype,
                f"{weight:.2%}",
                EXPECTED_OUTCOME[stype],
                str(round(active_invoices * weight)),
            )
        console.print(mix_table)
        console.print("[green]Dry run complete. No Odoo records created.[/green]")
        return 0

    # --- Live run ---
    load_dotenv()
    rng = random.Random(active_seed)
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
    console.print(f"[bold]Creating {active_vendors} vendors and {active_products} products...[/bold]")
    vendors = build_vendors(client, rng, active_vendors, active_vendor_pool)
    products = build_products(client, rng, active_products, active_product_pool)
    console.print(f"  {len(vendors)} vendors, {len(products)} products ready.\n")

    # Phase 2: scenarios.
    console.print(f"[bold]Generating {active_invoices} invoice scenarios...[/bold]")
    scenarios: list[ScenarioRecord] = []
    counts: dict[str, int] = {k: 0 for k in active_scenario_mix}

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
        task = progress.add_task("Seeding", total=active_invoices)
        for _ in range(active_invoices):
            stype = _pick_scenario(rng, active_scenario_mix)
            counts[stype] += 1
            vendor = rng.choice(vendors)
            try:
                record = execute_scenario(
                    client, stype, vendor, products, rng,
                    date_range_days=active_date_range,
                )
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
        pct = 100.0 * count / max(active_invoices, 1)
        table.add_row(stype, EXPECTED_OUTCOME[stype], str(count), f"{pct:.1f}%")
    console.print(table)

    console.print(
        f"\nRun the agent against any bill from the manifest:\n"
        f"  [cyan]python -m scripts.run_agent <BILL_NAME>[/cyan]\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
