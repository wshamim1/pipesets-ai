# Pipesets AI — User Guide

How to build, test, run and share LLM pipelines in Pipesets. Each guide is task-based: what a
feature is for, how to set it up in the UI, and what to watch out for. For environment variables,
deployment and API reference, see the main [README](../../README.md) and
[DEPLOYMENT.md](../../DEPLOYMENT.md).

| # | Guide | Covers |
|---|---|---|
| 1 | [Getting started](01-getting-started.md) | Sign in, the screens, provider keys, your first pipeline from build to publish |
| 2 | [Building pipelines](02-building-pipelines.md) | The canvas, every node type, wiring rules, the LLM node, flow control, memory, cache, output parsers, versions, AI-assisted building |
| 3 | [Tools](03-tools.md) | Built-in tools, installing more (Tools & MCP packages), Databricks and Snowflake, connections, secrets, toolkits, custom Python tools (UI and SDK) |
| 4 | [MCP servers](04-mcp.md) | Built-in MCP servers, adding your own (stdio / HTTP / SSE), OAuth, using Pipesets as an MCP server |
| 5 | [Agents, workflows and skills](05-agents-workflows-skills.md) | Master and Child agents, external agents, sub-pipelines, Human Gate, conversational workflows, skills |
| 6 | [Knowledge (RAG)](06-knowledge-rag.md) | Loaders, splitters, embeddings, vector stores, retrievers, rerankers, knowledge bases |
| 7 | [Guardrails and budgets](07-guardrails-budgets.md) | Middleware (grounding, moderation, injection, patterns, cost, rate limits), budgets |
| 8 | [Evaluate](08-evaluate.md) | Datasets, scorers, eval runs, history, Optimize models, eval-gated publishing, review queue |
| 9 | [Monitor and automate](09-monitor-automate.md) | Runs, traces, logs, costs, sessions · schedules, webhooks, alerts, jobs |
| 10 | [Share and integrate](10-share-integrate.md) | `/v1` API and keys, SDK and CLI, chat links, MCP server, export, Marketplace |
| 11 | [Settings and admin](11-settings-admin.md) | Members, workspaces, roles and ACLs, tool & MCP packages, provider keys, model backends, secrets, audit log, database, Lab |
| 12 | [Document extraction](12-document-extraction.md) | OCR, document loaders, Structured Extract, the review queue |

## Core ideas in one minute

- **Workspace (tenant) and project.** Everything you make belongs to a project in a workspace.
  Switch them at the top of the screen.
- **App.** A canvas flow you build. It starts as a **draft**.
- **Publish.** Freezes the draft as a numbered, unchangeable **version**. Only published versions
  run outside the editor: from `/v1`, schedules, webhooks, chat links, MCP and other pipelines.
  Editing a published app makes a new draft. The live version keeps running until you publish again.
- **Pipeline.** A published app run as a unit. Pipelines can call other pipelines.
- **Nodes.** Building blocks on the canvas: models, tools, memory, retrieval, guardrails, agents,
  flow control. Nodes affect each other through the **edges** you draw between them.
- **Secrets and connections.** Keys and database credentials are saved once, encrypted, and picked
  by name in nodes. A pipeline can't be saved with a key typed into a node.
