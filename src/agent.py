"""
Claude-orchestrated agent loop for three-way match.

The agent's job is narrow: given an invoice number (and optionally a PO
number), fetch the three documents, invoke the deterministic matcher, and
render a human-readable summary for the AP clerk. The math lives in
``match.py``; the model only orchestrates and narrates.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

from anthropic import Anthropic

from .model_adapter import ModelAdapter, get_adapter
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
    turns: int = 0  # number of model invocations (round-trips)
    input_tokens: int = 0  # summed across turns
    output_tokens: int = 0  # summed across turns
    latency_ms: int = 0  # wall-clock time for the full agent run
    stop_reason: Optional[str] = None  # last stop_reason from the model
    error: Optional[str] = None  # populated only if the run failed mid-loop


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
    """Run the three-way match agent on a single invoice.

    The optional ``system_prompt`` and ``tools`` overrides exist so
    experimental RPST variants can swap the playbook or toolset without
    forking this function. Pass ``None`` for either to use the defaults
    defined in this module / ``src.tools``.

    Pass ``adapter`` to use a non-Anthropic model provider (OpenAI, Ollama,
    or any ModelAdapter subclass). When ``adapter`` is None the function
    falls back to ``get_adapter(model)`` which routes by model name prefix.
    The legacy ``anthropic`` argument is still accepted for backwards
    compatibility and takes precedence if passed explicitly.
    """
    client = client or OdooClient()
    model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    dispatcher = ToolDispatcher(client)

    # Resolve adapter. Legacy callers may pass a raw Anthropic client;
    # wrap it so the loop below stays provider-agnostic.
    if adapter is None:
        if anthropic is not None:
            from .model_adapter import AnthropicAdapter
            adapter = AnthropicAdapter(client=anthropic)
        else:
            adapter = get_adapter(model)

    effective_system = system_prompt if system_prompt is not None else SYSTEM_PROMPT
    effective_tools = tools if tools is not None else TOOL_SCHEMAS

    messages: list[dict] = [
        {"role": "user", "content": f"Run the three-way match on invoice {invoice_number}."}
    ]

    tool_calls = 0
    turns = 0
    input_tokens = 0
    output_tokens = 0
    summary_text = ""
    last_stop_reason: Optional[str] = None

    started = time.perf_counter()
    try:
        for _turn in range(max_turns):
            resp = adapter.create_message(
                model=model,
                max_tokens=2048,
                system=effective_system,
                tools=effective_tools,
                messages=messages,
            )
            turns += 1
            last_stop_reason = resp.stop_reason
            usage = getattr(resp, "usage", None)
            if usage is not None:
                input_tokens += getattr(usage, "input_tokens", 0) or 0
                output_tokens += getattr(usage, "output_tokens", 0) or 0

            # Append assistant turn
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if getattr(block, "type", None) == "tool_use":
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

        error: Optional[str] = None
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    latency_ms = int((time.perf_counter() - started) * 1000)

    return AgentResult(
        match_result=dispatcher.last_result,
        summary=summary_text.strip(),
        tool_calls=tool_calls,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        stop_reason=last_stop_reason,
        error=error,
    )
