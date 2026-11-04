"""1 · Single agent: one model, four tools, a loop.

The model reads the customer's message and chooses the next tool call. The
application runs the tool, hands the result back, and the model chooses again —
until it has enough to answer. The sequence is not written down anywhere: the
next action depends on what the previous tool returned.

Try it with:
  "My order #4821 never arrived. Can I get a refund?"   → lost → refund
  "My order #4822 never arrived. Can I get a refund?"   → in transit → ETA, no refund
  "My order never arrived. Can I get a refund?"         → no number → asks you
"""

from google.adk import Agent

from shared import MODEL
from shared import data
from shared.data import SIGNED_IN_CUSTOMER
from shared.tools import check_tracking, look_up_order, refund_policy, request_refund

def _fresh_run(callback_context):
    """Demo only: forget earlier refunds so the same order can be replayed."""
    data.reset()


root_agent = Agent(
    name="support_agent",
    model=MODEL,
    description="Customer support agent for an online store.",
    instruction=f"""You are the customer support agent for an online store.
The signed-in customer is {SIGNED_IN_CUSTOMER}.

Resolve the customer's problem end to end:
- look up the order, then check the carrier's delivery status,
- when a package is lost, check the refund policy and request the refund,
- when it is still in transit, give the customer the ETA instead,
- if you cannot identify the order, ask the customer for the order number.
Explain the outcome in two or three plain sentences.""",
    tools=[look_up_order, check_tracking, refund_policy, request_refund],
    before_agent_callback=_fresh_run,
)
