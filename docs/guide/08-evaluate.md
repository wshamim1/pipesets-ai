# 8. Evaluate

Evals tell you whether a pipeline gives the right answers, and whether a change made it better or
worse. Open **Evaluate**. Its tabs are **Datasets**, **Run**, **History**, **Optimize** and
**Review**.

## 1. Build a dataset

A dataset is a list of **cases**: an input prompt and the expected output.

**Datasets → new dataset**, link it to a pipeline (needed for Optimize and generation), then add
cases any of these ways:

| Way | Button | Best for |
|---|---|---|
| By hand | **+ Add case** | The cases you care most about |
| From real runs | **⚡ From traces** | Turning real questions (and fixed answers) into tests |
| Generated | **✨ Generate more / ↻ Regenerate** | Breadth: the pipeline's model drafts cases from its description. Review them; regenerating replaces only AI cases, never manual or trace ones. |
| From a spreadsheet | **⬆ Import** / **⬇ Excel** | Bulk editing with the business team |
| From reviewed extractions | Review tab → Export | Document extraction pipelines ([guide](12-document-extraction.md#5-review-queue)) |

**Synthetic Data** (a node in Build) generates realistic test records (CRM, orders, HR, healthcare…)
and can save them to a dataset too.

Tips: 20–50 good cases beat 500 generated ones. Include the edge cases that have gone wrong before.
Write expected outputs that can be checked: "2034-12-31", not "the lease end date".

## 2. Run it

**Run** tab: choose the dataset, the pipeline (draft or a version) and a **scorer**:

| Scorer | Passes when | Use for |
|---|---|---|
| Contains | The expected text appears in the output | Facts, IDs, short answers |
| Exact | Output equals the expected text exactly | Classifiers, codes, fixed formats |
| LLM Judge | A model scores 0–1 how well the output matches | Free text, summaries, JSON with extra fields. Costs tokens. |

The report shows pass rate, each case's output and score, cost and latency.

## 3. Compare over time

**History** lists every eval run with its pass rate trend. Open two runs to see which cases changed.
Run the same dataset after every prompt, model or tool change.

## 4. Optimize models

**Optimize** finds the cheapest (or fastest) model for each LLM node that keeps the pass rate.

1. Pick a dataset linked to the pipeline, the scorer, and **Optimize for** lowest cost or lowest
   latency.
2. Tick the nodes to try and the candidate models. Models without a key in Settings are skipped.
3. Set **Pass rate it may lose** (tolerance), optionally **Screen on first** N cases to drop weak
   models early, **Max configs** and **Cases at once**.
4. Start. It runs in the background and shows progress. Every option is a real, billed run of the
   dataset.
5. When it's done, **Apply to draft**, check it, and publish. Past optimizations can be reopened,
   **↻ Re-run** or **✎ Edit & re-run**.

Results are only as good as the dataset. With a small one, set a tolerance so one unlucky answer
doesn't reject a good model.

## Eval-gated publishing

Stop a worse version from going live:

1. In Build, open the right panel → **Details → Eval gate → Set up gate**.
2. Choose the **Dataset** and **Scorer**, a minimum pass rate and/or "no regression against the
   previous version" (with a tolerance).
3. **On failure:** block the publish (an admin can override) or publish but flag the version.

Publishing then runs the eval first. Large datasets make publishing slow, so keep the gate dataset
focused.

## Review queue

**Review** holds fields pulled from documents by the Structured Extract tool, waiting for a person
to approve, correct or reject them. See [Document extraction → Review queue](12-document-extraction.md#5-review-queue).

## Feedback

👍 / 👎 from the people who read the answers, so real answers feed your evals.

- **Prompt Runner:** under a finished answer, 👍 or 👎 (click again to take it back). After a 👎,
  **Add note** says what was wrong and what the answer should have said.
- **Chat links:** visitors get 👍 / 👎 under each answer, and a box for what was wrong after a 👎.
  They never see run ids; each answer carries a sealed token only their own chat can use.
- **API:** `POST /v1/runs/{run_id}/feedback` with `{"rating": 1 | -1, "comment", "correction", "user"}`
  (scope `apps:run`). One rating per run per `user`; rating again replaces it.

**Feedback** lists the ratings (👎 first) with each run's prompt, answer and note, and shows
satisfaction (share of 👍) per pipeline and version, so a version that answers worse stands out.
Select ratings and **Export** them to a dataset: the prompt becomes the case input, and the expected
output is the rater's correction, or the answer itself for a 👍. A 👎 without a correction lands
with an empty expected output, tagged `thumbs_down`, for someone to fill in.
