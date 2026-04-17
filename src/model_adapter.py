"""
model_adapter.py -- Model abstraction layer for the three-way match agent.

Provides a common interface so run_experiment.py and agent.py can target
different model providers without forking the agent loop.

Three adapters ship by default:
  AnthropicAdapter  -- claude-* models via the Anthropic Messages API
  OpenAIAdapter     -- gpt-* / o-series via the OpenAI Chat Completions API
  OllamaAdapter     -- local models via Ollama's OpenAI-compatible endpoint

Usage from agent.py (drop-in):
    from .model_adapter import get_adapter

    adapter = get_adapter(model_name)
    response = adapter.create_message(
        model=model_name,
        system=system_prompt,
        messages=messages,
        tools=tool_schemas,
        max_tokens=2048,
    )
    # response.stop_reason    -> "tool_use" | "end_turn" | "stop"
    # response.content        -> list[ContentBlock]
    # response.usage          -> Usage(input_tokens, output_tokens)

The Anthropic adapter returns native Anthropic response objects -- the rest
of agent.py stays unchanged. The OpenAI and Ollama adapters return thin
shims that expose the same attributes.

Provider selection:
  get_adapter("claude-*")               -> AnthropicAdapter
  get_adapter("gpt-*" | "o1-*" | "o3-*")  -> OpenAIAdapter
  get_adapter("ollama:*" | "llama*" | "mistral*" | "phi*" | "gemma*")
                                        -> OllamaAdapter

You can also instantiate adapters directly:
    adapter = OllamaAdapter(base_url="http://localhost:11434")
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Shared response shim
# ---------------------------------------------------------------------------

@dataclass
class ContentBlock:
    """Minimal shim that mirrors anthropic.types.ContentBlock for tool_use and text."""
    type: str                          # "text" | "tool_use"
    text: str = ""                     # populated when type=="text"
    id: str = ""                       # populated when type=="tool_use"
    name: str = ""                     # tool name when type=="tool_use"
    input: dict = field(default_factory=dict)  # tool arguments


@dataclass
class UsageShim:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class MessageResponse:
    """Unified response object returned by all adapters.

    Mirrors the Anthropic SDK's Message object closely enough that
    agent.py can use either without change, provided it accesses
    only: stop_reason, content (list[ContentBlock]), usage.
    """
    stop_reason: str                       # "tool_use" | "end_turn"
    content: list[ContentBlock]
    usage: UsageShim = field(default_factory=UsageShim)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ModelAdapter(ABC):
    """Abstract base: one method to implement per provider."""

    @abstractmethod
    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
    ) -> Any:
        """Send a conversation turn and return a response.

        Implementations may return a native SDK object (as AnthropicAdapter
        does) or a MessageResponse shim (as OpenAI/Ollama adapters do).
        The caller (agent.py) accesses .stop_reason, .content, and .usage.
        """

    def supports_tools(self) -> bool:
        """Return True if this adapter supports structured tool use."""
        return True


# ---------------------------------------------------------------------------
# Anthropic adapter (native, no shim needed)
# ---------------------------------------------------------------------------

class AnthropicAdapter(ModelAdapter):
    """Thin wrapper around the Anthropic Python SDK.

    Returns the native Anthropic Message object -- no shim -- so the
    rest of agent.py works without modification.
    """

    def __init__(self, client: Any = None) -> None:
        """
        Args:
            client: An ``anthropic.Anthropic`` instance. If None, one is
                    created using the ANTHROPIC_API_KEY environment variable.
        """
        if client is not None:
            self._client = client
        else:
            try:
                from anthropic import Anthropic
                self._client = Anthropic()
            except ImportError as exc:
                raise ImportError(
                    "anthropic package not installed. Run: pip install anthropic"
                ) from exc

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
    ) -> Any:
        return self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------

class OpenAIAdapter(ModelAdapter):
    """Adapter for OpenAI gpt-* and o-series models.

    Translates between Anthropic-style tool schemas (input_schema) and
    OpenAI-style function schemas (parameters). Returns a MessageResponse
    shim so agent.py needs no changes.

    Lazy import: ``openai`` is not required unless you use this adapter.
    Install with: pip install openai
    """

    def __init__(self, client: Any = None, base_url: Optional[str] = None) -> None:
        """
        Args:
            client:   An ``openai.OpenAI`` instance. If None, one is created.
            base_url: Optional API base URL (e.g. for Azure or proxies).
        """
        self._client = client
        self._base_url = base_url

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "openai package not installed. Run: pip install openai"
            ) from exc
        kwargs: dict[str, Any] = {}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = openai.OpenAI(**kwargs)
        return self._client

    @staticmethod
    def _translate_tools(anthropic_tools: list[dict]) -> list[dict]:
        """Convert Anthropic tool schemas to OpenAI function-calling format."""
        oai_tools = []
        for t in anthropic_tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return oai_tools

    @staticmethod
    def _translate_messages(messages: list[dict]) -> list[dict]:
        """Translate Anthropic message list to OpenAI format.

        Handles tool_result blocks (Anthropic) -> tool messages (OpenAI).
        """
        oai_msgs: list[dict] = []
        for m in messages:
            role    = m["role"]
            content = m["content"]

            if isinstance(content, str):
                oai_msgs.append({"role": role, "content": content})
                continue

            if role == "user" and isinstance(content, list):
                # May contain tool_result blocks
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                text_parts   = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]

                if tool_results:
                    for tr in tool_results:
                        tr_content = tr.get("content", "")
                        if isinstance(tr_content, list):
                            tr_content = "\n".join(
                                block.get("text", "") if isinstance(block, dict) else str(block)
                                for block in tr_content
                            )
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": tr["tool_use_id"],
                            "content": str(tr_content),
                        })
                if text_parts:
                    combined = "\n".join(b.get("text", "") for b in text_parts)
                    oai_msgs.append({"role": "user", "content": combined})
                if not tool_results and not text_parts:
                    oai_msgs.append({"role": role, "content": str(content)})

            elif role == "assistant" and isinstance(content, list):
                # May contain tool_use blocks
                text_blocks = [b for b in content if getattr(b, "type", None) == "text" or
                               (isinstance(b, dict) and b.get("type") == "text")]
                tool_blocks = [b for b in content if getattr(b, "type", None) == "tool_use" or
                               (isinstance(b, dict) and b.get("type") == "tool_use")]

                text = " ".join(
                    (b.text if hasattr(b, "text") else b.get("text", ""))
                    for b in text_blocks
                )
                tool_calls = []
                for tb in tool_blocks:
                    name  = tb.name if hasattr(tb, "name") else tb.get("name", "")
                    tid   = tb.id   if hasattr(tb, "id")   else tb.get("id", "")
                    inp   = tb.input if hasattr(tb, "input") else tb.get("input", {})
                    tool_calls.append({
                        "id": tid,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(inp)},
                    })

                msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                oai_msgs.append(msg)
            else:
                oai_msgs.append({"role": role, "content": str(content)})

        return oai_msgs

    def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
    ) -> MessageResponse:
        client = self._get_client()
        oai_messages = [{"role": "system", "content": system}] + self._translate_messages(messages)
        oai_tools    = self._translate_tools(tools)

        kwargs: dict[str, Any] = dict(
            model=model,
            messages=oai_messages,
            max_tokens=max_tokens,
        )
        if oai_tools:
            kwargs["tools"] = oai_tools

        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg    = choice.message

        content_blocks: list[ContentBlock] = []

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                content_blocks.append(ContentBlock(
                    type="tool_use",
                    id=tc.id,
                    name=tc.function.name,
                    input=arguments,
                ))
            stop_reason = "tool_use"
        else:
            content_blocks.append(ContentBlock(
                type="text",
                text=msg.content or "",
            ))
            stop_reason = "end_turn"

        usage = UsageShim(
            input_tokens=getattr(resp.usage, "prompt_tokens", 0),
            output_tokens=getattr(resp.usage, "completion_tokens", 0),
        )
        return MessageResponse(stop_reason=stop_reason, content=content_blocks, usage=usage)


# ---------------------------------------------------------------------------
# Ollama adapter
# ---------------------------------------------------------------------------

class OllamaAdapter(OpenAIAdapter):
    """Adapter for local Ollama models.

    Ollama exposes an OpenAI-compatible endpoint at localhost:11434/v1, so
    this subclass just sets the base URL and skips the API-key requirement.

    Lazy import: ``openai`` is required (used as the HTTP client).
    Install with: pip install openai

    Usage:
        adapter = OllamaAdapter()              # defaults to localhost:11434
        adapter = OllamaAdapter("http://remote-host:11434")
    """

    def __init__(self, base_url: str = "http://localhost:11434/v1") -> None:
        super().__init__(base_url=base_url)

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "openai package required for OllamaAdapter. Run: pip install openai"
            ) from exc
        # Ollama doesn't require a real API key
        self._client = openai.OpenAI(
            base_url=self._base_url,
            api_key="ollama",
        )
        return self._client


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-", "text-davinci")
_OLLAMA_PREFIXES = ("ollama:", "llama", "mistral", "phi", "gemma", "qwen", "deepseek", "codellama")


def get_adapter(model_name: str) -> ModelAdapter:
    """Return the right adapter for a given model name.

    Rules (first match wins):
      - Starts with "claude-"                          -> AnthropicAdapter
      - Starts with "ollama:" or a known local prefix  -> OllamaAdapter
      - Starts with a known OpenAI prefix              -> OpenAIAdapter
      - Default (unknown)                              -> AnthropicAdapter

    Override by instantiating an adapter directly.
    """
    name = model_name.lower()

    if name.startswith("claude-"):
        return AnthropicAdapter()

    for prefix in _OLLAMA_PREFIXES:
        if name.startswith(prefix):
            # Strip "ollama:" prefix if present for the actual model tag
            return OllamaAdapter()

    for prefix in _OPENAI_PREFIXES:
        if name.startswith(prefix):
            return OpenAIAdapter()

    # Unknown model -- assume Anthropic (safest default for this project)
    return AnthropicAdapter()
