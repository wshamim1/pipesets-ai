# 1. Getting started

## Sign in

Open the UI (locally http://localhost:5173 after `./start.sh`). On a fresh server:

- **Sign up** from the login screen (on by default), or
- give a seeded user a password: `cd backend && .venv/bin/python manage.py set-password admin@demo.local`.

The first start creates a **Demo Tenant** with a few projects to try things in.

## The screens

The top bar has seven areas:

| Area | Use it to |
|---|---|
| **Apps** | See every app in the project: published, drafts, the one open in the builder. Create a new app. |
| **Build** | The canvas: drag nodes, wire them, configure, run, publish |
| **Evaluate** | Test pipelines against datasets, compare runs, find cheaper models, review extracted fields |
| **Monitor** | Metrics, runs, traces, logs, costs and budgets, memory sessions |
| **Automation** | Schedules, webhooks, alerts, background jobs |
| **Marketplace** | Share pipelines as listings, try and import others' |
| **Lab** | One-click test databases and local model servers |

**Settings** (members, keys, secrets, model backends, audit log…) is the ⚙ gear in the top bar.
In **Build**, the right-hand panel has **Run**, **Details**, **Docs** (generated documentation for
the pipeline), **Schedules** and **Webhooks**.

## Add a model key

A pipeline needs a key for its model provider. Pick one way:

1. **Settings → Model provider keys:** a default key per provider for the whole project. Easiest.
2. **Settings → Secrets:** save the key as a named secret, then pick it in a node's **API Key** field.
3. **Server environment:** `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, … in `backend/.env`.

A key on a node beats the project default, which beats the server's. To try things without any
key, use the **Mock** provider.

## Your first pipeline

1. **Apps → + New Application.** Name it, then open it in **Build**.
2. From the sidebar (**Essentials**) drag in **Start**, **LLM** and **Stop**, and connect
   Start → LLM → Stop.
3. Click the LLM node. Under **Model & Provider** pick a provider and model. Under **Instructions**
   write a **System Prompt**, e.g. "You answer questions about our leasing policy in two sentences."
4. Open the run panel, type a question and send it. Answers stream in. The tool calls, tokens and
   cost show as it runs.
5. **Save**, then **Publish**. You now have version 1.
6. Open **Monitor → Traces** to see the run step by step: prompt, answer, tokens, cost, latency.

From here:

- give it tools → [Tools](03-tools.md);
- let it answer from your documents → [Knowledge (RAG)](06-knowledge-rag.md);
- make it a team of agents → [Agents](05-agents-workflows-skills.md);
- call it from your own code → [Share and integrate](10-share-integrate.md).

## Shortcuts

- **Describe it instead:** the ✨ box in Build scaffolds a pipeline, tool or MCP server from a
  sentence, e.g. "a support pipeline with RAG, a reviewer agent and a Slack tool". Review what it
  builds before publishing.
- **Bring existing code:** **Import code** converts LangChain, CrewAI, AutoGen or plain Python into a
  pipeline.
- **Templates:** starter apps (RAG assistant, multi-agent research crew, tool-equipped assistant)
  are offered when you create an app.
