package ai.veritas.document;

import java.util.List;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import ai.veritas.ai.AiClient;
import ai.veritas.common.ApiException;
import ai.veritas.timeline.EventService;
import tools.jackson.databind.JsonNode;

/** Sends queued documents to the evidence service in the background and records the outcome. */
@Component
public class DocumentIngestor {

    private static final Logger log = LoggerFactory.getLogger(DocumentIngestor.class);

    private final DocumentRepository documents;
    private final FileStorage storage;
    private final AiClient ai;
    private final EventService events;

    public DocumentIngestor(DocumentRepository documents, FileStorage storage, AiClient ai, EventService events) {
        this.documents = documents;
        this.storage = storage;
        this.ai = ai;
        this.events = events;
    }

    @Async("ingestExecutor")
    public void ingest(UUID documentId) {
        EvidenceDocument doc = documents.findById(documentId).orElse(null);
        if (doc == null) {
            return; // deleted while queued
        }
        doc.markProcessing();
        documents.save(doc);
        long t0 = System.currentTimeMillis();
        try {
            JsonNode r = ai.ingest(doc.getInvestigationId(), doc.getId(), doc.getFilename(), storage.resolve(doc.getStoragePath()));
            if (!documents.existsById(documentId)) {
                ai.deleteDocument(doc.getInvestigationId(), documentId); // deleted during processing
                return;
            }
            List<String> warnings = r.path("warnings").valueStream().map(JsonNode::asString).toList();
            int flags = r.path("security_flags").asInt(0);
            doc.markIndexed(r.path("kind").asString(null), r.path("title").asString(null), r.path("role").asString(null),
                    r.path("doc_date").isNull() ? null : r.path("doc_date").asString(null),
                    r.path("pages").isNull() ? null : r.path("pages").asInt(), r.path("chunks").asInt(), r.path("facts").asInt(),
                    r.path("ocr_used").asBoolean(false), r.path("quality").asDouble(1.0), flags,
                    warnings.isEmpty() ? null : String.join("\n", warnings), System.currentTimeMillis() - t0);
            documents.save(doc);
            String pages = r.path("pages").isNull() ? "" : r.path("pages").asInt() + " pages, ";
            events.record(doc.getInvestigationId(), "document.indexed",
                    doc.getFilename() + " indexed — " + pages + r.path("chunks").asInt() + " evidence chunks, "
                            + r.path("facts").asInt() + " facts" + (r.path("ocr_used").asBoolean(false) ? " (OCR)" : ""),
                    "extract " + r.path("timings").path("extract_ms").asLong() + " ms · embed "
                            + r.path("timings").path("embed_ms").asLong() + " ms");
            if (flags > 0) {
                events.record(doc.getInvestigationId(), "security.flagged",
                        flags + " instruction-like passage(s) neutralised in " + doc.getFilename(),
                        "Treated as evidence only; excluded from facts and redacted from AI prompts.");
            }
            summarizeIfIdle(doc.getInvestigationId());
        } catch (AiClient.Rejected e) {
            fail(doc, e.getCode(), e.getMessage());
        } catch (ApiException e) {
            fail(doc, e.getCode(), e.getMessage());
        } catch (RuntimeException | LinkageError e) {
            // never leave a document stuck in PROCESSING
            log.error("Ingestion of {} failed", documentId, e);
            fail(doc, "INGEST_FAILED", "Indexing failed unexpectedly. Retry the document.");
        }
    }

    private void fail(EvidenceDocument doc, String code, String message) {
        if (!documents.existsById(doc.getId())) {
            return;
        }
        doc.markFailed(code, message);
        documents.save(doc);
        events.record(doc.getInvestigationId(), "document.failed", doc.getFilename() + " could not be indexed: " + message, code);
    }

    /** After the last queued document finishes, record what the collection now contains. */
    private void summarizeIfIdle(UUID investigationId) {
        boolean busy = documents.findByInvestigationIdOrderByCreatedAtAsc(investigationId).stream()
                .anyMatch(d -> d.getStatus() == EvidenceDocument.Status.QUEUED || d.getStatus() == EvidenceDocument.Status.PROCESSING);
        if (busy) {
            return;
        }
        try {
            JsonNode o = ai.get("/v1/collections/{c}/overview", investigationId);
            events.record(investigationId, "collection.analysed",
                    o.path("documents").asInt() + " documents analysed — " + o.path("chunks").asInt() + " evidence chunks, "
                            + o.path("facts").asInt() + " facts, " + o.path("conflicts_unresolved").asInt()
                            + " unresolved conflicts detected",
                    o.path("conflicts_resolved").asInt() + " conflicts resolved by supersession or amendment");
        } catch (RuntimeException e) {
            log.warn("Could not summarise collection {}: {}", investigationId, e.getMessage());
        }
    }
}
