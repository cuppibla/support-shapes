"""3 · Graph workflow: the process, as an executable flowchart.

    START → receive → load_records ─┬─ ok → investigate → checks ─┬─ pass      → issue_refund ─┬─ success → write_reply
             (code)     (code)       │     ┌───────────┐  (code)   ├─ exception → human_review ─┘  (failed → human_review)
                                     │     │ shipping  │           └─ no_refund → write_reply
                                     │     │  → billing│
                                     │     │  → propose│  (the team, as a nested workflow)
                                     │     └───────────┘
                                     └─ missing → ask_customer → (reply) → back to load_records

Code loads the records and does the exact checks. The agent team investigates.
A function moves the money. One model call writes the reply. The workflow says
which step runs after which — the model never gets to skip a check.

Try it with:
  "My order #4821 never arrived. Can I get a refund?"   → checks pass → refund → reply
  "My order #4823 never arrived. Can I get a refund?"   → $650 > limit → human review (type approve)
  "My order never arrived. Can I get a refund?"         → asks for the number (type 4821) → loops back
"""

from __future__ import annotations

import json
import re
from typing import Literal

from google.adk import Agent, Event, Workflow
from google.adk.events import RequestInput
from google.adk.workflow import DEFAULT_ROUTE
from pydantic import BaseModel, Field

from shared import MODEL, data
from shared.team import BillingReport, ShippingReport, billing_node, shipping_node

ORDER_RE = re.compile(r"#?\b(\d{4})\b")


# ─── 1. code: receive the message, load the records ───────────────────────────

def receive(node_input: str):
    """Node input = the customer's message. Pull out the order number if there is one."""
    data.reset()
    m = ORDER_RE.search(node_input)
    yield Event(state={
        "message": node_input,
        "order_id": m.group(1) if m else "",
        "review_approved": False,
        "refund_amount": 0.0,
        "outcome_text": "",
    })


def load_records(order_id: str):
    """Load order + payment records and verify the order belongs to the signed-in customer. 0 LLM.
    No usable order → ask the customer instead of investigating nothing."""
    order = data.ORDERS.get(order_id)
    if not order or order["customer_id"] != data.SIGNED_IN_CUSTOMER:
        yield Event(state={"records": {"found": False, "order_id": order_id}}, route="missing")
        return
    records = {
        "found": True,
        "order": order,
        "payment": {"amount_paid": order["amount"],
                    "already_refunded": data.REFUNDS.get(order_id, {}).get("amount", 0.0)},
    }
    yield Event(state={"records": records, "records_text": json.dumps(records, indent=2)}, route="ok")


# ─── 2. the agent team investigates and proposes ──────────────────────────────
# The team is a nested workflow: shipping, then billing (it needs shipping's
# finding), then one function turns the two reports into a proposal.

class Proposal(BaseModel):
    delivery_status: str = Field(description="lost / in_transit / delivered / unknown")
    resolution: Literal["refund", "eta", "missing_info", "other"]
    reason: str


def propose(shipping_report: ShippingReport, billing_report: BillingReport):
    """The team's findings → one proposed resolution. Code, not a model. 0 LLM."""
    status = shipping_report.delivery_status
    if not shipping_report.found:
        proposal = Proposal(delivery_status="unknown", resolution="missing_info",
                            reason="No order found for the number given.")
    elif status in data.REFUNDABLE_STATUSES and billing_report.eligible:
        proposal = Proposal(delivery_status=status, resolution="refund", reason=billing_report.reason)
    elif status == "in_transit":
        proposal = Proposal(delivery_status=status, resolution="eta",
                            reason=f"{shipping_report.detail} ETA {shipping_report.eta}.")
    else:
        proposal = Proposal(delivery_status=status, resolution="other",
                            reason=f"{shipping_report.detail} {billing_report.reason}")
    yield Event(state={"proposal": proposal.model_dump()})


investigate = Workflow(
    name="investigate",
    edges=[("START", shipping_node(), billing_node(), propose)],
)


# ─── 3. code: the required checks, and the routing ────────────────────────────

def checks(proposal: dict, order_id: str):
    """Exact checks against the records — not the model's claims. 0 LLM."""
    proposal = Proposal.model_validate(proposal)
    if proposal.resolution != "refund":
        yield Event(state={"outcome_text": f"No refund. {proposal.reason}"}, route="no_refund")
        return

    order = data.ORDERS[order_id]
    carrier_status = data.TRACKING[order["tracking_number"]]["status"]
    already = data.REFUNDS.get(order_id, {}).get("amount", 0.0)
    amount = round(order["amount"] - already, 2)

    if carrier_status not in data.REFUNDABLE_STATUSES:
        yield Event(state={"outcome_text": f"No refund: the carrier record says '{carrier_status}'."}, route="no_refund")
    elif already > 0:
        yield Event(state={"outcome_text": f"No refund: order {order_id} was already refunded (${already:.2f})."}, route="no_refund")
    elif amount > data.AUTO_REFUND_LIMIT:
        yield Event(state={"refund_amount": amount}, route="exception")
    else:
        yield Event(state={"refund_amount": amount}, route="pass")


# ─── 4. code: the refund function enforces its own rules ──────────────────────

def issue_refund(order_id: str, refund_amount: float, review_approved: bool):
    """Moves the money. Checks again before it does — whichever path called it."""
    if order_id in data.REFUNDS:
        yield Event(state={"outcome_text": f"Refund refused: order {order_id} already refunded."}, route="failed")
        return
    if refund_amount > data.AUTO_REFUND_LIMIT and not review_approved:
        yield Event(route="failed")
        return
    ref = f"PAY-REF-{order_id}"
    data.REFUNDS[order_id] = {"amount": refund_amount, "payment_ref": ref}
    yield Event(
        state={"outcome_text": f"Refund of ${refund_amount:.2f} for order {order_id} issued by the payment service (ref {ref})."},
        route="success",
    )


# ─── 5. the two pauses: a person (RequestInput), or the customer (a task agent) ──

def human_review(order_id: str, refund_amount: float):
    yield RequestInput(
        message=(f"Human review needed: order {order_id}, refund ${refund_amount:.2f} exceeds the "
                 f"${data.AUTO_REFUND_LIMIT:.0f} auto-refund limit. Reply 'approve' or 'reject'.")
    )


def handle_review(node_input):
    """node_input = the reviewer's reply. (Untyped on purpose: a numeric-looking reply arrives as an int.)"""
    if str(node_input).strip().lower().startswith("approve"):
        yield Event(state={"review_approved": True}, route="approve")
    else:
        yield Event(state={"outcome_text": "A support manager reviewed the request and declined the refund."}, route="reject")


class OrderNumber(BaseModel):
    order_id: str = Field(description="The customer's order number, digits only.")


# A task-mode agent: it asks the customer, the workflow pauses until they reply,
# and it finishes the task once it has the number. (Sample 22's pattern.)
ask_customer = Agent(
    name="ask_customer",
    model=MODEL,
    mode="task",
    description="Asks the customer for an order number the system could not find.",
    instruction="""You are a support assistant. The system could not find an order for this customer
(order number given so far: "{order_id?}").
Ask one short, friendly question for the order number. Do not make anything up.
When the customer gives a number, finish the task with the digits only.""",
    output_schema=OrderNumber,
)


def handle_customer_reply(node_input: OrderNumber):
    """The customer's reply → state, then back to load_records."""
    m = ORDER_RE.search(str(node_input.order_id))
    yield Event(state={"order_id": m.group(1) if m else ""})


# ─── 6. one model call writes the customer-facing reply ───────────────────────

write_reply = Agent(
    name="write_reply",
    model=MODEL,
    description="Writes the reply to the customer from the decided outcome.",
    instruction="""Write a short, clear reply to the customer — two or three sentences.
The customer wrote: {message}
The outcome the system decided: {outcome_text}
Explain that outcome. Do not promise anything beyond it.""",
)


# ─── the graph ────────────────────────────────────────────────────────────────

root_agent = Workflow(
    name="support_workflow",
    edges=[
        ("START", receive, load_records),
        (load_records, {"ok": investigate, DEFAULT_ROUTE: ask_customer}),
        (investigate, checks),
        (checks, {
            "pass": issue_refund,
            "exception": human_review,
            DEFAULT_ROUTE: write_reply,      # no_refund
        }),
        (issue_refund, {"success": write_reply, DEFAULT_ROUTE: human_review}),   # failed
        (human_review, handle_review),
        (handle_review, {"approve": issue_refund, DEFAULT_ROUTE: write_reply}),  # reject
        (ask_customer, handle_customer_reply),
        (handle_customer_reply, load_records),
    ],
)
