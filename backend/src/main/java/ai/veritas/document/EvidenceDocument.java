package ai.veritas.document;

import java.time.Instant;
import java.util.UUID;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "documents")
public class EvidenceDocument {

    public enum Status { QUEUED, PROCESSING, INDEXED, FAILED }

    @Id
    private UUID id;

    @Column(name = "investigation_id", nullable = false)
    private UUID investigationId;

    @Column(nullable = false)
    private String filename;

    @Column(name = "content_type")
    private String contentType;

    @Column(name = "size_bytes", nullable = false)
    private long sizeBytes;

    @Column(nullable = false)
    private String sha256;

    @Column(name = "storage_path", nullable = false)
    private String storagePath;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Status status;

    @Column(name = "error_code")
    private String errorCode;

    @Column(name = "error_message")
    private String errorMessage;

    private String kind;
    private String title;

    @Column(name = "doc_role")
    private String docRole;

    @Column(name = "doc_date")
    private String docDate;

    private Integer pages;
    private Integer chunks;
    private Integer facts;

    @Column(name = "ocr_used")
    private Boolean ocrUsed;

    private Double quality;

    @Column(name = "security_flags")
    private Integer securityFlags;

    private String warnings;

    @Column(name = "ingest_ms")
    private Long ingestMs;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "indexed_at")
    private Instant indexedAt;

    protected EvidenceDocument() {
    }

    public EvidenceDocument(UUID id, UUID investigationId, String filename, String contentType, long sizeBytes, String sha256,
            String storagePath) {
        this.id = id;
        this.investigationId = investigationId;
        this.filename = filename;
        this.contentType = contentType;
        this.sizeBytes = sizeBytes;
        this.sha256 = sha256;
        this.storagePath = storagePath;
        this.status = Status.QUEUED;
        this.createdAt = Instant.now();
    }

    public void markProcessing() {
        status = Status.PROCESSING;
        errorCode = null;
        errorMessage = null;
    }

    public void markFailed(String code, String message) {
        status = Status.FAILED;
        errorCode = code;
        errorMessage = message != null && message.length() > 500 ? message.substring(0, 497) + "…" : message;
    }

    public void markIndexed(String kind, String title, String role, String docDate, Integer pages, Integer chunks, Integer facts,
            Boolean ocrUsed, Double quality, Integer securityFlags, String warnings, long ingestMs) {
        this.status = Status.INDEXED;
        this.kind = kind;
        this.title = title != null && title.length() > 300 ? title.substring(0, 300) : title;
        this.docRole = role;
        this.docDate = docDate;
        this.pages = pages;
        this.chunks = chunks;
        this.facts = facts;
        this.ocrUsed = ocrUsed;
        this.quality = quality;
        this.securityFlags = securityFlags;
        this.warnings = warnings != null && warnings.length() > 2000 ? warnings.substring(0, 2000) : warnings;
        this.ingestMs = ingestMs;
        this.indexedAt = Instant.now();
        this.errorCode = null;
        this.errorMessage = null;
    }

    public UUID getId() { return id; }
    public UUID getInvestigationId() { return investigationId; }
    public String getFilename() { return filename; }
    public String getContentType() { return contentType; }
    public long getSizeBytes() { return sizeBytes; }
    public String getSha256() { return sha256; }
    public String getStoragePath() { return storagePath; }
    public Status getStatus() { return status; }
    public String getErrorCode() { return errorCode; }
    public String getErrorMessage() { return errorMessage; }
    public String getKind() { return kind; }
    public String getTitle() { return title; }
    public String getDocRole() { return docRole; }
    public String getDocDate() { return docDate; }
    public Integer getPages() { return pages; }
    public Integer getChunks() { return chunks; }
    public Integer getFacts() { return facts; }
    public Boolean getOcrUsed() { return ocrUsed; }
    public Double getQuality() { return quality; }
    public Integer getSecurityFlags() { return securityFlags; }
    public String getWarnings() { return warnings; }
    public Long getIngestMs() { return ingestMs; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getIndexedAt() { return indexedAt; }
}
