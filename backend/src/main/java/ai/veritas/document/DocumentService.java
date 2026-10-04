package ai.veritas.document;

import java.io.IOException;
import java.io.InputStream;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import ai.veritas.ai.AiClient;
import ai.veritas.common.ApiException;
import ai.veritas.config.AppProperties;
import ai.veritas.timeline.EventService;

/** Upload validation, storage and queueing. Deep content validation happens again in the AI service. */
@Service
public class DocumentService {

    private static final Logger log = LoggerFactory.getLogger(DocumentService.class);
    static final Set<String> EXTENSIONS = Set.of("pdf", "docx", "txt", "md", "csv", "png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp");

    private final DocumentRepository documents;
    private final FileStorage storage;
    private final DocumentIngestor ingestor;
    private final AiClient ai;
    private final EventService events;
    private final AppProperties.Uploads limits;

    public DocumentService(DocumentRepository documents, FileStorage storage, DocumentIngestor ingestor, AiClient ai,
            EventService events, AppProperties props) {
        this.documents = documents;
        this.storage = storage;
        this.ingestor = ingestor;
        this.ai = ai;
        this.events = events;
        this.limits = props.uploads();
    }

    /** Result per file, so one bad file in a batch does not reject the others. */
    public record UploadResult(String filename, boolean accepted, UUID documentId, String code, String message) {
    }

    public List<UploadResult> upload(UUID investigationId, List<MultipartFile> files) {
        if (files == null || files.isEmpty()) {
            throw ApiException.badRequest("Choose at least one file to upload.");
        }
        if (files.size() > limits.maxFilesPerRequest()) {
            throw ApiException.badRequest("Upload at most " + limits.maxFilesPerRequest() + " files at a time.");
        }
        long existing = documents.countByInvestigationId(investigationId);
        List<UploadResult> results = new ArrayList<>();
        List<UUID> queued = new ArrayList<>();
        for (MultipartFile f : files) {
            String name = sanitize(f.getOriginalFilename());
            if (existing + queued.size() >= limits.maxDocumentsPerInvestigation()) {
                results.add(new UploadResult(name, false, null, "LIMIT", "This investigation already holds the maximum number of documents."));
                continue;
            }
            try {
                UUID id = store(investigationId, f, name);
                queued.add(id);
                results.add(new UploadResult(name, true, id, null, null));
            } catch (ApiException e) {
                results.add(new UploadResult(name, false, null, e.getCode(), e.getMessage()));
            }
        }
        if (!queued.isEmpty()) {
            events.record(investigationId, "documents.uploaded", queued.size() + " document(s) uploaded and queued for indexing",
                    String.join(", ", results.stream().filter(UploadResult::accepted).map(UploadResult::filename).toList()));
        }
        queued.forEach(ingestor::ingest);
        return results;
    }

    UUID store(UUID investigationId, MultipartFile f, String name) {
        if (f.isEmpty()) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EMPTY_FILE", "The file is empty.");
        }
        if (f.getSize() > (long) limits.maxFileMb() * 1024 * 1024) {
            throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "FILE_TOO_LARGE", "The file is larger than " + limits.maxFileMb() + " MB.");
        }
        String ext = name.contains(".") ? name.substring(name.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT) : "";
        if (!EXTENSIONS.contains(ext)) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "UNSUPPORTED_TYPE",
                    "'" + (ext.isEmpty() ? "no extension" : "." + ext) + "' files are not supported. Use PDF, DOCX, TXT/MD or an image.");
        }
        UUID id = UUID.randomUUID();
        try (InputStream in = f.getInputStream()) {
            byte[] head = in.readNBytes(8);
            if (!signatureMatches(ext, head)) {
                throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "TYPE_MISMATCH", "The file content does not match its ." + ext + " extension.");
            }
        } catch (IOException e) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "UNREADABLE", "The file could not be read.");
        }
        String sha;
        String path;
        try (DigestInputStream in = new DigestInputStream(f.getInputStream(), MessageDigest.getInstance("SHA-256"))) {
            path = storage.save(investigationId, id, in).toString();
            sha = HexFormat.of().formatHex(in.getMessageDigest().digest());
        } catch (IOException | NoSuchAlgorithmException e) {
            log.error("Storing upload failed", e);
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "STORAGE", "The file could not be stored.");
        }
        var dup = documents.findByInvestigationIdAndSha256(investigationId, sha);
        if (dup.isPresent()) {
            storage.delete(path);
            throw ApiException.conflict("DUPLICATE", "Identical to '" + dup.get().getFilename() + "', which is already in this investigation.");
        }
        documents.save(new EvidenceDocument(id, investigationId, name, f.getContentType(), f.getSize(), sha, path));
        return id;
    }

    static boolean signatureMatches(String ext, byte[] h) {
        return switch (ext) {
            case "pdf" -> starts(h, 0x25, 0x50, 0x44, 0x46);
            case "docx" -> starts(h, 0x50, 0x4B, 0x03, 0x04);
            case "png" -> starts(h, 0x89, 0x50, 0x4E, 0x47);
            case "jpg", "jpeg" -> starts(h, 0xFF, 0xD8, 0xFF);
            case "webp" -> starts(h, 0x52, 0x49, 0x46, 0x46);
            case "tif", "tiff" -> starts(h, 0x49, 0x49, 0x2A, 0x00) || starts(h, 0x4D, 0x4D, 0x00, 0x2A);
            case "bmp" -> starts(h, 0x42, 0x4D);
            default -> { // text: no NUL bytes in the first bytes
                for (byte b : h) {
                    if (b == 0) {
                        yield false;
                    }
                }
                yield true;
            }
        };
    }

    private static boolean starts(byte[] h, int... sig) {
        if (h.length < sig.length) {
            return false;
        }
        for (int i = 0; i < sig.length; i++) {
            if ((h[i] & 0xFF) != sig[i]) {
                return false;
            }
        }
        return true;
    }

    static String sanitize(String original) {
        String name = original == null ? "document" : original.replace('\\', '/');
        name = name.substring(name.lastIndexOf('/') + 1);
        name = name.replaceAll("[\\p{Cntrl}<>:\"|?*]", "").trim();
        if (name.isEmpty() || name.equals(".") || name.equals("..")) {
            name = "document";
        }
        return name.length() > 200 ? name.substring(name.length() - 200) : name;
    }

    public void retry(UUID investigationId, UUID documentId) {
        EvidenceDocument d = documents.findByIdAndInvestigationId(documentId, investigationId)
                .orElseThrow(() -> ApiException.notFound("Document not found."));
        if (d.getStatus() != EvidenceDocument.Status.FAILED) {
            throw ApiException.conflict("NOT_FAILED", "Only failed documents can be retried.");
        }
        events.record(investigationId, "document.retry", "Retrying " + d.getFilename());
        ingestor.ingest(documentId);
    }

    public void delete(UUID investigationId, UUID documentId) {
        EvidenceDocument d = documents.findByIdAndInvestigationId(documentId, investigationId)
                .orElseThrow(() -> ApiException.notFound("Document not found."));
        documents.delete(d);
        ai.deleteDocument(investigationId, documentId);
        storage.delete(d.getStoragePath());
        events.record(investigationId, "document.removed", d.getFilename() + " removed from the investigation");
    }

    /** Documents left mid-flight by a restart are picked up again. */
    @EventListener(ApplicationReadyEvent.class)
    public void resumePending() {
        var pending = documents.findByStatusIn(List.of(EvidenceDocument.Status.QUEUED, EvidenceDocument.Status.PROCESSING));
        if (!pending.isEmpty()) {
            log.info("Resuming {} document(s) left in the ingestion queue", pending.size());
        }
        pending.forEach(d -> ingestor.ingest(d.getId()));
    }
}
