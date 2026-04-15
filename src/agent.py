"""
Claude-orchestrated agent loop for three-way match.

The agent's job is narrow: given an invoice number (and optionally a PO
number), fetch the three documents, invoke the deterministic matcher, and
render a human-readable summary for the AP clerk. The math lives in
``match.py``; the model only orchestrates and narrates.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from anthropic import Anthropic

from .models import MatchResult
from .odoo_client import OdooClient
from .tools import TOOL_SCHEMAS, ToolDispatcher


SYSTEM_PROMPT = """You are an AP (Accounts Payable) clerk assistant running a three-way match on a vendor invoice.

Your workflow for every invoice:
1. Call fetch_vendor_invoice to load the invoice.
2. From the invoice, read the PO reference. Call fetch_purchase_order on that PO.
3. Call fetch_goods_receipt for the same PO. If there is no receipt, that is a blocking finding — continue anyway.
4. Call check_for_duplicate_invoices using the vendor_id and the invoice total.
5. Call run_three_way_match. This is the authoritative decision.
6. Report the result to the user in plain English: what was checked, what the recommended action is, what specifically triggered it, and the dollar exposure.

Ground rules:
- Do not compute totals, quantities, or variances yourself. The run_three_way_match tool is the only source of the recommended action and the dollar amounts. Never override it.
- If a tool returns an error or a missing document, surface that as a blocking finding.
- Be concise. An AP clerk wants to know: approve / route / block, why, and what to do next.
"""


@dataclass
class AgentResult:
    match_result: Optional[MatchResult]
    summary: str  # Claude's final plain-English narration
    tool_calls: int


def run_agent(
    invoice_number: str,
    client: Optional[OdooClient] = None,
    anthropic: Optional[Anthropic] = None,
    model: Optional[str] = None,
    max_turns: int = 12,
    verbose: bool = False,
) -> AgentResult:
    client = client or OdooClient()
    anthropic = anthropic or Anthropic()
    model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    dispatcher = ToolDispatcher(client)

    messages: list[dict] = [
        {"role": "user", "content": f"Run the three-way match on invoice {invoice_number}."}
    ]

    tool_calls = 0
    summary_text = ""

    for _turn in range(max_turns):
        resp = anthropic.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Append assistant turn
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    tool_calls += 1
                    if verbose:
                        print(f"  -> {block.name}({block.input})")
                    result = dispatcher.dispatch(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # end_turn — assemble final text
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                summary_text += block.text
        break

    return AgentResult(
        match_result=dispatcher.last_result,
        summary=summary_text.strip(),
        tool_calls=tool_calls,
    )
