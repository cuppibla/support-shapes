# support-shapes — one support request, three ways to build the app

The demo behind the video *How Modern AI Apps Work: Agents, Teams, and Workflows*.
Three ADK 2 apps answer the same customer message with the same four fake tools:

| app | shape | what it shows |
| --- | --- | --- |
| `support_agent` | **single agent** — one model, four tools, a loop | the model picks the next tool from the last result |
| `support_team` | **agent team** — a coordinator and two `single_turn` specialists | responsibilities split; billing can't run before shipping |
| `support_workflow` | **graph workflow** — code → team → code checks → routes | the process is explicit; checks are nodes, not tool calls |

```
"My order #4821 never arrived. Can I get a refund?"
```

## Run it

```bash
uv venv --python 3.14 .venv && uv pip install -p .venv/bin/python "google-adk==2.5.0" python-dotenv
cp .env.example .env            # add GOOGLE_API_KEY (AI Studio) — or the Vertex variables
bash run.sh                     # adk web on http://localhost:48080
```

Pick an app in the dropdown, paste the message, then open **Events**, **Traces**, and the
**View Agent Structure Graph** button (top bar). The structure graph is the same picture as
the video's diagrams, drawn by the framework.

CLI, no browser (prints every tool call, route and pause):

```bash
.venv/bin/python scripts/smoke.py support_agent    "My order #4821 never arrived. Can I get a refund?"
.venv/bin/python scripts/smoke.py support_team     "My order #4821 never arrived. Can I get a refund?"
.venv/bin/python scripts/smoke.py support_workflow "My order #4823 never arrived. Can I get a refund?" approve
.venv/bin/python scripts/smoke.py support_workflow "My order never arrived. Can I get a refund?" "It's 4821"
```

## The scenarios (all fake data, in `shared/data.py`)

| message | single agent | team | workflow |
| --- | --- | --- | --- |
| `#4821` lost · $42 | look_up → tracking → policy → refund ✓ | shipping → billing (refunds) → reply | load → investigate → checks **pass** → `issue_refund` → reply |
| `#4822` in transit | look_up → tracking → ETA, no refund | — | checks **no_refund** → reply with ETA |
| `#4823` lost · $650 | refund tool refuses (over limit) | — | checks **exception** → `human_review` pause → `approve` → refund |
| no order number | asks for it, then continues | asks for it | `load_records` → `ask_customer` (task agent) → back to `load_records` |

Two things are deliberately structural, so the runs are reliable on camera instead of hoping the model behaves:

- `billing`'s input schema **requires** `delivery_status` → the coordinator must hear from shipping first.
- `request_refund` **requires** the `eligibility_token` that only `refund_policy` returns → the four-step
  sequence is enforced by code, and the refund tool checks its own rules before moving money.

## Layout

```
apps/support_agent/agent.py      1 · Agent(tools=[...])
apps/support_team/agent.py       2 · Agent(sub_agents=[shipping, billing])   single_turn specialists
apps/support_workflow/agent.py   3 · Workflow(edges=[...])                   team = nested Workflow node
shared/tools.py                  the four tools (+ payment_lookup)
shared/team.py                   shipping / billing — as sub-agents and as workflow nodes
shared/data.py                   orders, tracking, policy limit, refund store
scripts/smoke.py                 CLI runner (handles RequestInput pauses)
```

## Notes from building it on google-adk 2.5.0

- **A `single_turn` coordinator can't be a Workflow node.** Nesting `Agent(sub_agents=[...])`
  inside a `Workflow` fails on the coordinator's second model call
  (`No function call event found for function responses ids`). Inside the workflow the team is
  therefore a nested `Workflow(shipping → billing → propose)` — which also draws as a nested
  cluster in adk web, and makes the shipping→billing dependency an edge.
- **A tool-using agent after a `RequestInput` resume** hits Gemini's turn-order rule
  (`400 … function call turn comes immediately after a user turn`). `human_review` keeps
  `RequestInput` (only a tool-less agent runs after it); `ask_customer` is a `mode="task"`
  agent instead (official sample 22's pattern), which resumes cleanly into tool-using nodes.
- **Numeric-looking replies arrive as `int`** on resume — pause handlers take untyped `node_input`.
- **After a task-mode resume, a specialist occasionally answered the customer in prose** instead of
  calling its tools, and the structured report failed to parse. Fixed structurally: the two workflow
  specialists run with `include_contents="none"` and a `tool_config` of function-calling mode `ANY`
  (every turn is a tool call; finishing *is* the `set_model_response` call), plus an instruction line
  saying the customer is not in the conversation.
- **adk web's structure graph crashes for a `Workflow`** in 2.5.0 (`'Workflow' object has no attribute
  '_graph'`). One-line local fix:
  `sed -i '' 's/agent\._graph/agent.graph/g' .venv/lib/python3.14/site-packages/google/adk/cli/agent_graph.py`
- The refund store resets at the start of every root run so one order can be replayed in all
  three apps on camera.
