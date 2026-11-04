"""The two specialists, as a factory. Agents can't be shared between parents,
so support_team and support_workflow each build their own copies.

Both run in mode="single_turn": the coordinator calls them like tools, each
answers once with a typed report, and control returns to the coordinator.
billing's input schema REQUIRES delivery_status — that's what makes the
"shipping first, then billing" dependency structural instead of hoped-for."""

from __future__ import annotations

from google.adk import Agent
from google.genai import types as gtypes
from pydantic import BaseModel, Field

from . import MODEL
from .tools import check_tracking, look_up_order, payment_lookup, refund_policy, request_refund


class ShippingRequest(BaseModel):
    order_id: str = Field(description="The order number to investigate.")


class ShippingReport(BaseModel):
    order_id: str | None = ""
    found: bool = False
    delivery_status: str | None = Field(default="unknown", description="lost / in_transit / delivered / unknown")
    detail: str | None = ""
    eta: str | None = None


class BillingRequest(BaseModel):
    order_id: str
    delivery_status: str = Field(
        description="The delivery status that the shipping specialist reported. Required."
    )


class BillingReport(BaseModel):
    order_id: str | None = ""
    eligible: bool = False
    refunded: bool = False
    amount: float | None = None
    needs_human_review: bool = False
    reason: str | None = ""


def shipping_agent() -> Agent:
    return Agent(
        name="shipping",
        model=MODEL,
        mode="single_turn",
        description="Shipping specialist: investigates where an order is and what the carrier says.",
        instruction="""You are the shipping specialist for an online store.
Given an order number: look up the order, then check its tracking number with the carrier.
Report the delivery status exactly as the carrier gives it (lost / in_transit / delivered / unknown)
with the carrier's detail and ETA if any. If the order is not found, say so (found=false).
Do not discuss refunds or payments — that is billing's job.""",
        tools=[look_up_order, check_tracking],
        input_schema=ShippingRequest,
        output_schema=ShippingReport,
    )


def billing_agent(can_refund: bool = True) -> Agent:
    tools = [payment_lookup, refund_policy] + ([request_refund] if can_refund else [])
    action = (
        "If eligible and no human review is needed, request the refund with the eligibility token and report refunded=true."
        if can_refund
        else "Do NOT issue refunds — only report eligibility, the refundable amount and whether human review is needed."
    )
    return Agent(
        name="billing",
        model=MODEL,
        mode="single_turn",
        description="Billing specialist: payments, refund history and refund policy. Needs the delivery status from shipping.",
        instruction=f"""You are the billing specialist for an online store.
Given an order number and the delivery status reported by shipping:
look up the payment, then check the refund policy with that delivery status.
{action}
Report the outcome with the reason in one sentence.""",
        tools=tools,
        input_schema=BillingRequest,
        output_schema=BillingReport,
    )


# Workflow nodes must always act through a function call (a tool, or
# set_model_response to finish) — never answer in prose. Mode ANY enforces it.
_TOOLS_ONLY = gtypes.GenerateContentConfig(
    tool_config=gtypes.ToolConfig(
        function_calling_config=gtypes.FunctionCallingConfig(mode="ANY")
    )
)


# ─── the same specialists as workflow nodes ──────────────────────────────────
# Inside a Workflow the team is a nested workflow (shipping → billing → propose):
# an ADK 2.5.0 Workflow node can't host a single_turn coordinator, and the edge
# says the same thing the schema said above — billing waits for shipping.
# Same tools, same report schemas; inputs come from workflow state.

def shipping_node() -> Agent:
    return Agent(
        name="shipping",
        model=MODEL,
        description="Shipping specialist: investigates where an order is and what the carrier says.",
        instruction="""You are the shipping specialist for an online store.
Investigate order "{order_id}": look up the order, then check its tracking number with the carrier.
Report the delivery status exactly as the carrier gives it (lost / in_transit / delivered / unknown)
with the carrier's detail and ETA if any.
If the order number is empty or the order is not found, report found=false and delivery_status=unknown
without calling check_tracking. Do not discuss refunds.
You are a background worker: the customer is not in this conversation. Never reply to them and never
ask a question — call the tools, then return the report.""",
        tools=[look_up_order, check_tracking],
        output_schema=ShippingReport,
        output_key="shipping_report",
        include_contents="none",   # a worker fed from state — it needs no chat history
        generate_content_config=_TOOLS_ONLY,
    )


def billing_node() -> Agent:
    return Agent(
        name="billing",
        model=MODEL,
        description="Billing specialist: payments, refund history and refund policy.",
        instruction="""You are the billing specialist for an online store.
Order "{order_id}". The shipping specialist reported: {shipping_report}
If shipping reported found=false, do not call any tool: eligible=false, reason "order not found".
Otherwise look up the payment, then check the refund policy with the delivery status shipping reported.
Do NOT issue refunds — report eligibility, the refundable amount and whether human review is needed,
with the reason in one sentence.
You are a background worker: the customer is not in this conversation. Never reply to them and never
ask a question — call the tools, then return the report.""",
        tools=[payment_lookup, refund_policy],
        output_schema=BillingReport,
        output_key="billing_report",
        include_contents="none",
        generate_content_config=_TOOLS_ONLY,
    )
