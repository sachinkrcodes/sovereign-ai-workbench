"""The agent loop: the model asks for a tool, we check permission, run it, and feed the result
back, until the model gives a final answer or a limit is reached.

Every step is recorded so a run can be audited afterwards."""

import json
import logging
import time
from dataclasses import dataclass, field

from app.agents.registry import AgentSpec
from app.agents.tools import Tool, ToolContext, ToolError
from app.services.errors import LLMUnavailable

logger = logging.getLogger("app.agents")

MAX_TOOL_OUTPUT_CHARS = 2500
MAX_CALLS_PER_TURN = 3
PREVIEW_CHARS = 300


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class AgentResult:
    status: str  # completed | step_limit | failed
    answer: str | None
    steps: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    model: str | None = None
    error: str | None = None


def extract_tool_calls(message: dict, known_tools: set[str]) -> list[ToolCall]:
    """Read tool calls from the model's message.
    Small models sometimes write the call as JSON text instead of using the proper field,
    so that form is accepted too (only for known tool names)."""
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = (item or {}).get("function") or {}
        name = function.get("name")
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if name and isinstance(arguments, dict):
            calls.append(ToolCall(str(name), arguments))
    if calls:
        return calls[:MAX_CALLS_PER_TURN]

    content = (message.get("content") or "").strip()
    if content.startswith("{") and content.endswith("}"):
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return []
        name = data.get("name")
        arguments = data.get("parameters", data.get("arguments", {}))
        if name in known_tools and isinstance(arguments, dict):
            return [ToolCall(str(name), arguments)]
    return []


def _preview(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 3] + "..."


def _execute(call: ToolCall, allowed: dict[str, Tool], ctx: ToolContext, step: int):
    """Run one tool call safely. Returns (step_record, text_for_model, sources)."""
    started = time.perf_counter()
    sources: list[dict] = []
    if call.name not in allowed:
        status = "denied"
        text = (
            f"Permission denied: you may not use '{call.name}'. "
            f"Your allowed tools: {', '.join(sorted(allowed)) or 'none'}."
        )
    else:
        try:
            result = allowed[call.name].handler(ctx, call.arguments)
            status, text, sources = "ok", result.text, result.sources
        except ToolError as exc:
            status, text = "error", f"Tool error: {exc}"
        except Exception:  # a bug in a tool must never crash the whole run
            logger.exception("tool %s crashed", call.name)
            status, text = "error", "Tool failed unexpectedly."
    text = text[:MAX_TOOL_OUTPUT_CHARS]
    record = {
        "step": step,
        "tool": call.name,
        "arguments": call.arguments,
        "status": status,
        "output_preview": _preview(text),
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    return record, text, sources


def _add_sources(target: list[dict], new: list[dict]) -> None:
    for source in new:
        if source not in target:
            target.append(source)


def run_agent(
    spec: AgentSpec,
    task: str,
    chat,
    ctx: ToolContext,
    tools: dict[str, Tool],
) -> AgentResult:
    allowed = {name: tools[name] for name in spec.allowed_tools if name in tools}
    tool_specs = [tool.spec() for tool in allowed.values()]
    known = set(tools)
    messages: list[dict] = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": task},
    ]
    steps: list[dict] = []
    sources: list[dict] = []
    deadline = time.monotonic() + spec.max_seconds

    def finish(status: str, answer: str | None, error: str | None = None) -> AgentResult:
        return AgentResult(status, answer, steps, sources, getattr(chat, "model_name", None), error)

    try:
        for _ in range(spec.max_steps):
            if time.monotonic() > deadline:
                break
            message = chat.chat(messages, tool_specs)
            calls = extract_tool_calls(message, known)
            if not calls:
                answer = (message.get("content") or "").strip()
                return finish("completed", answer or "The agent produced no answer.")

            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {}),
                }
            )
            for call in calls:
                record, text, found = _execute(call, allowed, ctx, len(steps) + 1)
                steps.append(record)
                _add_sources(sources, found)
                messages.append({"role": "tool", "tool_name": call.name, "content": text})

        # Limit reached: ask for a final answer using only what was gathered.
        messages.append(
            {
                "role": "user",
                "content": "Step limit reached. Using only the information gathered above, "
                "write your final answer now. Do not call any tools.",
            }
        )
        message = chat.chat(messages, [])
        answer = (message.get("content") or "").strip()
        return finish("step_limit", answer or "The agent produced no answer.")
    except LLMUnavailable as exc:
        logger.warning("agent %s stopped: %s", spec.name, exc)
        return finish("failed", None, str(exc))
