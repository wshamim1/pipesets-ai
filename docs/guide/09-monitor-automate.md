# 9. Monitor and automate

## Monitor

Open **Monitor**. Every run (from the editor, `/v1`, schedules, webhooks, chat links or MCP) shows
up here.

| Tab | Shows | Use it to |
|---|---|---|
| **Metrics** | Runs, failures, median latency, model spend; breakdowns by model and by tool | Spot a pipeline getting slower, failing more or costing more |
| **Runs** | Every run with status, source, duration and cost | Find a specific run; resume a failed or interrupted one |
| **Traces** | Each run step by step: prompts, model answers, tool calls with arguments and results, tokens, cost, latency | Work out *why* an answer was wrong. Re-run from a step after fixing something. |
| **Logs** | Server-side log lines across pipelines | Errors that happen outside a model call |
| **Costs & budgets** | Spend per pipeline, model and period; **Spend Budgets** | Set and watch budgets ([Guardrails and budgets](07-guardrails-budgets.md#budgets)) |
| **Sessions** | The Memory Inspector: **Conversations**, **Long-term** memory facts, and the key-value **Store** | See what a pipeline remembers about a conversation or user; delete or forget it |

Debugging a wrong answer:

1. Find the run in **Traces**.
2. Check retrieval first (which sources came back), then tool calls (arguments and results), then
   the model's final prompt.
3. Fix the prompt, tool or data, then turn the case into an eval case (**Evaluate → ⚡ From traces**)
   so it stays fixed.

Traces can also be mirrored to **Langfuse** (`LANGFUSE_*` variables). `LANGFUSE_REDACT=1` sends only
model, tokens, cost and latency, without the text.

## Automate

Open **Automation**. Everything here runs **published** pipelines only.

### Schedules

Run a pipeline on a timetable, e.g. a nightly rent roll check or a Monday report.

1. **Schedules → new.** Pick the **Pipeline** and write the **Prompt** it runs with.
2. Pick when: **Every hour**, **Every day**, **Weekdays**, **Every week**, or **Custom (cron)**. Set
   the **Timezone**.
3. Save. Each schedule lists its runs and outputs, with a link to the trace.

- A schedule can't run more often than the server allows (`SCHEDULER_MIN_INTERVAL_SECONDS`, default
  5 minutes).
- Failed runs are retried. After repeated failures the schedule **auto-pauses** and sends an alert.
- Runs refused by a guardrail or budget, or rejected at a Human Gate, aren't retried.

### Webhooks

Let another system start a pipeline: a form submission, a GitHub push, a new file in storage.

1. **Webhooks → new**, pick the **Pipeline**, and write the **Prompt** template:

   ```text
   {{body}}                    the whole payload (pretty-printed JSON)
   {{body.ticket.subject}}     one field
   {{body.items.0.name}}       a list item
   {{query.repo}}              a query-string parameter
   ```

2. **Copy the URL now.** It's shown once (`/v1/hooks/<token>`). Anyone with it can start the pipeline.
3. Optional but recommended: a **Signing secret**. Then every call must send
   `sha256=<HMAC-SHA256 of the raw body>` in `X-Hub-Signature-256` (GitHub does this) or
   `X-Pipesets-Signature`.
4. Use **Sample payload** to preview the prompt a payload produces.

Calls return `202` at once and the run happens in the background, with retries. Each webhook lists
its calls, payloads and outputs. **New URL** replaces a leaked token. There are limits on calls in
flight (extra ones get `429`) and body size.

### Batches

Run a published pipeline once per row of a file: a list of leases, a set of support questions.

1. **Batches → + New batch**, pick the **Pipeline**, and upload the **Rows**: CSV / TSV, JSONL, a
   JSON array, Excel, or a `.txt` with one prompt per line (up to 5,000 rows).
2. Write the **Prompt** with `{column}` placeholders, e.g. `Abstract the lease for {tenant}, unit {unit}`.
   The first row's prompt is shown as you type. A column called `prompt` is used as-is.
3. **Rows at once** (1–10) is how many rows of this batch run at the same time, so schedules and
   webhooks keep their turn. **Retries** is per row.

**Documents instead of a table:** pick **Run over → Documents** and choose the files: PDFs (scanned
pages are OCR'd), images, emails, Word, Excel or text, up to 500 files of 50 MB each. Each file is one
run. The prompt can use `{document}` (the file's text, read when its run starts and cut at 100,000
characters), `{filename}` and `{path}`. **Read with** picks the loader by file type, or Docling for
PDFs and scans. For a Structured Extract pipeline the prompt starts as `{path}`: the tool loads the
file itself, and its fields go to Evaluate → Review under the batch's name. A file that can't be read
fails its row without a run. Uploaded files are kept with the batch and deleted with it.

Each row is a background run with retries; a row whose placeholders are all empty fails without a
run. The batch shows progress, cost and each row's output or error, and the run id to find its
trace. **Cancel** stops the rows not finished yet, **Retry failed** runs failed and cancelled rows
again, **⬇ CSV** downloads every row's input columns with its output, status, cost and run id.

### Alerts

Hear about problems in Slack or any system that takes a JSON POST.

1. **Alerts → new channel.** **Send to:** Slack (incoming webhook URL) or any URL (JSON POST).
2. **Events:** Run failed, Waiting for approval (a Human Gate paused a run), Review escalated, Schedule
   auto-paused.
3. **Pipelines:** every pipeline in the project, or chosen ones.
4. **Send test.**

Alerts are best-effort and not retried; there's no email channel yet.

### Jobs

The background queue behind schedules, webhooks, alerts and long tasks like optimizations. **Jobs**
lists failed jobs with their attempts and last error. **Retry** or **Discard** them.
