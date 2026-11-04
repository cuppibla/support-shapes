"""2 · Agent team: a coordinator and two specialists.

The coordinator owns the conversation. shipping and billing are sub-agents in
single_turn mode: the coordinator calls each one like a tool, gets a typed
report back, and decides what to do next. Each specialist has its own
instructions, its own tools and its own context.

billing's request REQUIRES the delivery status — so the coordinator has to hear
from shipping before it can ask billing. The dependency is in the schema.

Try it with the same message as the single agent:
  "My order #4821 never arrived. Can I get a refund?"
"""

from google.adk import Agent

from shared import MODEL
from shared import data
from shared.data import SIGNED_IN_CUSTOMER
from shared.team import billing_agent, shipping_agent

def _fresh_run(callback_context):
    """Demo only: forget earlier refunds so the same order can be replayed."""
    data.reset()


root_agent = Agent(
    name="coordinator",
    model=MODEL,
    description="Support coordinator: delegates to the shipping and billing specialists.",
    sub_agents=[shipping_agent(), billing_agent(can_refund=True)],
    instruction=f"""You coordinate customer support for an online store.
The signed-in customer is {SIGNED_IN_CUSTOMER}.
Two specialists work for you: shipping (where is the package) and billing (payments, refund policy, refunds).

For a delivery problem:
1. Ask shipping to investigate the order.
2. Then ask billing, passing the delivery_status that shipping reported. Never guess it.
3. Resolve the request and reply to the customer in two or three plain sentences.
If the customer gave no order number, ask for it before calling anyone.""",
    before_agent_callback=_fresh_run,
)
