# 6. Knowledge (RAG)

RAG (retrieval-augmented generation) lets a model answer from your documents. Documents are split
into chunks, turned into vectors (embeddings) and stored. At question time the closest chunks are
found and given to the model, with their sources.

Two ways to set it up:

- **Knowledge Base:** the quick way. One node, documents added from a dialog.
- **The full chain:** Doc Loader → Text Splitter → Embedding → Vector Store → Retriever
  (→ Reranker) → LLM. More control, and it can load from folders, S3, URLs and databases.

## Quick: a Knowledge Base

1. **Knowledge (RAG) → + Create Knowledge Base (PDF, Text, URL).**
2. Name it and add content: paste text, upload a file (PDF, TXT, MD) or give a URL. Choose the
   embedding **Model**, **Chunk Size** and **Overlap** (defaults are fine to start).
3. Drag the knowledge base onto the canvas and connect it to the LLM node.
4. In the node, set **Top-K Passages** (how many chunks the model gets; 4–6 is typical) and
   **Score Threshold** (drop weak matches). Use **Test Semantic Query** to see what a question finds.

## Full chain

| Node | Choose | Advice |
|---|---|---|
| **Doc Loader** | Where documents come from: file upload, path, folder, S3, web page, sitemap, RSS, Wikipedia, arXiv, Postgres / MySQL / SQLite, email, Yardi export, images (OCR)… | Database loaders need a Connection node linked to them. Loaders shown as "Soon" can't run yet. Scanned PDFs: see [Document extraction](12-document-extraction.md#2-ocr-for-scanned-pages). |
| **Text Splitter** | Recursive, Token, Markdown, Semantic, Sentence, HTML; chunk size and overlap | Recursive with 500–1,000 characters and 10–20% overlap is a good default. Markdown for docs with headings. |
| **Embedding** | OpenAI, Cohere, Google, Mistral, Voyage, Nomic, Ollama, llama.cpp, Bedrock, Azure OpenAI, or local sentence-transformers | Use the **same embedding model** for indexing and for the Retriever. Local runs offline. |
| **Vector Store** | **Local** or **pgvector** | Local is in the app database: fine for a few thousand chunks. pgvector for production. Other store types in the list currently fall back to Local. |
| **Retriever** | Similarity or MMR; collection; top-K; score threshold | MMR gives more varied passages when documents repeat themselves |
| **Reranker** | A cross-encoder that reorders the retrieved passages | Improves the order of the top results; costs a little latency |

### Index the documents

Fill in the Doc Loader's source, give the Vector Store a **collection name**, and run. Pipesets
loads, splits, embeds and stores the documents. Re-running clears the collection first, so
changing the embedding model takes effect. The Retriever must use the same collection name.

### Ask

Connect the Retriever (or Knowledge Base) to the LLM node. Answers stream with **Retrieved
Sources**: the chunks used and where they came from (file, page). In the system prompt, tell the
model to answer only from the sources and to say when they don't cover the question.

## Getting good answers

- **Check what's retrieved before tuning the prompt.** The Knowledge Base test box and the sources
  list show whether the right passages come back.
- **Too little context:** raise top-K or chunk size. **Off-topic passages:** raise the score
  threshold, or add a reranker.
- **Tables and scanned PDFs:** load with the Docling loader or enable OCR, or the text arrives
  garbled or empty.
- **Hallucinations:** add a **Grounding Check** guardrail ([Guardrails](07-guardrails-budgets.md)).
- **Measure it:** build an eval dataset of real questions and expected answers
  ([Evaluate](08-evaluate.md)).

For pulling specific fields out of documents (dates, amounts, names) rather than answering
questions, use **Structured Extract**: see [Document extraction](12-document-extraction.md).
