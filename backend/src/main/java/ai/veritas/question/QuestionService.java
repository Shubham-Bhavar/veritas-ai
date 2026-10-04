package ai.veritas.question;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import ai.veritas.ai.AiClient;
import ai.veritas.common.ApiException;
import ai.veritas.document.DocumentRepository;
import ai.veritas.document.EvidenceDocument;
import ai.veritas.timeline.EventService;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
public class QuestionService {

    private final AiClient ai;
    private final QuestionRepository questions;
    private final AnswerRepository answers;
    private final ClaimRepository claims;
    private final CitationRepository citations;
    private final ConflictRepository conflicts;
    private final DocumentRepository documents;
    private final EventService events;
    private final ObjectMapper mapper;
    private final TransactionTemplate tx;

    public QuestionService(AiClient ai, QuestionRepository questions, AnswerRepository answers, ClaimRepository claims,
            CitationRepository citations, ConflictRepository conflicts, DocumentRepository documents, EventService events,
            ObjectMapper mapper, TransactionTemplate tx) {
        this.ai = ai;
        this.questions = questions;
        this.answers = answers;
        this.claims = claims;
        this.citations = citations;
        this.conflicts = conflicts;
        this.documents = documents;
        this.events = events;
        this.mapper = mapper;
        this.tx = tx;
    }

    public JsonNode ask(UUID investigationId, Long userId, String text) {
        List<EvidenceDocument> docs = documents.findByInvestigationIdOrderByCreatedAtAsc(investigationId);
        long indexed = docs.stream().filter(d -> d.getStatus() == EvidenceDocument.Status.INDEXED).count();
        long pending = docs.stream().filter(d -> d.getStatus() == EvidenceDocument.Status.QUEUED
                || d.getStatus() == EvidenceDocument.Status.PROCESSING).count();
        if (indexed == 0) {
            throw ApiException.conflict(pending > 0 ? "STILL_INDEXING" : "NO_DOCUMENTS",
                    pending > 0 ? "Documents are still being indexed. Ask again in a moment."
                            : "Upload documents before asking a question.");
        }
        events.record(investigationId, "question.asked", "Question analysed: “" + Entities.clip(text, 300) + "”");
        long t0 = System.currentTimeMillis();
        JsonNode result = ai.investigate(investigationId, text);
        long latency = System.currentTimeMillis() - t0;

        ObjectNode payload = (ObjectNode) result;
        if (pending > 0) {
            payload.withArray("notes").add(pending + " document(s) were still being indexed and are not part of this answer.");
        }
        UUID questionId = persist(investigationId, userId, text, payload, latency);
        payload.put("question_id", questionId.toString());
        payload.put("latency_ms", latency);

        for (JsonNode step : result.path("timeline")) {
            String name = step.path("step").asString("");
            if (name.equals("retrieve") || name.equals("conflicts") || name.equals("synthesize")) {
                events.record(investigationId, "question." + name, step.path("detail").asString(""), step.path("ms").asLong() + " ms");
            }
        }
        JsonNode v = result.path("verdict");
        events.record(investigationId, "question.answered",
                "Conclusion: " + v.path("headline").asString("") + " (" + Math.round(result.path("confidence").path("score").asDouble() * 100)
                        + "% confidence, " + result.path("claims").size() + " claims, " + result.path("evidence").size() + " evidence items)",
                result.path("engine").asString("") + " engine · " + latency + " ms");
        return payload;
    }

    private UUID persist(UUID investigationId, Long userId, String text, JsonNode r, long latency) {
        return tx.execute(status -> {
            Entities.Question q = questions.save(new Entities.Question(investigationId, userId, text));
            JsonNode v = r.path("verdict");
            Entities.Answer a = answers.save(new Entities.Answer(q.id, v.path("status").asString("UNCERTAIN"),
                    v.path("headline").asString(""), r.path("confidence").path("score").asDouble(0), r.path("engine").asString("extractive"),
                    mapper.writeValueAsString(r), latency));
            Map<String, JsonNode> evidence = new HashMap<>();
            r.path("evidence").forEach(e -> evidence.put(e.path("id").asString(), e));
            int pos = 0;
            for (JsonNode c : r.path("claims")) {
                Entities.ClaimRow row = claims.save(new Entities.ClaimRow(a.id, c.path("id").asString(), pos++, c.path("text").asString(""),
                        c.path("status").asString(), c.path("kind").asString("finding"), c.path("source").asString("engine")));
                List<Entities.CitationRow> cites = new ArrayList<>();
                for (JsonNode eid : c.path("evidence")) {
                    JsonNode e = evidence.get(eid.asString());
                    if (e == null) {
                        continue;
                    }
                    UUID docId = UUID.fromString(e.path("document_id").asString());
                    cites.add(new Entities.CitationRow(row.id, eid.asString(), documents.existsById(docId) ? docId : null,
                            e.path("chunk_id").asString(), e.path("page").isNull() ? null : e.path("page").asInt(),
                            e.path("section").asString(null), e.path("stance").asString("supports"), e.path("quote").asString("")));
                }
                citations.saveAll(cites);
            }
            for (JsonNode c : r.path("conflicts")) {
                conflicts.save(new Entities.ConflictRow(a.id, c.path("id").asString(), c.path("severity").asString(),
                        c.path("status").asString(), c.path("summary").asString("")));
            }
            return q.id;
        });
    }

    public record HistoryItem(UUID id, String question, String status, String headline, double confidence, String askedAt) {
    }

    public List<HistoryItem> history(UUID investigationId) {
        List<Entities.Question> qs = questions.findByInvestigationIdOrderByCreatedAtDesc(investigationId);
        Map<UUID, Entities.Answer> byQuestion = new HashMap<>();
        answers.findByQuestionIdIn(qs.stream().map(q -> q.id).toList()).forEach(a -> byQuestion.put(a.questionId, a));
        return qs.stream().filter(q -> byQuestion.containsKey(q.id)).map(q -> {
            Entities.Answer a = byQuestion.get(q.id);
            return new HistoryItem(q.id, q.text, a.verdictStatus, a.headline, a.confidence, q.createdAt.toString());
        }).toList();
    }

    public JsonNode answer(UUID investigationId, UUID questionId) {
        Entities.Question q = questions.findByIdAndInvestigationId(questionId, investigationId)
                .orElseThrow(() -> ApiException.notFound("Question not found."));
        Entities.Answer a = answers.findByQuestionId(q.id).orElseThrow(() -> ApiException.notFound("Answer not found."));
        ObjectNode payload = (ObjectNode) mapper.readTree(a.payload);
        payload.put("question_id", q.id.toString());
        payload.put("latency_ms", a.latencyMs);
        payload.put("asked_at", q.createdAt.toString());
        return payload;
    }
}
