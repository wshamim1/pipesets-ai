# Document Extraction — How to Use

This guide explains how to turn leases, licenses, rent rolls and emails into fields you can check
and rely on. Every field comes with the page and the exact quote it was read from, and a person
approves it before anything depends on it.

It covers:

1. [How the pieces fit](#1-how-the-pieces-fit)
2. [OCR for scanned pages](#2-ocr-for-scanned-pages)
3. [Loaders](#3-loaders): PDF, Image (OCR), Docling, Email, Yardi Report Export
4. [Structured Extract tool](#4-structured-extract-tool)
5. [Review queue](#5-review-queue)
6. [Walkthrough: abstract a lease from start to finish](#6-walkthrough-abstract-a-lease-from-start-to-finish)
7. [Troubleshooting](#7-troubleshooting)

Status: first version, 2026-11-02. Tesseract OCR is checked on real scans. Vision OCR and
Structured Extract are only tested with stubbed models so far. OCRmyPDF hasn't run yet. See
[plan.md](../../plan.md) (P1) for what's open.

---

## 1. How the pieces fit

```
 Document ──► Loader ──► pages (text + page numbers) ──► Structured Extract ──► Review queue ──► Eval dataset
              │                                          (model reads fields,    (a person approves,
              └─ OCR for scanned pages                    quotes are checked)     corrects or rejects)
```

| Piece | Where | Use it to |
|---|---|---|
| OCR engines | Setting on the PDF, Image, Directory, S3 and Email loaders | Read pages that are images, not text |
| Loaders | Doc Loader node, or the `loader` setting of Structured Extract | Turn a file into pages with page numbers |
| Structured Extract | Tool node (Tools → Data & Files) | Pull named fields out of a document, with citations |
| Review queue | Evaluate → 🧾 Review | Check each field before it's used |
| Export to eval | Review queue → Export | Turn reviewed documents into test cases |

All paths refer to the **backend server's** filesystem: the uploads folder, a mounted share, or a
folder the server can read. A file on your laptop has to be uploaded first. Use the Doc Loader
node's upload box, then copy the **Resolved Path** it shows.

---

## 2. OCR for scanned pages

A scanned PDF has pictures of pages, not text. OCR reads the text from those pictures. Pipesets
only runs OCR on pages that have no text layer. Typed pages are read directly and stay exactly as
they are.

### Choosing an engine

| Engine | Runs | Best for | Needs |
|---|---|---|---|
| `auto` (default) | Locally | Uses the first installed: OCRmyPDF, then Tesseract, then Docling | One of them installed |
| `tesseract` | Locally | Clean typed scans; fast and free | The `tesseract` program (in the Docker image) |
| `ocrmypdf` | Locally | Crooked or rotated scans in PDFs | `ocrmypdf`, `tesseract` and `gs` (Ghostscript) |
| `docling` | Locally | Tables (rent schedules, exhibits) | The `docling` Python package and torch. Not in the desktop app. |
| `vision` | Cloud | Bad scans, stamps, handwriting, complex tables | A vision model and its provider key. Billed per page. |
| `off` | — | Text PDFs only; skips OCR | — |

`auto` never picks `vision`: it costs money and sends page images to the model's provider. Choose
it on purpose, and only for documents you're allowed to send to that provider.

### Settings

| Setting | Default | Meaning |
|---|---|---|
| `ocr_engine` | `auto` | One of the engines above |
| `ocr_language` | `eng` | Tesseract language codes; combine with `+`, e.g. `eng+spa` |
| `ocr_dpi` | `300` | Resolution pages are rendered at (72–600). Higher is slower but better on small print. |
| `ocr_max_pages` | 200 (vision: 50) | Most scanned pages one document may OCR, so a large file can't run up time or cost |
| `ocr_provider`, `ocr_model` | — | Vision only, e.g. `openai` / `gpt-4o-mini`, or `anthropic` and a Claude model |
| `ocr_api_key`, `ocr_base_url` | — | Vision only. Leave the key empty to use the project's key from **Settings**. |

Vision works with OpenAI-compatible, Anthropic and Ollama models. Gemini and Bedrock don't accept
images through the gateway yet.

### In the UI

On a **Doc Loader** node with the PDF, Image, Directory, S3 or Email loader, the **Scanned pages
(OCR)** section has the engine, language and (for vision) provider and model. On **Structured
Extract** it's the **OCR for scanned pages** setting. There, vision uses the tool's own model unless
you set `ocr_provider` / `ocr_model`.

### What you get back

Each OCR'd page is tagged `parser: ocr:<engine>`, so you can tell which pages came from OCR. If
OCR can't read some pages, the document still loads. Every page carries `pages_without_text`
(e.g. `"2, 7"`) and `ocr_error` with the reason. **Check these before trusting a document:** a lease
missing its rent exhibit page looks complete otherwise.

---

## 3. Loaders

A loader turns a file into a list of documents (usually one per page), each with text and metadata
such as `source` and `page`. Use them in a **Doc Loader** node (to index for RAG) or via the `loader`
setting of Structured Extract.

### PDF

- **Use for:** any PDF: typed, scanned, or mixed.
- **Source:** path to a `.pdf`.
- **Gives:** one document per page with `page` and `pages`. Scanned pages go through OCR (section 2).
- **Settings:** the OCR settings, plus `password` for protected PDFs.

### Image (OCR)

- **Use for:** scans saved as pictures: `.png`, `.jpg`, `.tif`/`.tiff`, `.bmp`, `.webp`.
- **Source:** path to the image.
- **Gives:** one document (`page: 1`).
- **Settings:** the OCR settings. `ocrmypdf` reads PDFs only, so `auto` uses Tesseract or Docling here.
  For a multi-page TIFF only the first page is read; convert it to PDF instead.

### Docling (OCR + tables)

- **Use for:** documents where layout and tables matter: PDFs with rent schedules, DOCX, PPTX,
  XLSX, HTML, images.
- **Source:** path to the file.
- **Gives:** one document per page, as Markdown (tables kept as Markdown tables), tagged
  `parser: docling`.
- **Settings:** `ocr` (default on), `tables` (default on).
- **Note:** heavier and slower than the PDF loader. The PDF loader stays the default for folders and S3.

### Email (EML/MSG)

- **Use for:** documents that only exist in inboxes: renewed licenses, operator financials sent by email.
- **Source:** path to a saved `.eml` file (Outlook: *Save As* → `.eml`, or drag the message to a
  folder). `.msg` needs the optional `extract-msg` package.
- **Gives:**
  - first, the message itself: From, To, Cc, Date, Subject and body (HTML bodies converted to text);
  - then every attachment a loader can read (PDF pages, Word, Excel sheets, CSV, images…). Each one
    is tagged `attachment: <file name>` and `source: <the email>`.
- **Settings:** `attachments` (default on). Attachments nothing can read are listed in
  `skipped_attachments` on the message document. Scanned PDF attachments use the OCR settings.
- **Folders:** the Directory and S3 loaders pick up `.eml` / `.msg`, so a folder of exported emails
  works too. Reading straight from a mailbox (IMAP / Microsoft 365) isn't built yet.

### Yardi Report Export

- **Use for:** rent roll, lease expiration and tenancy schedule reports **exported from Yardi** as
  CSV or Excel (`.xlsx`). Old `.xls`: re-export as `.xlsx` or CSV.
- **Source:** path to the export.
- **Gives:** one document per tenant row. The text has every column. The metadata uses standard names
  so later steps don't depend on how Yardi labels a column:

  | Field | Matched from columns like |
  |---|---|
  | `property` | Property, Property Code, Building, or the group heading above the rows |
  | `unit` | Unit, Suite, Space |
  | `tenant`, `tenant_code` | Tenant, Lease, Resident · Tenant Code, Lease Code |
  | `lease_from`, `lease_to` | Lease From / To, Start / End Date, Commencement, Expiration |
  | `monthly_rent`, `annual_rent`, `rent_per_sqft` | Monthly Rent, Rent, Base Rent · Annual Rent · Rent PSF |
  | `sqft`, `beds`, `status`, `lease_type`, `term_months`, `security_deposit`, `balance` | the obvious ones |

- **How it reads the report:**
  - skips the title lines at the top and finds the header row (the first row naming at least three
    known columns);
  - remembers the property from heading rows that have only their first cell filled;
  - skips blank rows, `Total` / `Grand Total` rows and repeated headers. Excel dates become
    `YYYY-MM-DD`.
- **Settings:** `header_row` (1-based) if the header isn't found automatically; `max_rows` (10,000).
- **Note:** built from common Yardi layouts. Check the first few documents against the report the
  first time you load a new report type.

---

## 4. Structured Extract tool

Reads a document and returns the fields you list. Each field comes with its value, page, exact
quote and confidence. Then it checks each quote is really on that page.

### Set it up

1. In **Build**, add an **LLM** node and a **Tool** node, and connect them.
2. On the Tool node pick **Structured Extract** (Tools → Data & Files).
3. Fill in the settings:

| Setting | Default | What to put |
|---|---|---|
| Read the document with (`loader`) | `pdf` | `pdf`, `docling`, `docx`, `email`, `yardi_export`, `image`, `excel`, `text` |
| OCR for scanned pages (`ocr_engine`) | `auto` | See section 2 |
| `fields` | A lease example | One per line, `name: what to look for`. Or JSON: `[{"name": "rent", "description": "...", "type": "money"}]` |
| `instructions` | — | Extra rules, e.g. "Rent is the first-year amount; ignore later escalations" |
| `provider`, `model` | `openai`, `gpt-4o-mini` | The model that reads the document |
| `api_key` | — | Leave empty to use the project key from Settings. Pick a stored secret rather than typing one. |
| Review (`review`) | Send to queue | **Send every field to the review queue**, or **Return only** |
| `batch` | — | A name to group a set of documents in the queue, e.g. `maple-grove-2026-q4` |
| `max_chars` | 150,000 | Most text sent in one model call (about 40k tokens). Longer documents are split into parts |

### Writing good fields

- **Name a field in one or two words; describe it in a sentence.** The name becomes the key
  (`Monthly Base Rent` → `monthly_base_rent`). The description is what the model looks for.
- **Set `type`** (JSON form) to `date`, `money`, `number` or `boolean`. Dates come back `YYYY-MM-DD`,
  money as a plain number. In the review queue, corrections to number fields stay numbers.
- **One fact per field.** Split "term and renewal options" into `lease_end` and `renewal_options`.
- **Say which one when there are several:** "base rent in the *first* lease year", "the *guarantor*,
  not the tenant".
- Up to 60 fields per run.

Example for a healthcare lease:

```text
tenant_entity: Legal name of the tenant / operator
lease_start: Lease commencement date
lease_end: Lease expiration date
monthly_base_rent: Monthly base rent in the first lease year
annual_escalation: Annual rent increase (percent or fixed amount)
guarantor: Who guarantees the lease, if anyone
license_requirement: What license the tenant must keep, and the clause that says so
licensed_beds: Number of licensed beds at the facility
renewal_options: Number and length of renewal options
```

### Run it

Give the LLM node a system prompt like:

> When the user gives a file path, call Structured Extract with it as `source` and reply with the
> tool's JSON unchanged.

Then send the path (e.g. `/data/uploads/ab12cd_maple_grove_lease.pdf`) in the Run panel, through
`/v1`, from a schedule or from a webhook.

**Many documents at once:** publish the pipeline, then **Automation → Batches → + New batch →
Documents**. Pick the files (PDFs, scans, emails, Word, …), keep the prompt `{path}` and run. Each file
is one run, and every field lands in the review queue under the batch's name (unless the tool sets
its own **Batch**), so **Accuracy** reports on the whole set. See
[Monitor and automate → Batches](09-monitor-automate.md#batches).

### What it returns

```json
{
  "source": "/data/uploads/ab12cd_maple_grove_lease.pdf",
  "fields": [
    {"name": "lease_end", "value": "2034-12-31", "page": 2, "page_label": null,
     "quote": "expires on December 31, 2034", "verified": true, "confidence": 0.95, "...": "..."},
    {"name": "guarantor", "value": null, "page": null, "quote": null, "verified": false, "confidence": 0.0}
  ],
  "parts": 1,
  "prompt_version": "pv_3f9c0a71be",
  "unverified": [],
  "not_found": ["guarantor"],
  "conflicts": [],
  "review": {"queued": 2, "where": "Evaluate → Review queue"}
}
```

- **`verified`:** the quote was found on the cited page, ignoring spacing, case and punctuation
  (90% match allowed for OCR noise). If the quote is on a different page, the citation is moved there.
- **`confidence`:** the model's own estimate (0–1). Capped at **0.3** when the quote couldn't be
  found, and **0** when the field wasn't found.
- **`page_label`:** for emails and reports, where the text came from, e.g. `license.pdf p.1` or
  `row 14`.
- **`unverified` / `not_found`:** the fields to look at first.
- **`prompt_version`:** an id for the system prompt, field list and instructions together. It
  changes when any of them changes, so the accuracy report can compare prompts.

### Long documents

A document up to `max_chars` is read in one model call. A longer one (a lease with exhibits and
amendments) is split into **parts** of at most `max_chars`, always at a page boundary. Once a part
is two-thirds full, the next part starts at a page that opens an article, section, exhibit,
schedule, addendum, amendment or rider, so a section isn't split across two calls. A single page
longer than `max_chars` is cut at paragraph breaks and keeps its page number. Up to 3 parts run at
once; a document that needs more than 20 parts is refused.

The parts' answers are merged per field:

- the value with a **verified** quote wins over an unverified one, then the higher confidence,
  then the earlier page;
- different values found by other parts are kept as **`alternatives`** (value, page, quote,
  verified, confidence);
- when an alternative also has a verified quote (e.g. an amendment changes the rent), the field
  gets **`conflict: true`**, its confidence is capped at **0.5**, and it's listed in `conflicts`. A
  person has to pick: bulk approval skips it.

Each part costs one model call, so a document in 4 parts costs about 4 times as much as one call.
If any part fails, the whole extraction fails and the message names the part.

---

## 5. Review queue

Where people check extracted fields. Open **Evaluate → 🧾 Review**.

### Reading the screen

- **Tabs:** To review, Approved, Corrected, Rejected, each with a count. **Batch** filters to one batch.
- **Grouping:** fields are grouped by document. Within a document the weakest come first: not
  found, then quote not found, then low confidence.
- **Each field shows:**
  - the value;
  - a badge: **✓ quote found** (green), **quote not found** (amber: open the document and check) or
    **not found**;
  - the confidence;
  - the quote, with its page;
  - **parts disagree** (amber) when another part of a long document found a different value with a
    found quote, and **bulk** on fields approved in bulk;
  - under **Other parts of the document found**, each alternative value with its page and quote.
- **📄 Page** opens the cited page's text with the quote highlighted, as the model read it (after
  OCR). **📄 Page N** on an alternative opens that page. Pages are saved when the field is filed, so
  the document isn't loaded or OCR'd again. Fields filed before 2026-11-02 have no saved page.

### Deciding

| Button | Use when | Result |
|---|---|---|
| **Approve** | The value matches the document | `approved`; the value is kept |
| **Correct** | The value is wrong or missing | Type the right value → `corrected`. "$185,000.00" in a money field is saved as `185000`. |
| **Reject** | The field doesn't apply to this document | `rejected`; no value |
| **Use this value** (on an alternative) | Another part has the right value | `corrected` with that value |

### Bulk approve

On **To review**, set a threshold (50–100%, default 90) and click **Approve N fields**. It approves
pending fields that have **all** of these:

- a value (not "not found");
- a quote found on the cited page;
- confidence at or above the threshold;
- no "parts disagree".

N is counted for the current batch before you click. Each field approved this way gets the note
"Bulk approved: …" and the **bulk** badge. The bulk action is written to the audit log
(`review.bulk_approve`). Deciding a field again by hand clears **bulk**.

Start with a high threshold. Check the accuracy report on fields you reviewed one by one before
lowering it.

### Accuracy report

**Accuracy** in the toolbar shows, for each model and prompt version, and for each field:

- **Right:** approved, or rejected when the model said "not found";
- **Wrong:** corrected, or rejected when the model gave a value;
- **Accuracy:** right ÷ (right + wrong);
- **Bulk** and **To review:** counted but not scored. A bulk approval isn't a check of the model.

Use it to measure a prompt or model change: run the same documents in a new batch with the new
prompt, review, and compare the two prompt versions. **Batch** filters the report too.

- You can change a decision later; the last one counts. Each decision records who made it and when.
- Decisions, bulk approvals and exports are written to the **audit log** (`review.decide`,
  `review.bulk_approve`, `review.export`).
- Running a document again in the same batch replaces its **pending** fields and keeps the ones
  already decided.

### Export to an eval dataset

At the bottom of the queue, name a dataset and click **Export**. Each **fully reviewed** document
becomes one eval case:

- **input:** the document path;
- **expected output:** the reviewed fields as JSON;
- **tags:** `extraction-review`, plus `corrected` if anything was corrected.

Documents with fields still pending are skipped. Exporting again only adds new documents.

Use the dataset to test a changed prompt, field list or model before publishing. Use the **LLM
judge** scorer: the pipeline's output also has pages and quotes, so an exact match won't pass.
**Evaluate → Optimize** can then find the cheapest model that keeps the pass rate.

> Eval datasets aren't scoped to a workspace yet. Don't export confidential documents on a server
> shared with other organisations.

Through the API (signed in, same project headers as the UI):

| Call | Does |
|---|---|
| `GET /api/reviews?status=pending&batch=…&source=…` | List reviews and counts per status |
| `GET /api/reviews/{id}` | One review |
| `GET /api/reviews/{id}/page` (optional `?page=N` for an alternative's page) | The cited page's text |
| `GET /api/reviews/bulk-approve?min_confidence=0.9&batch=…` | How many fields bulk approval would approve |
| `POST /api/reviews/bulk-approve` `{"min_confidence": 0.9, "batch": "…", "source": "…"}` | Bulk approve |
| `GET /api/reviews/report?batch=…` | Accuracy per model, prompt version and field |
| `POST /api/reviews/{id}/decision` `{"decision": "correct", "value": 185000, "note": "…"}` | Approve, correct or reject |
| `POST /api/reviews/export` `{"dataset_name": "…"}` or `{"dataset_id": "…"}`, optional `batch` | Export reviewed documents |

---

## 6. Walkthrough: abstract a lease from start to finish

1. **Upload.** Add a Doc Loader node, drop the lease PDF on it and copy the **Resolved Path**.
2. **Build.** Add an LLM node (system prompt from [section 4](#run-it)) and a Structured Extract
   tool connected to it:
   - `loader`: `pdf`;
   - `ocr_engine`: `auto`, or `vision` for a poor scan;
   - `fields`: the lease example;
   - `batch`: `pilot-leases`.
3. **Run.** Paste the path in the Run panel. Look at `unverified` and `not_found` in the answer.
4. **Review.** Open Evaluate → 🧾 Review, filter on `pilot-leases`. Approve the ones that match,
   correct the rest. For amber "quote not found" fields, open the PDF at the cited page.
5. **Repeat for 20–30 leases.** Publish the pipeline and run each lease through `/v1` or a schedule.
6. **Measure.** Count approved vs corrected per field. Fields often corrected need a better
   description or `instructions`.
7. **Lock it in.** Export to a dataset (e.g. "Lease abstraction — pilot"). Turn on eval-gated
   publishing for the pipeline, so a prompt or model change that gets reviewed leases wrong can't
   ship.

For rent rolls use `loader: yardi_export`. For a license renewal sent by email use `loader: email`;
the license PDF attachment is read with its page numbers.

---

## 7. Troubleshooting

| Message or symptom | Cause | Fix |
|---|---|---|
| "No OCR engine is installed on this server" | No Tesseract, OCRmyPDF or Docling | Install Tesseract (`brew install tesseract`, `apt install tesseract-ocr`; already in the Docker image) or pick `vision` |
| "Docling isn't installed on this server" | Desktop app, or a broken torch/NumPy install | Use `tesseract` or `vision`. On an Intel Mac dev setup, reinstall with `python -m pip install -r requirements.txt` (pins NumPy 1.x and transformers 4.x there) |
| "Vision OCR needs a model" | `vision` without `ocr_provider` / `ocr_model` | Set them (Structured Extract uses its own model) |
| "… scanned pages; OCR is limited to N" | Larger than `ocr_max_pages` | Raise `ocr_max_pages` |
| `pages_without_text` on the documents | OCR couldn't read those pages | Read `ocr_error`; try another engine or a higher `ocr_dpi` |
| "Couldn't find the header row" (Yardi) | Unknown column names | Set `header_row` to the header's row number |
| "has no tenant rows under its header" (Yardi) | Wrong header row, or no Unit / Tenant column | Check `header_row`; the report needs a Unit, Tenant or Tenant Code column |
| "Reading Outlook .msg files needs the extract-msg package" | `.msg` without the package | Save the message as `.eml`, or install `extract-msg` |
| "The document needs N parts of … characters; the limit is 20" | Very long document | Raise `max_chars` (if the model's context allows) or split the document |
| "… failed (part 2 of 3): …" | One part's model call failed | Run it again; every part is needed |
| "The model didn't answer with the expected JSON" | The model wrapped or cut its answer | Use a stronger model, or fewer fields per run |
| Many "quote not found" on a scanned lease | OCR errors, or the model paraphrased | Try `ocr_engine: vision` or `docling`; fix values in review |
| Export says "No reviewed documents to export yet" | Every document still has pending fields | Finish reviewing, or export with `only_complete: false` through the API |
