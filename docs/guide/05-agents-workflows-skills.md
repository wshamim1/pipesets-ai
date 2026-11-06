# 5. Agents, workflows and skills

## When to use what

| You want | Use |
|---|---|
| One model that answers, maybe with tools | An **LLM** node ([Building pipelines](02-building-pipelines.md)) |
| A planner that splits a task across specialists | **Master Agent + Child Agents** |
| To reuse a whole published pipeline as one step or specialist | A **Pipeline** node, or a Child Agent of kind *pipeline* |
| To call an agent that lives outside Pipesets | A Child Agent of kind *external* |
| A person to approve or edit before the run continues | **Human Gate** |
| A guided conversation that collects answers step by step | **Workflow Steps** |
| Instructions and tools that switch on only for certain topics | **Skills** |

## Master and Child agents

A **Master Agent** gets the task, plans it, hands parts to its **Child Agents**, and combines their
results.

### Set up

1. Drag a **Master Agent** onto the canvas, after Start.
2. **Identity & Goal:** the **Agent Goal** says what the team produces, e.g. "Write a due-diligence
   brief on the operator named by the user."
3. **LLM (Planning):** the model that plans and combines. Pick a strong one.
4. **Coordination Strategy:**

   | Strategy | How it runs | Good for |
   |---|---|---|
   | Sequential | Children one at a time, each getting the previous output | Pipelines: research → write → review |
   | Parallel | All children at once, results merged | Independent parts: financials + licensing + news |
   | Dynamic | The master picks which child to call next, as it goes | Open-ended tasks |

   **Max Steps** caps how many delegations one run may make.
5. Drag **Child Agents** and connect each to the Master.

### Child Agent kinds

| Kind | What it is | Set |
|---|---|---|
| **LLM** (default) | A specialist model with its own prompt and tools | **Specialist Role** (Researcher, Writer, Reviewer, Planner, Code Generator, Data Analyst, Fact Checker, Summariser, Translator, Extractor, Classifier, Support Agent, or Custom), model, **System Prompt**, **Allowed Tool IDs** |
| **Pipeline** | A published pipeline as the specialist | **Pipeline**, **Version** (or latest), **Timeout** |
| **External** | An agent running elsewhere, called over HTTP | **Protocol**, **Endpoint URL**, auth, request/response mapping (below) |

Picking a role fills in a starting system prompt; edit it to fit. Connect tools to a child the same
way as to an LLM node, and list them in **Allowed Tool IDs** to limit what it may call.

### External agents

| Protocol | Use for | Notes |
|---|---|---|
| OpenAI-compatible | Anything serving `/v1/chat/completions` (vLLM, another gateway, a hosted agent) | Set **Model** |
| Generic REST / webhook | Your own HTTP service | **Request Body (JSON)** template and **Response Path** to the answer field |
| A2A | Agent2Agent JSON-RPC agents | |

**Auth:** None, Bearer token, or a custom header (**Header Name** + token). Use a secret for the
token. Private network addresses are blocked unless the server allows them
(`EXTERNAL_AGENT_ALLOW_PRIVATE`, `EXTERNAL_AGENT_ALLOWED_HOSTS`).

### Runs, checkpoints and resuming

Master Agent runs are checkpointed. An interrupted or failed run can **resume** from its last step
without repeating finished model and tool calls: from the Run panel, or `POST /v1/runs/{id}/resume`.

## Human Gate

Puts a person in the loop of a Master Agent run.

1. Drag a **Human Gate** between the steps that need checking (e.g. before an email is sent).
2. **Gate Type:**
   - **Approval:** the run pauses until someone approves or rejects.
   - **Edit Gate:** the reviewer can change the output before it continues.
   - **Review:** doesn't pause; reviewers can flag issues afterwards.
3. **Prompt Message:** what the reviewer should check.
4. **Timeout (hours)** and **On Timeout:** auto-approve, auto-reject (run fails), or escalate.

When a run pauses, the Run panel shows **approve / reject / edit**. Through `/v1` the stream sends a
`paused` event; continue with `POST /v1/runs/{id}/resume` and a `gate_decision` (`approve`,
`reject` or `edit`). Set up **Automation → Alerts** for "Waiting for approval" so reviewers hear
about it in Slack.

## Workflows (conversational steps)

A workflow is a guided conversation: it asks, waits for the user's reply, and continues. Use it for
intake forms, onboarding, triage.

1. Chain **Workflow Step** nodes from Start.
2. Pick each step's **Step Type**:

   | Type | Does | Pauses? |
   |---|---|---|
   | Ask | Asks a question; **Expected Input** is text, number or date | Yes |
   | Choice | Offers options from a list (**Options From** a variable; label and value fields) | Yes |
   | Confirm | Yes / no; branch on the answer | Yes |
   | Tool Call | Runs a tool with **Input to Tool** | No |
   | Message | Shows text | No |

3. **Save Result As** stores the answer in a variable. Use it later as `{{name}}`, `{{order.id}}` or
   `{{items[0].sku}}` in messages and tool inputs.

Each run keeps the version it started with, so publishing a change doesn't break conversations in
progress. One reply runs at most 50 steps, so a loop can't spin forever.

## Skills

A skill packages *how to do something*: instructions (an SOP) plus the tools it needs. The agent
only sees a one-line "when to use" for each skill and loads the full instructions when a request
needs them, so the prompt stays short and dozens of tools don't confuse the model.

### Create a skill

1. **Tools & integrations → Skills → ⚡ Manage Skills Catalog**, and create a skill (or open one).
2. Fill in:
   - **Name**, icon, category, tags.
   - **When to use** (up to 300 characters): all the model sees until it loads the skill. Write it as
     "When the user asks to…", e.g. "When the user asks why an Airflow DAG run failed".
   - **Instructions:** the steps to follow, written as you'd brief a colleague. The model gets them
     when it loads the skill.
   - **Tools it needs:** tool or MCP server ids, e.g. `airflow, airflow_task_logs`.
3. Drag the skill onto the canvas and connect it to an LLM node, together with the tools it needs.

The Skill node shows whether it's ready: **✓ Its 4 tool(s) are attached**, or **⚠ Needs:** the tools
to attach to the LLM node and the settings to fill in on them (e.g. `base_url` on the Airflow tool).
A flow with a skill that isn't ready shows a blocking issue in **Validate** and **can't be
published** until it's fixed.

Every save is a new **version**. A Skill node uses the latest version unless you pin one in its
config, so fixing a skill fixes every pipeline that uses it. Built-in skills can't be edited; copy
one to change it.

### How the agent uses skills

On the LLM node, **Skills** has two settings:

- **Load when needed** (default): the system prompt lists each attached skill's name and "when to
  use", and the model gets one extra tool, `use_skill`. When a request matches, it loads the skill
  and gets its instructions back. Attached tools that a skill needs stay **hidden until that skill is
  loaded**; other attached tools are available from the start. **Max loaded** (default 3) caps how
  many skills one request can load.
- **Always in the prompt:** every skill's instructions go in the prompt and every tool is on. Use
  it for small models that don't call tools well. Runs on the mock provider or a local model
  (Ollama, llama.cpp, Jan) and Child agents always work this way.

The Prompt Runner shows **🧩 Skill name** under the answer for each skill a run loaded, and the
trace has a "Loaded skill" step showing which version it used and which tools it switched on.

### Starter skills

Built in, for the data-platform tool packages: **Airflow DAG triage**, **Databricks job triage**,
**Snowflake slow or costly query review** and **Kafka consumer lag investigation**. Each uses only
its package's tools. A starter skill is usable once those tools are installed (**Settings → Tools &
MCP packages**).

Good skills are narrow ("renew a state SNF licence"), not broad ("compliance").
