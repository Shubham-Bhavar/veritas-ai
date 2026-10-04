package ai.veritas.investigation;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import ai.veritas.ai.AiClient;
import ai.veritas.common.ApiException;
import ai.veritas.demo.DemoService;
import ai.veritas.document.DocumentService;
import ai.veritas.document.EvidenceDocument;
import ai.veritas.question.QuestionService;
import ai.veritas.security.AuthUser;
import ai.veritas.timeline.EventService;
import ai.veritas.timeline.InvestigationEvent;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/investigations")
public class InvestigationController {

    private final InvestigationService investigations;
    private final DocumentService documents;
    private final QuestionService questions;
    private final DemoService demo;
    private final EventService events;
    private final AiClient ai;

    public InvestigationController(InvestigationService investigations, DocumentService documents, QuestionService questions,
            DemoService demo, EventService events, AiClient ai) {
        this.investigations = investigations;
        this.documents = documents;
        this.questions = questions;
        this.demo = demo;
        this.events = events;
        this.ai = ai;
    }

    // ------------------------------------------------------------------ views

    public record InvestigationView(UUID id, String title, String description, boolean demo, Instant createdAt, Instant updatedAt,
            Long documentCount, Long indexedCount) {
    }

    public record DocumentView(UUID id, String filename, String status, String errorCode, String errorMessage, long sizeBytes,
            String kind, String title, String role, String docDate, Integer pages, Integer chunks, Integer facts, Boolean ocrUsed,
            Double quality, Integer securityFlags, String warnings, Long ingestMs, Instant createdAt, Instant indexedAt) {
        static DocumentView of(EvidenceDocument d) {
            return new DocumentView(d.getId(), d.getFilename(), d.getStatus().name(), d.getErrorCode(), d.getErrorMessage(),
                    d.getSizeBytes(), d.getKind(), d.getTitle(), d.getDocRole(), d.getDocDate(), d.getPages(), d.getChunks(),
                    d.getFacts(), d.getOcrUsed(), d.getQuality(), d.getSecurityFlags(), d.getWarnings(), d.getIngestMs(),
                    d.getCreatedAt(), d.getIndexedAt());
        }
    }

    public record EventView(Long id, String type, String message, String detail, Instant at) {
        static EventView of(InvestigationEvent e) {
            return new EventView(e.getId(), e.getType(), e.getMessage(), e.getDetail(), e.getCreatedAt());
        }
    }

    public record CreateRequest(@NotBlank(message = "Give the investigation a title.") @Size(max = 200) String title,
            @Size(max = 2000) String description) {
    }

    public record AskRequest(@NotBlank(message = "Type a question.") @Size(min = 3, max = 1000,
            message = "Questions must be between 3 and 1000 characters.") String question) {
    }

    public record CompareRequest(@NotNull UUID documentA, @NotNull UUID documentB) {
    }

    private InvestigationView view(Investigation i) {
        List<EvidenceDocument> docs = investigations.documents(i.getId());
        return new InvestigationView(i.getId(), i.getTitle(), i.getDescription(), i.isDemo(), i.getCreatedAt(), i.getUpdatedAt(),
                (long) docs.size(), docs.stream().filter(d -> d.getStatus() == EvidenceDocument.Status.INDEXED).count());
    }

    private Investigation owned(UUID id) {
        return investigations.owned(id, AuthUser.current().id());
    }

    // ------------------------------------------------------------------ investigations

    @GetMapping
    public List<InvestigationView> list() {
        return investigations.list(AuthUser.current().id()).stream().map(this::view).toList();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public InvestigationView create(@Valid @RequestBody CreateRequest req) {
        return view(investigations.create(AuthUser.current().id(), req.title(), req.description(), false));
    }

    @PostMapping("/demo")
    @ResponseStatus(HttpStatus.CREATED)
    public InvestigationView loadDemo() {
        return view(demo.load(AuthUser.current().id()));
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable UUID id) {
        Investigation inv = owned(id);
        return Map.of("investigation", view(inv),
                "documents", investigations.documents(id).stream().map(DocumentView::of).toList());
    }

    @PatchMapping("/{id}")
    public InvestigationView rename(@PathVariable UUID id, @Valid @RequestBody CreateRequest req) {
        return view(investigations.rename(id, AuthUser.current().id(), req.title(), req.description()));
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID id) {
        investigations.delete(id, AuthUser.current().id());
    }

    // ------------------------------------------------------------------ documents

    @PostMapping(path = "/{id}/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> upload(@PathVariable UUID id, @RequestPart("files") List<MultipartFile> files) {
        owned(id);
        var results = documents.upload(id, files);
        investigations.touch(id);
        return Map.of("results", results);
    }

    @PostMapping("/{id}/documents/{docId}/retry")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public void retry(@PathVariable UUID id, @PathVariable UUID docId) {
        owned(id);
        documents.retry(id, docId);
    }

    @DeleteMapping("/{id}/documents/{docId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void deleteDocument(@PathVariable UUID id, @PathVariable UUID docId) {
        owned(id);
        documents.delete(id, docId);
    }

    @GetMapping("/{id}/documents/{docId}/content")
    public JsonNode documentContent(@PathVariable UUID id, @PathVariable UUID docId) {
        owned(id);
        return ai.get("/v1/collections/{c}/documents/{d}", id, docId);
    }

    @GetMapping(path = "/{id}/documents/{docId}/pages/{page}", produces = MediaType.IMAGE_PNG_VALUE)
    public ResponseEntity<byte[]> page(@PathVariable UUID id, @PathVariable UUID docId, @PathVariable int page,
            @RequestParam(required = false) String chunk, @RequestParam(required = false) String sentence,
            @RequestParam(defaultValue = "false") boolean flags) {
        owned(id);
        if (page < 1 || page > 10_000) {
            throw ApiException.badRequest("Invalid page.");
        }
        if (sentence != null && sentence.length() > 300) {
            sentence = sentence.substring(0, 300);
        }
        byte[] png = ai.pageImage(id, docId, page, chunk, sentence, flags);
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).contentType(MediaType.IMAGE_PNG).body(png);
    }

    @GetMapping("/{id}/chunks/{chunkId}")
    public JsonNode chunk(@PathVariable UUID id, @PathVariable String chunkId) {
        owned(id);
        return ai.get("/v1/collections/{c}/chunks/{k}", id, chunkId);
    }

    // ------------------------------------------------------------------ intelligence

    @PostMapping("/{id}/questions")
    public JsonNode ask(@PathVariable UUID id, @Valid @RequestBody AskRequest req) {
        owned(id);
        JsonNode answer = questions.ask(id, AuthUser.current().id(), req.question().trim());
        investigations.touch(id);
        return answer;
    }

    @GetMapping("/{id}/questions")
    public List<QuestionService.HistoryItem> history(@PathVariable UUID id) {
        owned(id);
        return questions.history(id);
    }

    @GetMapping("/{id}/questions/{questionId}")
    public JsonNode answer(@PathVariable UUID id, @PathVariable UUID questionId) {
        owned(id);
        return questions.answer(id, questionId);
    }

    @GetMapping("/{id}/conflicts")
    public JsonNode conflicts(@PathVariable UUID id) {
        owned(id);
        return ai.get("/v1/collections/{c}/conflicts", id);
    }

    @GetMapping("/{id}/security")
    public JsonNode security(@PathVariable UUID id) {
        owned(id);
        return ai.get("/v1/collections/{c}/security", id);
    }

    @GetMapping("/{id}/overview")
    public JsonNode overview(@PathVariable UUID id) {
        owned(id);
        return ai.get("/v1/collections/{c}/overview", id);
    }

    @PostMapping("/{id}/compare")
    public JsonNode compare(@PathVariable UUID id, @Valid @RequestBody CompareRequest req) {
        owned(id);
        var docs = investigations.documents(id);
        for (UUID d : List.of(req.documentA(), req.documentB())) {
            if (docs.stream().noneMatch(x -> x.getId().equals(d) && x.getStatus() == EvidenceDocument.Status.INDEXED)) {
                throw ApiException.badRequest("Both documents must be indexed documents of this investigation.");
            }
        }
        JsonNode result = ai.post("/v1/collections/{c}/compare",
                Map.of("document_a", req.documentA().toString(), "document_b", req.documentB().toString()), id);
        events.record(id, "compare", "Compared " + result.path("before").path("filename").asString("")
                + " with " + result.path("after").path("filename").asString(""),
                result.path("summary").toString());
        return result;
    }

    @GetMapping("/{id}/timeline")
    public List<EventView> timeline(@PathVariable UUID id) {
        owned(id);
        return events.timeline(id).stream().map(EventView::of).toList();
    }
}
