# VERITAS AI

**AI that investigates documents — not just reads them.**

> **Live demo:** https://classical-shorts-medicaid-taste.trycloudflare.com — choose **Continue as guest**, then **Load the demo investigation** (indexes in about 30 s), then open **Judge mode** in the sidebar.
> It runs the Docker Compose stack below (PostgreSQL + pgvector, evidence service, API, nginx), served through a Cloudflare tunnel.
> **Source:** https://github.com/Shubham-Bhavar/veritas-ai

VERITAS is an evidence-first document investigation platform built for ALGOTHON'26, problem **ALG-AI-02 — Intelligent Document Investigator**. You upload a collection of PDFs, Word files, text files and scans, then ask hard questions. VERITAS answers with:

- a **verdict** in one of five evidence states: Supported, Partially supported, Contradicted, Uncertain, Insufficient evidence;
- the **claims** behind it, each citing **evidence** that points at an exact sentence on an exact page;
- the **conflicts** between documents, resolved only when a document explicitly supersedes or amends another;
- a **confidence** score computed from named evidence signals and explained in plain language;
- what is **missing**, and what to do next.

---

## The problem

Organisations rarely ask a question that one document answers. A scholarship officer, a compliance analyst or a contract reviewer has to read several documents, often in different versions and formats, and some of them disagree. A chat-with-PDF tool returns one confident paragraph, but it can't show where each part came from. It can't notice that two rulebooks state different limits, and it never says "the documents don't tell us." Those failures are exactly the ones that matter when the answer has to be defended.

## The solution

VERITAS treats every answer as an investigation:

```
UPLOAD → INDEX → UNDERSTAND → INVESTIGATE → CORRELATE → VERIFY → EXPLAIN
```

| Stage | What actually happens |
|---|---|
| Upload | Files are validated by **content** (magic bytes, archive structure, encoding), not by name. Duplicates are rejected by SHA-256. |
| Index | PyMuPDF layout extraction with font-aware heading detection, running-header removal and hidden-text detection; python-docx with tables; OCR (RapidOCR) for images and image-only PDF pages. Every chunk keeps its page, section path, line and bounding boxes. |
| Understand | **Typed fact extraction**: money (₹2,50,000, Rs. 2.5 lakh), percentages, CGPA, ages and age ranges, dates. Each fact carries a comparator (≤, ≥, range), an attribute label ("annual family income") and a role (requirement / subject record / statement). |
| Investigate | Hybrid retrieval: local embeddings (bge-small) + BM25, reciprocal-rank fusion, cross-encoder re-ranking, per-document diversity. On PostgreSQL the dense ranking is a pgvector cosine query scoped to the investigation. |
| Correlate | Facts are clustered **by attribute across documents** using value-masked clause embeddings, label overlap, comparator compatibility and a cannot-link constraint. Clusters that disagree become conflicts. Polarity contradictions ("eligible" vs "not eligible") are detected too. |
| Verify | Eligibility criteria are evaluated deterministically against the subject's records. If an LLM is configured, its claims must cite real evidence ids and contain only numbers that appear in the cited text, and the more cautious verdict wins. |
| Explain | Verdict, claims, evidence, conflicts, missing information, a recommendation, an evidence graph and a timed reasoning trace. |

## Why VERITAS is not a chatbot

- **No answer without a citation.** Every claim lists evidence items, and every evidence item opens the real page with the passage highlighted.
- **It refuses to guess.** It answered *"Does the scholarship cover hostel fees?"* with **Insufficient evidence**. A naive system answers "No", by matching *"does not cover examination fees"*.
- **It refuses to pick sides.** Two 2026 rulebooks state ₹2,50,000 and ₹2,00,000. VERITAS reports the conflict and explains that the later date does not establish which rule applies. It resolves a conflict only when a document says so; for example, the circular that "in partial modification of para 4.2… hereby extended" the deadline.
- **Confidence is computed, not claimed.** It is a weighted sum of relevance, corroboration, agreement, completeness and extraction quality. It is capped by the verdict, and a model can never set it.
- **Documents can't give orders.** Hidden white text that tells the AI to approve an applicant at 100% confidence is found, quarantined and shown to the user. The verdict stays "Undetermined".

## Key features

| Feature | Where |
|---|---|
| Investigation workspace with verdict, claims, evidence and uncertainty | *Investigate* tab |
| **Source Inspector**: the real page image with the cited sentence highlighted (PDF and scans), or the passage in context (DOCX/TXT), plus "why this evidence matters" | click any evidence |
| **Evidence Graph**: Documents → Evidence → Conflicts → Claims → Verdict; hover traces a path | *Evidence Graph* tab |
| **Conflict Radar**: values, sources, dates, sections, severity, resolution status, the reason it is a conflict, and the most recent document (reported, not used to decide) | *Conflict Radar* tab |
| **Uncertainty engine**: explainable confidence with a signal breakdown; missing evidence; conditions for human review | answer view |
| **Compare documents**: changed values, added and removed requirements, supersession clause cited | *Compare* tab |
| **Investigation timeline**: uploads, indexing (with timings), security findings, questions, conclusions | *Timeline* tab |
| **Prompt-injection defence**: hidden-text detection, instruction scoring, quarantine, redaction, LLM verification | *Security* tab |
| **Judge mode**: Case 1 Supported · 2 Conflict · 3 Insufficient evidence · 4 Prompt injection · 5 Comparison, plus the flagship, one click each, run live | sidebar |
| **Answer brief**: Asked / Found / Evidence / Conflict (decisive vs. merely present) / Uncertain / Why, built from the answer's own data | top of every answer |
| One-click **demo investigation**: 11 documents in 5 formats | workspace |

## Architecture

```
React (Vite) ──/api──▶ Spring Boot API ──internal token──▶ FastAPI evidence service
   UI                  auth, investigations,                 extraction · OCR · facts
                       uploads, async ingestion,              embeddings · hybrid retrieval
                       answers, claims, citations,            conflicts · reasoning
                       timeline                               verification · rendering
                          │                                      │
                    PostgreSQL (veritas)              PostgreSQL + pgvector (evidence)
                    H2 locally                        SQLite locally
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the pipeline, the engines and the data model.

## Tech stack

- **Frontend:** React 19, Vite 8, React Router 7, TanStack Query, hand-written CSS design system (Instrument Serif, IBM Plex Sans and Mono)
- **Backend:** Spring Boot 4.1 (Java 21), Spring Security with JWT, Spring Data JPA, Flyway, PostgreSQL (H2 in PostgreSQL mode locally)
- **Evidence service:** Python, FastAPI, PyMuPDF, python-docx, RapidOCR (ONNX), fastembed (`BAAI/bge-small-en-v1.5` embeddings and the `ms-marco-MiniLM-L-6-v2` cross-encoder), NumPy, psycopg with pgvector, and the optional Anthropic SDK (Claude)
- **Deployment:** Docker Compose (pgvector/pgvector:pg16, nginx)

## Running it

### Docker (recommended)

```bash
cp .env.example .env
```

Fill in `DB_PASSWORD`, `JWT_SECRET` (`openssl rand -base64 48`) and `AI_INTERNAL_TOKEN` (`openssl rand -base64 32`). `ANTHROPIC_API_KEY` is optional.

```bash
docker compose up --build
```

Open http://localhost:8080, choose **Continue as guest**, then **Load the demo investigation**.

### Local development (no Docker)

Requirements: Java 21, Maven, Node 20+, Python 3.12+.

```bash
# 1. Evidence service
cd ai-service
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (bin/pip on macOS/Linux)
AI_INTERNAL_TOKEN=dev-token-change-me .venv/Scripts/python -m uvicorn app.main:app --port 8001

# 2. API (new terminal)
cd backend
mvn -DskipTests package
JWT_SECRET=$(openssl rand -base64 48) AI_INTERNAL_TOKEN=dev-token-change-me AI_SERVICE_URL=http://127.0.0.1:8001 \
  java -jar target/veritas-backend-1.0.0.jar --server.port=8090

# 3. Web app (new terminal)
cd frontend
npm install
API_PROXY_TARGET=http://127.0.0.1:8090 npm run dev
```

The first start of the evidence service downloads the embedding and re-ranking models (about 150 MB) into `ai-service/data/models`. Locally the evidence store is SQLite and the API database is an H2 file, so no database server is needed.

To regenerate the demo documents: `python ai-service/demo/generate_demo.py`.

## Environment variables

| Variable | Service | Purpose |
|---|---|---|
| `JWT_SECRET` | API | Signs access tokens (≥ 32 bytes). **Required.** |
| `AI_INTERNAL_TOKEN` | API + AI | Shared secret for internal calls. **Required.** |
| `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` | API | PostgreSQL connection (defaults to a local H2 file) |
| `EVIDENCE_DATABASE_URL` | AI | `postgresql://…` (pgvector) or `sqlite:///…` (default) |
| `ANTHROPIC_API_KEY`, `LLM_MODEL`, `LLM_EFFORT` | AI | Optional Claude synthesis (default model `claude-opus-5-5`) |
| `MAX_FILE_MB`, `MAX_PAGES` | both | Upload limits (25 MB, 300 pages) |
| `ENABLE_OCR`, `ENABLE_RERANKER`, `EMBEDDING_MODEL` | AI | Engine switches |
| `DEMO_ENABLED` | API | Enables the one-click demo investigation |
| `ALLOWED_ORIGINS` | API | CORS origins, only for cross-origin deployments |
| `RATE_LIMIT_AUTH`, `RATE_LIMIT_ASK`, `RATE_LIMIT_UPLOAD` | API | Per-IP requests per minute |

## Enabling Claude (optional)

1. Get an Anthropic API key from the Claude Console.
2. Set it **only** on the evidence service, never on the frontend or the API:
   - Docker: add `ANTHROPIC_API_KEY=...` to `.env`, then `docker compose up -d ai`.
   - Local: start the evidence service with `ANTHROPIC_API_KEY=...` in its environment.
3. Check that the workspace's **Engines → Reasoning** reads `Claude (claude-opus-5-5) + verification`, and that answers show the badge *Claude synthesis · verified*.
4. Optional: `LLM_MODEL` (default `claude-opus-5-5`), `LLM_EFFORT` (`low`, `medium` or `high`; default `medium`), `LLM_TIMEOUT_S` (default 90).

What changes with a key:
- Claude writes the answer text, and may add claims for conditions stated in words.
- Every added claim must cite existing evidence ids and contain only numbers that appear in the cited text. If not, it is discarded and the UI says so.
- The verdict is the more cautious of the engine's and Claude's; confidence is still computed by the engine.
- On a refusal, a timeout or an API error, the extractive answer is shown with a note.

## API overview

All `/api` routes except auth and status need `Authorization: Bearer <token>`. Another user's investigation returns 404.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/guest` · `/register` · `/login` | Get an access token |
| GET | `/api/system/status` | Which engines are live |
| GET/POST | `/api/investigations` | List / create |
| POST | `/api/investigations/demo` | Create the demo investigation (real ingestion) |
| GET/PATCH/DELETE | `/api/investigations/{id}` | Detail with documents / rename / delete |
| POST | `/api/investigations/{id}/documents` | Multipart upload (`files`), per-file results |
| POST/DELETE | `/api/investigations/{id}/documents/{doc}[/retry]` | Retry a failed document / remove one |
| GET | `/api/investigations/{id}/documents/{doc}/pages/{n}?chunk=&sentence=&flags=` | Page PNG with highlights |
| GET | `/api/investigations/{id}/documents/{doc}/content` · `/chunks/{chunk}` | Text view / passage in context |
| POST | `/api/investigations/{id}/questions` | Investigate a question (structured answer) |
| GET | `/api/investigations/{id}/questions[/{qid}]` | Question log / a stored answer |
| GET | `/api/investigations/{id}/conflicts` · `/security` · `/overview` · `/timeline` | Radar, flags, counts, events |
| POST | `/api/investigations/{id}/compare` | Compare two documents |

Errors are RFC 7807 `application/problem+json` with a stable `code` (`DUPLICATE`, `TYPE_MISMATCH`, `STILL_INDEXING`, `AI_UNAVAILABLE`…).

## Testing

```bash
cd ai-service && .venv/Scripts/python -m pytest -q    # 54 tests (53 + 1 Postgres-only on SQLite)
TEST_EVIDENCE_DATABASE_URL=postgresql://user:pass@host:5432/evidence .venv/Scripts/python -m pytest -q   # same suite on PostgreSQL + pgvector
cd backend && mvn test                                 # 12 tests: authz isolation, stale sessions, upload validation, outages, persistence
cd frontend && npm test                                # component tests (confidence breakdown, status vocabulary)
```

Last run results: AI **54/54 on PostgreSQL 16 + pgvector 0.6.2** and **53 + 1 skipped on SQLite**; backend **12/12**; frontend **2/2**.

The AI tests run the **real** pipeline on the real demo documents, with real OCR and real embeddings. They cover:

- **Bad input:** empty, corrupted, encrypted, mismatched, oversized and binary files; unsupported types; duplicates; the page limit; OCR finding no text; a 120-page document.
- **Answers:** missing evidence, conflicting values, contradictory statements, an irrelevant question, an ambiguous subject.
- **Security:** prompt injection hidden in a PDF, and a manipulated LLM output that tries to fake citations, numbers and confidence.
- **The Claude path through the real Anthropic SDK:** the network is replaced by a mock transport (`tests/test_llm_wire.py`). The tests check:
  - the exact request: model, structured output, effort, refusal fallback, system prompt;
  - that the cautious verdict is kept;
  - that HTTP 500, 429 and 401, refusals and truncation all fall back to the engine.
- **Outages:** the LLM is unavailable, or the evidence store is unavailable (503, with automatic reconnect once the database returns).
- **pgvector:** search is scoped to one investigation and matches the exact ranking.

## Verification status

| Area | Verified how | Result |
|---|---|---|
| Full app on **PostgreSQL 16 + pgvector 0.6.2** | Native Postgres binaries with pgvector, set up by `deploy/postgres-init.sql`; Flyway V1 applied; a fresh guest → demo → all judge cases run through the UI | ✅ Passed, after fixing 3 production-path bugs (see ARCHITECTURE.md › Production-path findings) |
| Persistence | Evidence service restarted, then answers rebuilt from Postgres; the question log reloaded | ✅ |
| Database outage | Postgres restarted under the running service | ✅ Degraded, then recovered on the next call without a restart |
| Claude request and failure handling | Real `anthropic` SDK with a mock HTTP transport | ✅ Request shape, verification gate, 500/429/401/refusal/truncation |
| **Live Claude answers** | Needs `ANTHROPIC_API_KEY` | ⚠️ Not run: no key in this environment |
| **`docker compose up --build`** | Docker Desktop 4.93 on Windows (WSL2) | ✅ All 4 containers up (ai and postgres healthy). A fresh guest → demo indexed 11/11 on pgvector in 36 s → flagship answer "Likely eligible", 85%; conflicts 2 unresolved, 3 resolved |
| Public deployment | Cloudflare tunnel to the compose stack | ✅ Homepage, API, guest login and deep links served over HTTPS |

**Measured on the demo set (Postgres, laptop CPU):** a fresh demo load is fully indexed in about 20 s; the two OCR scans take about 7–9 s each. Questions take 0.8–2.8 s from click to rendered answer, compare is under 1 s, and a page render is under 1 s.

## Deployment

`docker-compose.yml` runs four containers:

- PostgreSQL with pgvector, which holds two databases (`veritas` for the API, `evidence` for the evidence service);
- the evidence service, internal only, with its models baked into the image;
- the API, internal only;
- nginx, which serves the app and proxies `/api`. This is the only published port.

Put a TLS-terminating proxy (Caddy, a cloud load balancer) in front for production.

## Limitations (stated honestly)

- **The live link is served from a team laptop** through a Cloudflare quick tunnel. It is up only while that machine runs the compose stack, and the URL changes if the tunnel restarts. For permanent hosting, run `docker compose up -d` on any VM with Docker and about 4 GB RAM.
- **Live Claude answers have not been observed** because no API key was available. The integration is exercised through the real SDK with a mock transport, including a deliberately manipulated model. Without a key, the **extractive engine** answers, and the UI says so in the sidebar and on each answer.
- **The extractive engine decides numeric criteria, not prose.** Conditions such as "not receiving another scholarship" are listed for human review together with the closest record, not decided automatically. An LLM, when configured, adds verified claims for these.
- Fact extraction is tuned for English with Indian number formats and common date formats. Attribute matching is general (embedding-based), but its thresholds were calibrated on policy-style documents.
- Handwriting OCR and complex multi-column tables are out of scope. DOCX has no page numbers, so DOCX citations use paragraph positions.
- The evidence service caches each collection in memory, so it runs as one worker. Scale horizontally per tenant, or move the cache to Redis.

## Future improvements

- An NLI model to judge prose conditions without an LLM.
- Cross-version document lineage, so supersession is detected from titles and reference numbers alone.
- Reviewer workflows: accept a conflict resolution and record who decided it.
- Streaming answers, and server-sent events for indexing progress.
- Per-tenant encryption at rest, and audit export.

## AI / API disclosure

- **Models used at runtime:** `BAAI/bge-small-en-v1.5` (embeddings) and `Xenova/ms-marco-MiniLM-L-6-v2` (re-ranking), both run locally through ONNX; RapidOCR (local); optionally Anthropic Claude (`claude-opus-5-5`) for answer synthesis. No document leaves the deployment unless an Anthropic key is configured, and then only the retrieved, redacted passages are sent.
- **Development:** this project was built with the help of an AI coding assistant (Claude). The design, code, demo documents and tests were reviewed and run during development.
- The demo documents are fictional. Any resemblance to real applicants or circulars is unintended.
