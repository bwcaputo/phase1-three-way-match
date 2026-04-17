# Agent Interface Contract

This document defines the stable contract between the experiment harness and
the three-way match agent. Follow it if you want to swap the agent
implementation, run a different model provider, or build a custom variant.

---

## What "the agent" is

The agent is the function `src.agent.run_agent`. It accepts an invoice number
and a set of optional overrides, calls a model via `src.model_adapter`, and
returns an `AgentResult`. The harness (`scripts/run_experiment.py`) calls this
function once per bill and records the result.

The agent does not know about experiments, configs, or sampling. It just
processes one invoice.

---

## Input contract

### `run_agent` signature

```python
def run_agent(
    invoice_number: str,
    client: Optional[OdooClient] = None,
    anthropic: Optional[Anthropic] = None,
    model: Optional[str] = None,
    max_turns: int = 12,
    verbose: bool = False,
    system_prompt: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    adapter: Optional[ModelAdapter] = None,
) -> AgentResult:
```

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `invoice_number` | `str` | required | Odoo bill number, e.g. `BILL/2026/0001` |
| `client` | `OdooClient` | auto | XML-RPC client. Created from `.env` if None |
| `anthropic` | `Anthropic` | auto | Legacy: raw Anthropic SDK client. Wrapped into `AnthropicAdapter` |
| `model` | `str` | `ANTHROPIC_MODEL` env | Model string passed to the provider |
| `max_turns` | `int` | 12 | Hard cap on agent loop iterations |
| `verbose` | `bool` | False | Print tool calls to stdout |
| `system_prompt` | `str` | module default | Override the RPST playbook |
| `tools` | `list[dict]` | `TOOL_SCHEMAS` | Override the tool set |
| `adapter` | `ModelAdapter` | auto | Override the model provider. Auto-selected from `model` if None |

The RPST axis a variant changes maps to exactly one override:

| RPST Axis | Override parameter |
|---|---|
| Role | `system_prompt` (persona text) |
| Playbook | `system_prompt` (workflow instructions) |
| Skills/Tools | `tools` |
| Tool implementation | Patch `src/tools.py` or `src/match.py` |

---

## Output contract

### `AgentResult` fields

```python
@dataclass
class AgentResult:
    match_result: Optional[MatchResult]  # structured output from run_three_way_match
    summary: str                          # model's plain-English narration
    tool_calls: int                       # total tool invocations this run
    turns: int                            # model round-trips
    input_tokens: int                     # summed across all turns
    output_tokens: int                    # summed across all turns
    latency_ms: int                       # wall-clock ms, start to finish
    stop_reason: Optional[str]            # last stop_reason from the model
    error: Optional[str]                  # set only if the run raised an exception
```

### `MatchResult` (the authoritative decision)

```python
class MatchResult(BaseModel):
    recommended_action: Literal["approve", "route_for_review", "block"]
    match_status: Literal["match", "mismatch", "missing_document", "duplicate", "error"]
    findings: list[str]         # human-readable list of discrepancies
    audit_trail: list[str]      # ordered log of every check performed
    dollar_exposure: Decimal    # 0.00 if approved; absolute variance if flagged
```

The harness grades accuracy by comparing `match_result.recommended_action`
to the expected action recorded in `playground_manifest.json`. If
`match_result` is `None` (the agent errored before calling the matcher),
the bill is scored incorrect.

---

## Tool schemas

The five tools available to the agent follow the Anthropic tool-use schema
(`name`, `description`, `input_schema`). They live in `src/tools.py` as
`TOOL_SCHEMAS`.

### `fetch_vendor_invoice`

```json
{
  "name": "fetch_vendor_invoice",
  "description": "Fetch a vendor invoice from Odoo by its bill number.",
  "input_schema": {
    "type": "object",
    "properties": {
      "invoice_number": { "type": "string", "description": "e.g. BILL/2026/0001" }
    },
    "required": ["invoice_number"]
  }
}
```

Returns: JSON object with `vendor_id`, `vendor_name`, `po_reference`,
`invoice_date`, `line_items` (list of `{product_id, product_name, quantity, unit_price, subtotal}`),
`amount_total`.

### `fetch_purchase_order`

```json
{
  "name": "fetch_purchase_order",
  "description": "Fetch a purchase order from Odoo by PO number.",
  "input_schema": {
    "type": "object",
    "properties": {
      "po_number": { "type": "string" }
    },
    "required": ["po_number"]
  }
}
```

Returns: JSON object with `po_number`, `vendor_id`, `vendor_name`,
`order_date`, `line_items`, `amount_total`.

### `fetch_goods_receipt`

```json
{
  "name": "fetch_goods_receipt",
  "description": "Fetch the goods receipt (stock picking) tied to a PO.",
  "input_schema": {
    "type": "object",
    "properties": {
      "po_number": { "type": "string" }
    },
    "required": ["po_number"]
  }
}
```

Returns: JSON object with `receipt_name`, `po_number`, `receipt_date`,
`line_items` (received quantities per SKU), or `{"error": "No goods receipt found"}`.

### `check_for_duplicate_invoices`

```json
{
  "name": "check_for_duplicate_invoices",
  "description": "Check whether this vendor has a near-duplicate posted invoice.",
  "input_schema": {
    "type": "object",
    "properties": {
      "vendor_id":      { "type": "integer" },
      "invoice_total":  { "type": "number" }
    },
    "required": ["vendor_id", "invoice_total"]
  }
}
```

Returns: JSON object with `duplicate_found` (bool), `matching_invoices`
(list of matching bill numbers if any).

### `run_three_way_match`

```json
{
  "name": "run_three_way_match",
  "description": "Run the deterministic three-way match. This is the authoritative decision.",
  "input_schema": {
    "type": "object",
    "properties": {
      "invoice_number": { "type": "string" },
      "po_number":      { "type": "string" },
      "duplicate_found": { "type": "boolean", "default": false }
    },
    "required": ["invoice_number", "po_number"]
  }
}
```

Returns: A `MatchResult` JSON object (see above). The model **must not**
override or reinterpret this result. Its only job is to narrate it.

---

## Model adapter protocol

To add a new model provider, subclass `ModelAdapter` in `src/model_adapter.py`:

```python
from src.model_adapter import ModelAdapter, MessageResponse, ContentBlock, UsageShim

class MyAdapter(ModelAdapter):
    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
    ) -> MessageResponse:
        # Call your provider's API here.
        # Translate the response into MessageResponse format.
        ...
        return MessageResponse(
            stop_reason="tool_use" | "end_turn",
            content=[ContentBlock(type="tool_use", id=..., name=..., input={...})],
            usage=UsageShim(input_tokens=N, output_tokens=M),
        )
```

Then pass it directly:

```python
from scripts.run_experiment import run_experiment
result = run_agent(invoice_number, adapter=MyAdapter(), model="my-model")
```

Or register a prefix in `get_adapter()` in `src/model_adapter.py` so it
auto-selects by model name.

---

## How the harness calls the agent

`scripts/run_experiment.py` loads a YAML config, draws a sample from
`playground_manifest.json`, and calls `run_agent` once per bill:

```python
result = run_agent(
    invoice_number=bill["invoice_number"],
    model=cfg.model,
    system_prompt=cfg.system_prompt,       # None -> module default
    tools=cfg.tools,                        # None -> TOOL_SCHEMAS
)
correct = (
    result.match_result is not None
    and result.match_result.recommended_action == bill["expected_action"]
)
```

The result is written to `experiments/<variant>/runs.jsonl` and
`experiments/<variant>/summary.json`.

---

## Grading rules

| Condition | Score |
|---|---|
| `match_result.recommended_action == expected_action` | correct |
| `match_result is None` (agent errored) | incorrect |
| `match_result.recommended_action != expected_action` | incorrect |
| `error` is set but `match_result` is still populated | graded on `recommended_action` |

"Accuracy" in `summary.json` is `correct / bills_attempted` (not
`correct / bills_completed`). This penalizes crashes and connection errors
as incorrect predictions rather than ignoring them.

---

## Extending the playground

Bills are seeded by `scripts/seed_playground.py` and recorded in
`playground_manifest.json`. Each entry has:

```json
{
  "invoice_number": "BILL/2026/0042",
  "scenario_type":  "partial_shipment",
  "expected_action": "approve",
  "po_number":      "P00042",
  "vendor_name":    "Acme Corp"
}
```

To add a new scenario type:

1. Add a branch in `seed_playground.py`'s `execute_scenario()` function.
2. Add the scenario key to `EXPECTED_OUTCOME` and `ALL_SCENARIOS`.
3. Add a fraction to the `scenario_mix` in the profile YAML.
4. Re-seed: `docker compose down -v && docker compose up -d && python scripts/seed_playground.py`

The matcher in `src/match.py` may need updating if the new scenario
introduces a discrepancy type it doesn't currently check.
