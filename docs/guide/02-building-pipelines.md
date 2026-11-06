# 2. Building pipelines

## The canvas

- **Add a node:** drag it from the left sidebar. The sidebar has four tabs: **Essentials**,
  **Tools & integrations**, **Knowledge (RAG)** and **Control & safety**. Use search to find a node
  by name.
- **Connect nodes:** drag from one node's handle to another's. An edge means "these work
  together": a Memory, Tool or Guardrail attached to an LLM node applies to that LLM.
- **Configure:** click a node. Its settings open in numbered cards. **Save to App** stores them,
  **Delete Node** removes the node.
- **Validation:** problems show live: an unconnected node, a missing key, a loader with no source.
  Fix errors before running; warnings are suggestions.
- **Try it unsaved:** the **Run** panel runs the canvas as it is, without publishing.

## Node reference

| Group | Node | What it does |
|---|---|---|
| Models | **LLM** | Calls a model with your system prompt; uses any tools, memory and guardrails attached to it |
| | **Output Parser** | Turns the answer into JSON, a typed schema, regex captures, CSV, an ISO date or one of a fixed set of values |
| Tools | **Tool** | A built-in or custom tool the model can call → [Tools](03-tools.md) |
| | **MCP server** | All the tools of an MCP server → [MCP](04-mcp.md) |
| | **Toolkit** | Your own bundle of tools as one node |
| | **Skill** | Instructions plus the tools they need, switched on by topic → [Skills](05-agents-workflows-skills.md#skills) |
| | **Connection** | Saved database or API credentials that tools and loaders use |
| Guardrails | **Middleware** | Checks before and after the model → [Guardrails](07-guardrails-budgets.md) |
| State | **Memory** | Conversation history across turns |
| | **Cache** | Reuses answers to repeated prompts |
| Retrieval | Doc Loader, Text Splitter, Embedding, Vector Store, Retriever, Reranker, Knowledge Base | Answer from your documents → [RAG](06-knowledge-rag.md) |
| Orchestration | **Start / Stop** | Where the flow begins and ends |
| | **Master Agent / Child Agent** | A planner that delegates to specialists → [Agents](05-agents-workflows-skills.md) |
| | **Gateway** | Branch, fan out, merge or loop |
| | **Human Gate** | Pause for a person to approve, edit or review |
| Workflows | **Workflow Step** | A conversational form: ask, choose, confirm, call a tool |
| Pipelines | **Pipeline** | Run another published pipeline as a step |

## The LLM node

| Card | Setting | Notes |
|---|---|---|
| 1. Model & Provider | Provider, Model | 19 providers through Pipesets' own gateway; local ones: Ollama, llama.cpp, Jan |
| 2. Sampling | Temperature, Max Tokens, Top P | Low temperature (0–0.3) for extraction and classification; higher for writing |
| 3. Credentials & URL | API Key, Base URL | Pick a **secret**, or leave empty to use the project key. Base URL for Ollama, llama.cpp, vLLM or a proxy. |
| 4. Instructions | System Prompt | What the model is and how it should answer. Be specific about format. |
| | Timeout, Max Retries (0–5), Retry Backoff | Retries cover temporary provider errors |
| | Fallback Provider / Model / Key / Base URL | Used when the main model fails after its retries. Use a different provider for real failover. |

Tips:

- Put rules in the system prompt, data in the user message.
- To make the model use a tool, name the tool and say when to call it.
- `{{document}}` in the system prompt is replaced by a document parsed with an attached Docling tool.

## Flow control: Gateway

| Type | Use |
|---|---|
| **Condition (IF/ELSE)** | Route on the upstream output. The expression is JavaScript with `output` as the text, e.g. `output.includes("ESCALATE")`. Name the true and false branches. |
| **Split (fan-out)** | Send the same output to 2–5 branches at once |
| **Merge (AND-join)** | Wait for all incoming branches, then continue |
| **Loop** | Repeat the connected nodes up to **Max Iterations**, or until the **Stop Condition** is true |

## Memory

Attach a **Memory** node to an LLM node so it remembers the conversation.

| Strategy | Keeps |
|---|---|
| Sliding window | Recent turns within a token budget; drops the oldest first (good default) |
| Summarize | The system prompt and last few turns; older turns compressed |
| Last K turns | The last N messages, whatever their size |

- **Session ID:** separates conversations. Through `/v1`, pass `session_id` per end user.
- **Session TTL:** how long an idle conversation is kept.
- **Long-term memory** (opt-in per workspace): facts a user states (preferences, profile, goals) are
  remembered across sessions, with personal data removed. **Facts recalled per run** sets how many
  come back. Inspect or forget them in **Monitor → Sessions**.

## Cache

Attach a **Cache** node to skip the model for repeated prompts.

| Scope | A hit needs the same… |
|---|---|
| Prompt | prompt, whatever the model |
| Model | prompt and model |
| Strict | prompt, model and all sampling settings |

Set the **TTL** and **max size**. Don't cache answers that depend on live data or on who's asking.

## Output Parser

Attach after an LLM node when another system needs structured output.

| Type | Gives |
|---|---|
| JSON | A JSON object |
| Pydantic | JSON validated against your JSON Schema |
| Regex | Named capture groups |
| CSV | Rows |
| DateTime | Natural language → ISO-8601 |
| Enum | One of the allowed values you list |

Tell the model the format in its system prompt too; the parser checks it, it doesn't create it.

## Pipelines inside pipelines

The **Pipelines** sidebar section lists published pipelines. Drop one on the canvas to run it as a
step, or use it as a Child Agent. Build small, tested pipelines ("classify ticket", "summarise
lease") and compose them. Each has its own versions and evals.

## Debugging a run

Stop a run partway, look at what a node is about to get, change it, and test the nodes after it
without paying for the ones before. LLM, Tool, Toolkit, Retriever and Child agent nodes have two
buttons in their header, next to ✕ (hover the node to see them): **●** toggles a breakpoint and
**📌** pins an output. Once set, they stay visible on the node. The same controls are in the
**🐞 Debug** strip at the top of the node's config.

- **Pause here** (a breakpoint, ● on the node): Prompt Runner runs stop before this node's next step
  — each model call of an LLM node, each call of a tool, the retrieval. The runner shows what the
  step is about to use (the messages, the tool input, the search query) and you can edit it, then:
  - **▶ Continue** runs to the next breakpoint,
  - **⤵ Step** pauses again before the very next step, whatever node it is,
  - **■ Stop** ends the run.

  Steps before the pause are replayed from the run's checkpoint, so continuing never pays for a
  model call twice. The trace marks steps that ran with an edited input.
- **Pin an output** (📌 on the node): runs use it instead of running the node — no model call, no
  tool call, no search, no cost — so you can work on the nodes after it. Pin from a finished run
  with **📌 Pin** on a tool result or a child agent's output, **📌 Pin answer** under the LLM's
  answer, or type one in the Debug section. **Unpin** to run the node again. A pinned answer still
  goes through the output parser and response guardrails, and isn't written to memory or the cache.

Breakpoints and pins only affect runs from the Prompt Runner. Published runs (API, chat links,
schedules, webhooks, batches) ignore them, even though they're saved with the pipeline.

## Drafts, versions and publishing

- **Save** stores the draft. **Publish** freezes it as the next version.
- Only published versions run from `/v1`, schedules, webhooks, chat links, MCP and other pipelines.
- Editing a published app makes a new draft; callers keep using the live version until you publish.
- Version history and generated docs are in the right panel (**Details**, **Docs**).
- An app can require an eval to pass before publishing → [Evaluate](08-evaluate.md#eval-gated-publishing).

## AI-assisted building

- **✨ Describe:** the box in Build scaffolds a pipeline, a custom tool or an MCP server from a
  sentence. It uses only loaders and tools that actually work. Check and adjust before publishing.
- **Import code:** paste LangChain, CrewAI, AutoGen or plain Python; you get a blueprint to review.
- **Export:** turn a pipeline into LangChain, CrewAI or AutoGen code, a notebook, Docker Compose or
  an OpenAPI spec → [Share](10-share-integrate.md#export).
