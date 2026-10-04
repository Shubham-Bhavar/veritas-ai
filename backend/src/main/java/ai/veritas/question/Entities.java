package ai.veritas.question;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

/** Persistence model for questions and their evidence-backed answers. */
final class Entities {

    private Entities() {
    }

    @Entity
    @Table(name = "questions")
    static class Question {
        @Id
        UUID id;
        @Column(name = "investigation_id", nullable = false)
        UUID investigationId;
        @Column(name = "asked_by", nullable = false)
        Long askedBy;
        @Column(nullable = false)
        String text;
        @Column(name = "created_at", nullable = false)
        Instant createdAt;

        protected Question() {
        }

        Question(UUID investigationId, Long askedBy, String text) {
            this.id = UUID.randomUUID();
            this.investigationId = investigationId;
            this.askedBy = askedBy;
            this.text = text;
            this.createdAt = Instant.now();
        }
    }

    @Entity
    @Table(name = "answers")
    static class Answer {
        @Id
        UUID id;
        @Column(name = "question_id", nullable = false)
        UUID questionId;
        @Column(name = "verdict_status", nullable = false)
        String verdictStatus;
        @Column(nullable = false)
        String headline;
        @Column(nullable = false)
        double confidence;
        @Column(nullable = false)
        String engine;
        @Column(nullable = false)
        String payload;
        @Column(name = "latency_ms", nullable = false)
        long latencyMs;
        @Column(name = "created_at", nullable = false)
        Instant createdAt;

        protected Answer() {
        }

        Answer(UUID questionId, String verdictStatus, String headline, double confidence, String engine, String payload, long latencyMs) {
            this.id = UUID.randomUUID();
            this.questionId = questionId;
            this.verdictStatus = verdictStatus;
            this.headline = headline.length() > 300 ? headline.substring(0, 297) + "…" : headline;
            this.confidence = confidence;
            this.engine = engine;
            this.payload = payload;
            this.latencyMs = latencyMs;
            this.createdAt = Instant.now();
        }
    }

    @Entity
    @Table(name = "claims")
    static class ClaimRow {
        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        Long id;
        @Column(name = "answer_id", nullable = false)
        UUID answerId;
        @Column(name = "claim_key", nullable = false)
        String claimKey;
        @Column(nullable = false)
        int position;
        @Column(nullable = false)
        String text;
        @Column(nullable = false)
        String status;
        @Column(nullable = false)
        String kind;
        @Column(nullable = false)
        String source;

        protected ClaimRow() {
        }

        ClaimRow(UUID answerId, String claimKey, int position, String text, String status, String kind, String source) {
            this.answerId = answerId;
            this.claimKey = claimKey;
            this.position = position;
            this.text = clip(text, 2000);
            this.status = status;
            this.kind = kind;
            this.source = source;
        }
    }

    @Entity
    @Table(name = "citations")
    static class CitationRow {
        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        Long id;
        @Column(name = "claim_id", nullable = false)
        Long claimId;
        @Column(name = "evidence_key", nullable = false)
        String evidenceKey;
        @Column(name = "document_id")
        UUID documentId;
        @Column(name = "chunk_id", nullable = false)
        String chunkId;
        Integer page;
        String section;
        @Column(nullable = false)
        String stance;
        @Column(nullable = false)
        String quote;

        protected CitationRow() {
        }

        CitationRow(Long claimId, String evidenceKey, UUID documentId, String chunkId, Integer page, String section, String stance,
                String quote) {
            this.claimId = claimId;
            this.evidenceKey = evidenceKey;
            this.documentId = documentId;
            this.chunkId = chunkId;
            this.page = page;
            this.section = clip(section, 500);
            this.stance = stance;
            this.quote = clip(quote, 2000);
        }
    }

    @Entity
    @Table(name = "conflicts")
    static class ConflictRow {
        @Id
        @GeneratedValue(strategy = GenerationType.IDENTITY)
        Long id;
        @Column(name = "answer_id", nullable = false)
        UUID answerId;
        @Column(name = "conflict_key", nullable = false)
        String conflictKey;
        @Column(nullable = false)
        String severity;
        @Column(nullable = false)
        String status;
        @Column(nullable = false)
        String summary;

        protected ConflictRow() {
        }

        ConflictRow(UUID answerId, String conflictKey, String severity, String status, String summary) {
            this.answerId = answerId;
            this.conflictKey = conflictKey;
            this.severity = severity;
            this.status = status;
            this.summary = clip(summary, 500);
        }
    }

    static String clip(String s, int max) {
        if (s == null) {
            return null;
        }
        return s.length() > max ? s.substring(0, max - 1) + "…" : s;
    }
}
