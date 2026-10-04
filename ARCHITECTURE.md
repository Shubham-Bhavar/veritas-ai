# VERITAS AI — Architecture

## Services and responsibilities

```
┌──────────────┐  /api   ┌────────────────────────┐ X-Internal-Token ┌──────────────────────────────┐
│ React (Vite) │ ──────▶ │ Spring Boot API         │ ───────────────▶ │ FastAPI evidence service      │
│ nginx in prod│         │ · JWT auth, ownership   │                  │ · validate / extract / OCR    │
└──────────────┘         │ · upload validation     │                  │ · chunk / facts / embeddings  │
                         │ · async ingestion queue │                  │ · hybrid retrieval + rerank   │
                         │ · answers, claims,      │                  │ · conflict engine             │
                         │   citations, conflicts  │                  │ · criteria + verdict engine   │
                         │ · timeline, rate limits │                  │ · confidence, graph, compare  │
                         └───────────┬────────────┘                  │ · LLM synthesis + verification│
                                     │                               │ · page rendering + highlights │
                              PostgreSQL "veritas"                    └──────────────┬───────────────┘
                              (H2 locally)                              PostgreSQL+pgvector "evidence"
                                                                        (SQLite locally) + file store
```

There are three services because each owns a clear concern:
- **Spring** is the system of record: who may see what, what was uploaded, what was asked and answered, and when.
- **The evidence service** owns everything derived from document content.
- **The browser** never talks to the evidence service, which is not published in the deployment.

## Ingestion pipeline (evidence service)

1. **Validate** (`ingest/validate.py`): magic bytes, DOCX archive structure, UTF-8/CP1252 text, size limit, and the extension must match the content.
2. **Extract** (`ingest/extract.py`)
   - PDF: PyMuPDF `dict` layout with span fonts and colours. Body font size → headings; numbered headings set the depth. Running headers and page numbers repeated across pages are removed. Text-layer quirks are normalised (NBSP, soft hyphens). Label and value blocks on one baseline are rejoined.
   - **Hidden text**: white spans, spans smaller than 2.5 pt, and off-page spans become `hidden` blocks. They are never chunked and always become security flags.
   - Scanned pages (little text, embedded images) are rendered at 2× and OCR'd. OCR lines are re-merged into rows and paragraphs, `Key: Value` lines are kept, and OCR spacing errors are repaired.
   - DOCX: paragraphs with heading styles, list items, tables. Two-column tables become `Label: value` fields.
   - TXT/MD: markdown, numbered and capitalised headings; paragraphs with line numbers.
3. **Metadata** (`ingest/metadata.py`)
   - Title, the issuing authority, and the document date (preferring "Effective/Dated/Submitted on", never "Date of birth"). Reference numbers. Years.
   - Role: *policy*, *record* or *reference*.
   - Subjects (the person a record is about) versus everyone named.
   - Every **supersession** ("supersede…") and **amendment** ("in partial modification of… hereby extended") sentence.
4. **Chunk** (`ingest/chunker.py`): section-aware, ~650 characters, never crossing a page. Each chunk keeps its section path, page, lines and bounding boxes.
5. **Scan** (`ingest/injection.py`): instruction-likeness scoring per sentence.
6. **Facts** (`intel/facts.py`): typed values with comparators, labels, roles and value-masked "attribute text". Flagged sentences are skipped.
7. **Embed** chunks (title + section + text) and facts (section + attribute text). **Store** them.

## Retrieval

`intel/index.py` keeps an in-memory snapshot per collection: the chunk matrix, the fact matrix, and BM25 statistics. It is rebuilt when the collection version changes, or on restart from the store. A query takes these steps:

1. Dense cosine and BM25 over stemmed content terms. The dense ranking comes from a **pgvector `<=>` query** on PostgreSQL, or from the in-memory matrix on SQLite; the two produce identical rankings, which is tested.
2. Reciprocal-rank fusion builds the candidate pool (30).
3. A cross-encoder re-ranks the pool. The final score is 0.6·rerank + 0.25·dense + 0.15·lexical.
4. At most 3 passages per document, then the top 8.

**Relevance** (0–1) is derived from the cross-encoder probability. It drives the insufficient-evidence gate and the confidence score.

## Conflict engine (`intel/conflicts.py`)

1. **Attribute clustering** over requirement and statement facts in *different* documents. Two facts are a candidate pair when:
   - they have the same type and compatible comparators, and
   - their value-masked attribute embeddings have cosine similarity ≥ 0.86 (with some label overlap), or ≥ 0.74 with label Jaccard ≥ 0.5.

   Clustering is agglomerative with two constraints:
   - **complete linkage**: every cross-document pair must match;
   - **cannot-link**: two facts from the same document with different values are never merged. This keeps "renewal: 55% marks" apart from "eligibility: 60% marks".
2. **Supersession map**: a document is superseded when another document's supersession sentence references it. A reference means its reference number, or a matching year plus at least 60% of its title terms.
3. **Amendments**: a fact whose own sentence amends another document overrides that document's value in the cluster.
4. Whatever still disagrees is **UNRESOLVED**. The most recent date is reported but never used to choose.
5. **Statement contradictions**: assertion facts about eligibility, permission or coverage, compared with negation neutralised (cosine ≥ 0.84, term overlap ≥ 0.3), with opposite polarity.
6. **Severity**:
   - HIGH: a threshold requirement (money, %, score or age with ≤, ≥ or a range), or a contradiction about eligibility;
   - MEDIUM: dates and other requirements;
   - LOW: anything resolved.

## Reasoning engine (`intel/investigate.py`)

- **Question analysis**: intent (eligibility, value, yes/no or open), value-type hints, and subject resolution. "This student" with two applicants on file returns a request to name one; the engine does not guess.
- **Eligibility**: each eligibility criterion cluster is evaluated against the subject's facts.
  - Criteria are threshold requirements in eligibility sections, not benefits or renewal.
  - Inactive (superseded or amended) values are excluded, and the reason is quoted.
  - Ages are computed from a date of birth at the rule's "as on" date.
  - The outcome is SUPPORTED, CONTRADICTED, UNCERTAIN (the result depends on a conflict) or INSUFFICIENT (no record).
  - Corroboration comes from every record stating the same value. If the subject's own records disagree, the result is UNCERTAIN.
  - A required-documents checklist is matched against the applicant's documents.
  - Prose conditions are listed for review together with the closest record line.
- **Value questions**: the best-matching fact's cluster. One active value → SUPPORTED; several → UNCERTAIN with the conflict attached.
- **Yes/no questions**: polarity statements. If both polarities are active → UNCERTAIN.
- **Insufficient-evidence gate**: a question term absent from the whole corpus must be semantically covered by a sentence in the top passages (cosine ≥ 0.78). If not, the answer is INSUFFICIENT and the closest passages are shown as context only.
- **Verdict rules for eligibility**:
  - any criterion CONTRADICTED → *Not eligible*;
  - any UNCERTAIN → *Undetermined*;
  - all SUPPORTED → *Eligible*;
  - SUPPORTED plus gaps → *Likely eligible*.

## Confidence (`intel/confidence.py`)

`score = 0.25·relevance + 0.25·corroboration + 0.20·agreement + 0.20·completeness + 0.10·extraction`

| Signal | Meaning |
|---|---|
| relevance | mean relevance of the cited evidence |
| corroboration | independent documents per decided claim (1 → 0.55, 2 → 0.8, 3+ → 1.0) |
| agreement | 1.0 with no conflicts; 0.92 if all conflicts were resolved; 0.75 if an unresolved conflict exists but isn't material; 0.3 if a conclusion depends on one |
| completeness | the share of claims that have evidence |
| extraction | OCR confidence, or 1.0 for native text |

The score is capped by the verdict: INSUFFICIENT ≤ 25%, UNCERTAIN ≤ 55%, PARTIAL ≤ 85%. Each signal is returned with a sentence explaining it.

## LLM layer (`intel/llm.py`, optional)

When `ANTHROPIC_API_KEY` is set, Claude (`claude-opus-5-5`, structured JSON output, server-side refusal fallback) receives:
- the question;
- the evidence passages, as escaped data tags with flagged sentences redacted;
- the engine's findings.

Its output passes a gate:
- unknown evidence ids → the claim is rejected;
- numbers that don't appear in the cited text → the claim is rejected;
- duplicates of engine claims are dropped;
- the final verdict is the more cautious one;
- confidence remains the engine's.

On any failure the extractive answer is returned, with a note.

## Data model

**System of record** (Flyway `V1__init_schema.sql`):

| Table | Holds |
|---|---|
| `users` | accounts, including guest workspaces |
| `investigations` | owned by a user |
| `documents` | file metadata, SHA-256, storage path, status, extraction stats |
| `questions` / `answers` | the full structured payload plus verdict, headline, confidence, engine and latency |
| `claims` / `citations` | normalised for querying and audit |
| `conflicts` | the conflicts attached to each answer |
| `investigation_events` | the timeline |

**Evidence store** (`app/store/store.py`, SQLite or pgvector):

| Table | Holds |
|---|---|
| `documents` | metadata JSON: people, subjects, amendments, page sizes, warnings |
| `chunks` | text, section, page, lines, boxes, quality, flagged sentences, `embedding vector(384)` (pgvector) |
| `facts` | typed value, comparator, label, role, sentence offsets, `embedding` |
| `security_flags` | kind, severity, text, reasons, page, bounding box |

The tables of the two stores live in **separate databases** in the deployment.

## Production-path findings (PostgreSQL + pgvector)

The first run on real PostgreSQL 16 with pgvector 0.6.2 found three bugs that SQLite and H2 could not show. All three are fixed and covered by tests:

1. **Vectors came back as objects.** Newer `pgvector-python` returns a `Vector` object, not an array, so every question would have failed. Fixed in `Store._unvec`.
2. **A global HNSW index silently returned nothing.** With many investigations in one table, the HNSW scan returns its `ef_search` nearest rows across *all* of them, and the `collection_id` filter then discards every one: zero results. Investigations are small, so the query now filters first (a `MATERIALIZED` CTE) and ranks exactly with `<=>`, and the misleading index was dropped. For one very large collection, a per-collection partial index or pgvector ≥ 0.8 iterative scans would be the next step.
3. **The JVM sent its host timezone to Postgres.** Some hosts report legacy aliases (`Asia/Calcutta`) that PostgreSQL rejects at connect time. The API now pins the JVM to UTC; every timestamp is a UTC instant.

The same run also hardened the session check. A validly signed token whose account no longer exists (database reset, deleted guest) is detected on load in the UI and returns 401 from the API, rather than a foreign-key 409.

## Failure handling

| Failure | Behaviour |
|---|---|
| Corrupt, empty, encrypted, mismatched or unsupported file | Rejected per file, with a stable code and a readable message; the other files in the batch continue |
| Duplicate file | `DUPLICATE`, naming the original |
| OCR finds nothing | `OCR_NO_TEXT`; a scanned page inside a PDF becomes a warning instead |
| Evidence service down during ingestion | The document becomes `FAILED` with `AI_UNAVAILABLE` and a Retry button; it is never left stuck |
| Restart mid-ingestion | Queued and processing documents are resumed at startup |
| Evidence service down during a question | 503 `AI_UNAVAILABLE` |
| Evidence store down | The service returns 503 `UNAVAILABLE` with `component: evidence_store`, and `/health` reports degraded. The next call reconnects automatically once the database is back (verified by restarting Postgres under the running service) |
| Backend down | The UI shows "The VERITAS server is unavailable right now"; the network-level error is reported in plain words |
| Stale session (account gone) | The UI detects it on load, clears it and shows "Your session ended"; the API answers 401 |
| LLM down, refusing, or truncated | Extractive answer with a note |
| Documents still indexing | The answer uses the indexed ones and says how many are pending |
