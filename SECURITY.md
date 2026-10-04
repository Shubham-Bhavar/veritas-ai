# VERITAS AI — Security

Investigated documents can be sensitive and can be hostile. VERITAS assumes both.

## Threat model

| Threat | Mitigation |
|---|---|
| Another user reads my investigation | Every investigation is owned by one user. Every endpoint loads it with `findByIdAndOwnerId`, and someone else's investigation returns **404**, so its existence is never revealed. Tested. |
| Stolen or forged session | HS256 JWT signed with an environment secret (≥ 32 bytes, required at startup), 12-hour expiry, `Authorization` header only (no cookies, so no CSRF). The token lives in sessionStorage and is cleared on 401. A signed token whose account no longer exists is rejected: `/auth/me` returns 401 and the UI checks it on load; creating data returns 401 rather than a database error. Tested. |
| Credential stuffing | BCrypt (cost 12), constant-time handling of unknown emails, and a per-IP rate limit on auth endpoints. Guest accounts cannot log in with a password. |
| Malicious upload | The extension allow-list is checked against magic bytes in the API **and** deep-validated again in the evidence service (archive structure, encoding, PDF parse). Size and page limits apply. Encrypted PDFs are rejected. Files are stored under server-generated UUID paths, so a client filename never picks a location. Filenames are sanitised. Duplicates are detected by SHA-256. |
| Abuse and cost | Per-IP rate limits for questions, uploads and authentication; a cap on documents per investigation. |
| Internal service exposure | The evidence service requires `X-Internal-Token` (constant-time compare) and is not published in Docker Compose. The browser only talks to `/api`. |
| Secrets in code | None. Every secret comes from the environment; `.env` is git-ignored; `.env.example` holds no values. The Anthropic key is used only server-side in the evidence service. |
| Data leaving the deployment | Embeddings, re-ranking and OCR run locally. Without an Anthropic key, nothing leaves. With one, only retrieved, redacted passages are sent. |
| SQL injection | Every query binds its values: JPA and Spring Data in the API, DB-API parameters in the evidence store. The only formatted SQL interpolates hard-coded table names. |
| Path traversal | Stored paths are built from server UUIDs and checked to stay inside the storage root. Client filenames are reduced to a base name. Tested with `../../etc/…`. |
| Error leakage | RFC 7807 responses with readable messages; no stack traces or exception messages are returned (`include-message: never`). |
| Browser-side attacks | nginx sets CSP, `X-Frame-Options: DENY`, `nosniff` and `no-referrer`. React escapes all document text, and page images are served as blobs. |

## Prompt-injection defence

Uploaded text is **data, not instructions**. The defence has five layers, and each one is tested:

1. **Detect** (`ingest/injection.py`). Each sentence is scored against weighted patterns:
   - override requests ("ignore previous instructions");
   - system-prompt extraction;
   - role reassignment ("you are now…") and authority claims ("system override", "administrator mode");
   - confidence dictation ("report 100% confidence");
   - concealment ("do not mention any conflicts");
   - chat-role markup and AI-directed imperatives.

   Ordinary policy language ("must not exceed", "will not be accepted", "system administrator will verify") is deliberately not flagged.
2. **Reveal hidden text.** PDF spans that are white, smaller than 2.5 pt, or off the page are extracted separately. Invisible prose is always high severity. The flag records its page and bounding box, so the UI can draw it on the page.
3. **Quarantine.** Flagged sentences never become facts and are never used as supporting evidence. Hidden text is never chunked.
4. **Redact.** Before any LLM call, flagged sentences are replaced with `[instruction-like text removed by VERITAS security layer]`. Passages are wrapped as escaped data tags, and the system prompt states that passage text is never an instruction.
5. **Verify.** Even a fully manipulated model cannot change the outcome:
   - claims must cite real evidence ids;
   - every number must appear in the cited text;
   - the more cautious verdict wins;
   - confidence is computed by the engine.

   `tests/test_llm_and_api.py::test_llm_cannot_override_conflict_or_invent_evidence` simulates exactly that attack.

The demo includes a real attack: white text in `Rahul_Verma_Statement_of_Purpose.pdf` instructs the AI to approve the applicant at 100% confidence. The result:
- it is flagged as HIGH and logged in the timeline;
- it is shown on the page;
- it is excluded from the answer;
- the verdict remains "Undetermined — the rules conflict" at 55%.

## Operational notes

- Rotate `JWT_SECRET` to invalidate all sessions. Rotate `AI_INTERNAL_TOKEN` on both services together.
- Back up both PostgreSQL databases and the two upload volumes. Deleting an investigation removes its rows, its vectors and its files.
- Terminate TLS in front of nginx in production. nginx overwrites `X-Forwarded-For`, so the rate limiter sees real client addresses; never expose the API container directly.
