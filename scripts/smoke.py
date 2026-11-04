"""Run one app from the CLI and print what happened — tool calls, routes, pauses, text.

    python scripts/smoke.py support_agent "My order #4821 never arrived. Can I get a refund?"
    python scripts/smoke.py support_workflow "My order #4823 never arrived. Can I get a refund?" approve
    python scripts/smoke.py support_workflow "My order never arrived. Can I get a refund?" 4821

Extra arguments are follow-up messages sent into the same session (for RequestInput pauses).
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "apps")]

from google.adk import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.adk.workflow.utils._workflow_hitl_utils import create_request_input_response  # noqa: E402
from google.genai import types as gtypes  # noqa: E402

from shared import data  # noqa: E402


def describe(event) -> list[str]:
    out = []
    name = type(event).__name__
    author = getattr(event, "author", None) or getattr(event, "node_name", None) or ""
    route = getattr(event, "route", None)
    if route:
        out.append(f"  ↳ [{author}] route={route!r}")
    if name == "RequestInput" or "RequestInput" in name:
        out.append(f"  ⏸ PAUSE [{author}]: {getattr(event, 'message', '')}")
        return out
    msg = getattr(event, "message", None)
    parts = getattr(msg, "parts", None) or []
    for p in parts:
        fc = getattr(p, "function_call", None)
        if fc:
            out.append(f"  🔧 [{author}] call {fc.name}({dict(fc.args) if fc.args else ''})")
        fr = getattr(p, "function_response", None)
        if fr:
            out.append(f"  ↩  [{author}] {fr.name} → {fr.response}")
        if getattr(p, "text", None):
            out.append(f"  💬 [{author}] {p.text.strip()}")
    if isinstance(msg, str) and msg:
        out.append(f"  💬 [{author}] {msg}")
    return out


def pending_interrupt(event) -> str | None:
    """The interrupt id if this event is a workflow pause (RequestInput)."""
    for p in getattr(getattr(event, "message", None), "parts", None) or []:
        fc = getattr(p, "function_call", None)
        if fc and fc.name == "adk_request_input":
            return fc.id
    return None


async def main(app: str, messages: list[str]) -> None:
    data.reset()
    agent = importlib.import_module(app).root_agent
    runner = Runner(node=agent, app_name=app, session_service=InMemorySessionService(), auto_create_session=True)
    interrupt_id: str | None = None
    for text in messages:
        if interrupt_id:
            # A paused workflow resumes from a function_response on its interrupt id —
            # the same thing adk web sends when you type into the pause prompt.
            print(f"\n{'='*70}\n👤 (reply to pause) {text}\n")
            new_message = gtypes.Content(role="user", parts=[create_request_input_response(interrupt_id, {"result": text})])
            interrupt_id = None
        else:
            print(f"\n{'='*70}\n👤 {text}\n")
            new_message = gtypes.Content(role="user", parts=[gtypes.Part(text=text)])
        async for event in runner.run_async(user_id="u1", session_id="s1", new_message=new_message):
            for line in describe(event):
                print(line)
            interrupt_id = pending_interrupt(event) or interrupt_id
    print(f"\nrefunds issued: {data.REFUNDS}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
